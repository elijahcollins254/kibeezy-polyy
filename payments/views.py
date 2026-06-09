import json
import logging
from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from decimal import Decimal
from .mpesa_integration import get_mpesa_client
from .models import Transaction
from .transaction_safety import (
    safe_process_deposit, 
    safe_process_withdrawal,
    verify_user_balance_consistency,
    TransactionError
)
from api.validators import validate_amount, normalize_phone_number, ValidationError
from users.models import CustomUser
from notifications.views import create_notification
from brokerage.services.ledger import (
    record_deposit_and_update_balance,
    record_withdrawal_success_and_update_balance,
    record_withdrawal_reversal_and_update_balance,
)
logger = logging.getLogger(__name__)

@csrf_exempt
@require_http_methods(["GET"])
def test_mpesa_credentials(request):
    """Test if M-Pesa credentials are valid"""
    try:
        client = get_mpesa_client()
        token = client.get_access_token()
        
        if token:
            return JsonResponse({
                'status': 'success',
                'message': 'M-Pesa credentials are valid',
                'token': token[:20] + '...'  # Show first 20 chars only
            })
        else:
            return JsonResponse({
                'status': 'error',
                'message': 'Failed to get access token'
            }, status=400)
    except Exception as e:
        logger.error(f"Credential test error: {str(e)}")
        return JsonResponse({
            'status': 'error',
            'message': f'Credential validation failed: {str(e)}'
        }, status=400)

def get_authenticated_user(request):
    """Get authenticated user from session or X-User-Phone-Number/X-User-Email header"""
    # Try session-based auth first
    if request.user and request.user.is_authenticated:
        return request.user
    
    # Fall back to phone number header-based auth
    phone_number = request.headers.get('X-User-Phone-Number')
    if phone_number:
        try:
            # Normalize phone number
            phone_number = normalize_phone_number(phone_number)
            return CustomUser.objects.get(phone_number=phone_number)
        except CustomUser.DoesNotExist:
            return None
    
    # Fall back to email header-based auth (for Google OAuth users)
    email = request.headers.get('X-User-Email')
    if email:
        try:
            return CustomUser.objects.get(email=email)
        except CustomUser.DoesNotExist:
            return None
    
    return None



@csrf_exempt
@require_http_methods(["POST"])
def initiate_stk_push(request):
    # Get authenticated user from session or header
    user = get_authenticated_user(request)
    if not user:
        logger.warning(f"Unauthorized STK push attempt")
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    # TODO: Add KYC verification check once onboarding flow is ready
    # For now, allow all authenticated users to make deposits
    
    try:
        data = json.loads(request.body)
        amount = data.get('amount')
        
        # Validate amount using validators
        if not amount:
            return JsonResponse({'error': 'Amount is required'}, status=400)
        
        try:
            amount = validate_amount(amount, min_amount=Decimal('1'), max_amount=Decimal('150000'))
        except ValidationError as e:
            return JsonResponse({'error': e.message}, status=400)
        
        # Get M-Pesa client (real or mock)
        client = get_mpesa_client()
        
        # Initiate STK push
        response = client.initiate_stk_push(
            user.phone_number,
            amount,
            account_reference=f"CACHE_{user.id}"
        )
        
        if response.get('ResponseCode') == '0':
            # Create a pending transaction
            transaction = Transaction.objects.create(
                user=user,
                type='DEPOSIT',
                amount=amount,
                phone_number=user.phone_number,
                checkout_request_id=response.get('CheckoutRequestID'),
                merchant_request_id=response.get('MerchantRequestID'),
                status='PENDING',
                description=f'M-Pesa deposit of KES {amount}'
            )
            
            logger.info(f"STK Push initiated for user {user.phone_number}, amount: {amount}")
            return JsonResponse({
                'message': 'STK Push initiated successfully',
                'checkout_id': response.get('CheckoutRequestID'),
                'transaction_id': transaction.id,
                'customer_message': response.get('CustomerMessage', 'Check your phone for M-Pesa prompt')
            })
        else:
            return JsonResponse({
                'error': response.get('ResponseDescription', 'Failed to initiate STK Push'),
                'customer_message': response.get('CustomerMessage', 'Payment initiation failed')
            }, status=400)
            
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except ValidationError as e:
        return JsonResponse({'error': e.message}, status=400)
    except Exception as e:
        logger.error(f"STK Push error: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def initiate_withdrawal(request):
    """Initiate B2C withdrawal/payout to user's M-Pesa account"""
    # Get authenticated user from session or header
    user = get_authenticated_user(request)
    if not user:
        logger.warning(f"Unauthorized withdrawal attempt")
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    try:
        data = json.loads(request.body)
        amount = data.get('amount')
        
        # Validate amount
        if not amount:
            return JsonResponse({'error': 'Amount is required'}, status=400)
        
        try:
            amount = validate_amount(amount, min_amount=Decimal('10'), max_amount=Decimal('150000'))
        except ValidationError as e:
            return JsonResponse({'error': e.message}, status=400)
        
        # Check user has sufficient balance
        if user.balance < amount:
            return JsonResponse({
                'error': 'Insufficient balance',
                'current_balance': float(user.balance),
                'requested_amount': float(amount)
            }, status=400)
        
        # Validate user has phone number
        if not user.phone_number:
            return JsonResponse({
                'error': 'Phone number not set on account',
                'action': 'update_profile'
            }, status=400)
        
        # Create pending withdrawal transaction with user's phone number
        transaction = Transaction.objects.create(
            user=user,
            type='WITHDRAWAL',
            amount=amount,
            phone_number=user.phone_number,  # User receiving the funds
            status='PENDING',
            description=f'M-Pesa withdrawal of KES {amount}'
        )
        
        # Get M-Pesa client and initiate B2C payment
        client = get_mpesa_client()
        
        response = client.b2c_payment(
            user.phone_number,  # User's phone receives the payout
            amount,
            description=f'CACHE withdrawal'
        )
        
        if response.get('ResponseCode') == '0':
            # Update transaction with B2C details
            transaction.merchant_request_id = response.get('ConversationID')
            transaction.checkout_request_id = response.get('OriginatorConversationID')
            transaction.save()
            
            # DO NOT deduct balance yet - wait for callback to confirm success
            # Balance will be deducted in b2c_result_callback when result_code == 0
            
            # Create notification
            create_notification(
                user=user,
                type_choice='WITHDRAWAL_INITIATED',
                title='Withdrawal Initiated',
                message=f'Your withdrawal of KES {amount} has been initiated to {user.phone_number}',
                color_class='blue',
                related_transaction_id=transaction.id
            )
            
            logger.info(f"Withdrawal initiated for user {user.phone_number}, amount: {amount}, balance NOT yet deducted")
            return JsonResponse({
                'message': 'Withdrawal initiated successfully',
                'transaction_id': transaction.id,
                'conversation_id': response.get('ConversationID'),
                'amount': float(amount),
                'status': 'PENDING'
            })
        else:
            # B2C initiation failed
            transaction.status = 'FAILED'
            transaction.description = response.get('ResponseDescription', 'B2C payment initiation failed')
            transaction.save()
            
            return JsonResponse({
                'error': response.get('ResponseDescription', 'Failed to process withdrawal'),
                'customer_message': response.get('CustomerMessage', 'Withdrawal processing failed')
            }, status=400)
            
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except ValidationError as e:
        return JsonResponse({'error': e.message}, status=400)
    except Exception as e:
        logger.error(f"Withdrawal error: {str(e)}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def b2c_result_callback(request):
    """
    Handle B2C result callback from M-Pesa Daraja API
        CSRF EXEMPTION: This endpoint is @csrf_exempt because:
    - Safaricom sends server-to-server POST callbacks (not from a browser)
    - Cannot include CSRF tokens in callback payloads
    - Safaricom servers are whitelisted in CSRF_TRUSTED_ORIGINS for extra security
    - Request validation is done by matching OriginatorConversationID to stored transactions
        Safaricom will POST result to ResultURL with callback containing:
    - Result (0 = success)
    - ResultCode (0 = success)
    - OriginatorConversationID or ExternalReference (to match transaction)
    - ResponseDescription
    - ConversationID
    
    Flow:
    1. Parse callback data
    2. Find matching Transaction by external_ref or conversation_id
    3. If success: mark COMPLETED and credit user wallet
    4. If failed: mark FAILED and optionally retry
    5. Respond with 200 OK to Daraja
    """
    import logging
    from django.db import transaction as db_transaction
    
    logger = logging.getLogger(__name__)
    
    try:
        data = json.loads(request.body)
        logger.info(f"🔔 B2C callback received at {timezone.now().isoformat()}")
        logger.info(f"   Full payload: {json.dumps(data, indent=2)}")
        
        # Extract key fields from callback
        # Daraja may send different field names in Result and in timeout callback
        # NOTE: Use 'is not None' to handle ResultCode=0 (which is falsy but valid)
        result_code = data.get('Result', {}).get('ResultCode')
        if result_code is None:
            result_code = data.get('ResultCode')
        external_ref = (
            data.get('Result', {}).get('ExternalReference') or 
            data.get('ExternalReference') or
            data.get('MerchantRequestID')
        )
        conversation_id = (
            data.get('Result', {}).get('ConversationID') or 
            data.get('ConversationID')
        )
        originator_conv_id = (
            data.get('Result', {}).get('OriginatorConversationID') or 
            data.get('OriginatorConversationID')
        )
        response_description = (
            data.get('Result', {}).get('ResponseDescription') or 
            data.get('ResponseDescription', 'No description')
        )
        
        logger.info(f"   Extracted fields:")
        logger.info(f"   - ResultCode: {result_code}")
        logger.info(f"   - ExternalReference: {external_ref}")
        logger.info(f"   - OriginatorConversationID: {originator_conv_id}")
        logger.info(f"   - ConversationID: {conversation_id}")
        logger.info(f"   - ResponseDescription: {response_description}")
        
        if not external_ref and not conversation_id and not originator_conv_id:
            logger.warning(f"❌ B2C callback missing identifiers: {data}")
            return JsonResponse({'status': 'error', 'message': 'Missing identifiers'}, status=400)
        
        # Find transaction by external_ref, originator_conv_id, or conversation_id
        tx = None
        lookup_methods = []
        
        try:
            # Method 1: external_ref
            if external_ref:
                lookup_methods.append(f"by external_ref={external_ref}")
                tx = Transaction.objects.get(external_ref=external_ref)
                logger.info(f"✅ Found transaction {tx.id} by external_ref")
        except Transaction.DoesNotExist:
            logger.info(f"   Not found by external_ref")
        
        if not tx:
            try:
                # Method 2: checkout_request_id (stores OriginatorConversationID)
                if originator_conv_id:
                    lookup_methods.append(f"by checkout_request_id={originator_conv_id}")
                    tx = Transaction.objects.get(checkout_request_id=originator_conv_id)
                    logger.info(f"✅ Found transaction {tx.id} by checkout_request_id (OriginatorConversationID)")
            except Transaction.DoesNotExist:
                logger.info(f"   Not found by checkout_request_id/OriginatorConversationID")
        
        if not tx:
            try:
                # Method 3: merchant_request_id (stores ConversationID)
                if conversation_id:
                    lookup_methods.append(f"by merchant_request_id={conversation_id}")
                    tx = Transaction.objects.get(merchant_request_id=conversation_id)
                    logger.info(f"✅ Found transaction {tx.id} by merchant_request_id (ConversationID)")
            except Transaction.DoesNotExist:
                logger.info(f"   Not found by merchant_request_id/ConversationID")
        
        if not tx:
            # Method 4: Search by mpesa_response JSON
            lookup_methods.append(f"by mpesa_response JSON")
            tx = Transaction.objects.filter(
                type='WITHDRAWAL',
                status='PENDING',
                mpesa_response__contains={'originator_conversation_id': originator_conv_id}
            ).first()
            if tx:
                logger.info(f"✅ Found transaction {tx.id} by mpesa_response.originator_conversation_id")
        
        if not tx:
            logger.warning(f"❌ Transaction not found. Attempted lookups: {lookup_methods}")
            # Still respond 200 OK so Daraja doesn't keep retrying
            return JsonResponse({'status': 'error', 'message': 'transaction_not_found'})
        
        logger.info(f"✅ Matched transaction {tx.id} for user {tx.user.phone_number}")
        
        # Check result code (0 = success)
        is_success = result_code == 0 or result_code == '0'
        
        with db_transaction.atomic():
            # Idempotency: check if already processed
            if tx.status == 'COMPLETED':
                logger.info(f"Transaction {tx.id} already marked COMPLETED, skipping")
                return JsonResponse({'status': 'ok', 'message': 'already_processed'})

            if is_success:
                # Payment successful
                logger.info(f"B2C payout success for transaction {tx.id}, recipient {tx.user.phone_number}")

                # Record ledger withdrawal and update user.balance atomically
                try:
                    ledger_tx, updated_balance = record_withdrawal_success_and_update_balance(
                        tx.user,
                        tx.amount,
                        reference=f"payments:{tx.id}",
                        metadata={'payments_tx': tx.id}
                    )
                except Exception as e:
                    logger.error(f"Ledger withdrawal recording failed: {e}")
                    # Mark transaction failed for manual review
                    tx.status = 'FAILED'
                    tx.mpesa_response = tx.mpesa_response or {}
                    tx.mpesa_response.update({
                        'callback_success': False,
                        'callback_result_code': result_code,
                        'callback_description': f"Ledger write failed: {e}",
                        'callback_time': timezone.now().isoformat()
                    })
                    tx.save()
                    return JsonResponse({'status': 'error', 'message': 'ledger_failure'}, status=200)

                # Update payment transaction
                tx.status = 'COMPLETED'
                tx.mpesa_response = tx.mpesa_response or {}
                tx.mpesa_response.update({
                    'callback_success': True,
                    'callback_result_code': result_code,
                    'callback_description': response_description,
                    'callback_time': timezone.now().isoformat(),
                    'ledger_tx_id': getattr(ledger_tx, 'id', None),
                })
                tx.save()

                logger.info(
                    f"Withdrawal completed and balance deducted: tx_id={tx.id}, user={tx.user.phone_number}, "
                    f"amount={tx.amount}, new_balance={updated_balance}"
                )

                # Send notification
                _send_payout_notification(tx.user, tx)

            else:
                # Payment failed
                logger.warning(
                    f"B2C payout failed for transaction {tx.id}, code={result_code}, "
                    f"description={response_description}"
                )

                # Attempt to record reversal in ledger and update balance atomically
                reversal_meta = {}
                try:
                    reversal_tx = record_withdrawal_reversal_and_update_balance(
                        tx.user,
                        tx.amount,
                        reference=f"payments_reversal:{tx.id}",
                        metadata={'payments_tx': tx.id}
                    )
                    # function returns (tx, updated_balance) in our implementation
                    if isinstance(reversal_tx, tuple):
                        reversal_tx_obj = reversal_tx[0]
                    else:
                        reversal_tx_obj = reversal_tx
                    reversal_meta['ledger_reversal_id'] = getattr(reversal_tx_obj, 'id', None)
                except Exception as e:
                    logger.error(f"Failed to record withdrawal reversal in ledger: {e}")
                    reversal_meta['reversal_error'] = str(e)

                tx.status = 'FAILED'
                tx.mpesa_response = tx.mpesa_response or {}
                tx.mpesa_response.update({
                    'callback_success': False,
                    'callback_result_code': result_code,
                    'callback_description': response_description,
                    'callback_time': timezone.now().isoformat(),
                    **reversal_meta,
                })
                tx.save()

                logger.info(
                    f"User {tx.user.phone_number} refunded KES {tx.amount} due to failed payout"
                )

                # Log for manual review / retry
                logger.error(
                    f"Payout failed: tx_id={tx.id}, user={tx.user.phone_number}, "
                    f"amount={tx.amount}, code={result_code}"
                )
        
        # Always respond 200 OK to Daraja
        return JsonResponse({'status': 'ok'}, status=200)
    
    except json.JSONDecodeError:
        logger.error("B2C callback: invalid JSON")
        return JsonResponse({'error': 'invalid_json'}, status=400)
    except Exception as e:
        logger.error(f"B2C callback processing error: {e}", exc_info=True)
        # Still return 200 to prevent Daraja retries
        return JsonResponse({'status': 'error', 'message': str(e)}, status=200)


def _send_payout_notification(user, transaction):
    """
    Send user a notification of successful payout (SMS, in-app, etc)
    (Placeholder for future notification system)
    """
    # TODO: implement notification system
    # e.g., send SMS via Africastalking
    # e.g., create in-app notification record
    logger = logging.getLogger(__name__)
    logger.info(f"Payout notification: User {user.phone_number} received KES {transaction.amount}")


@ensure_csrf_cookie
@require_http_methods(["GET"])
def get_transaction_status(request, transaction_id):
    """Get the status of a transaction"""
    try:
        # Get authenticated user from session or header
        user = get_authenticated_user(request)
        if not user:
            return JsonResponse({'error': 'Authentication required'}, status=401)
        
        try:
            transaction = Transaction.objects.get(id=transaction_id, user=user)
        except Transaction.DoesNotExist:
            return JsonResponse({'error': 'Transaction not found'}, status=404)
        
        response = {
            'id': transaction.id,
            'status': transaction.status,
            'amount': float(transaction.amount),
            'type': transaction.type,
            'created_at': transaction.created_at.isoformat()
        }
        
        # Include error message if payment failed
        if transaction.status == 'FAILED' and transaction.description:
            response['error_message'] = transaction.description
        
        return JsonResponse(response)
    
    except Exception as e:
        logger.error(f"Transaction status error: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def sync_withdrawal_status(request):
    """
    MANUAL ENDPOINT: Sync withdrawal status from M-Pesa
    
    For debugging/manual testing when callbacks might be delayed or failed.
    Checks if a pending withdrawal has been processed by M-Pesa.
    
    Request:
        {
            "transaction_id": 123
        }
    
    Returns:
        {
            "status": "COMPLETED" | "FAILED" | "PENDING",
            "amount": 500.00,
            "message": "...",
            "mpesa_response": {...}
        }
    """
    try:
        user = get_authenticated_user(request)
        if not user:
            return JsonResponse({'error': 'Authentication required'}, status=401)
        
        data = json.loads(request.body)
        transaction_id = data.get('transaction_id')
        
        if not transaction_id:
            return JsonResponse({'error': 'transaction_id is required'}, status=400)
        
        try:
            transaction = Transaction.objects.get(id=transaction_id, user=user, type='WITHDRAWAL')
        except Transaction.DoesNotExist:
            return JsonResponse({'error': 'Withdrawal transaction not found'}, status=404)
        
        # Only sync if still pending
        if transaction.status != 'PENDING':
            return JsonResponse({
                'status': transaction.status,
                'amount': float(transaction.amount),
                'message': f'Withdrawal is {transaction.status}',
                'mpesa_response': transaction.mpesa_response
            })
        
        # Transaction is pending - return current state
        # Note: M-Pesa doesn't provide a query API for B2C like it does for STK Push
        # The status will be updated via callback from M-Pesa
        logger.info(f"Sync request for pending withdrawal tx_id={transaction.id}")
        
        return JsonResponse({
            'status': 'PENDING',
            'amount': float(transaction.amount),
            'message': 'Withdrawal is pending. M-Pesa will send status via callback. Check back in a moment.',
            'external_ref': transaction.external_ref,
            'checkout_request_id': transaction.checkout_request_id,
            'merchant_request_id': transaction.merchant_request_id,
            'created_at': transaction.created_at.isoformat(),
            'last_updated': transaction.updated_at.isoformat()
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Sync withdrawal status error: {str(e)}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def mpesa_callback(request):
    """Handle M-Pesa callback to update transaction and user balance"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            logger.info(f"M-Pesa callback received: {json.dumps(data)}")
            
            # Get M-Pesa client
            client = get_mpesa_client()
            
            # Validate and process callback
            result = client.validate_callback(data)
            
            if not result:
                return JsonResponse({'error': 'Invalid callback data'}, status=400)
            
            checkout_request_id = result.get('checkout_request_id')
            
            try:
                transaction = Transaction.objects.get(checkout_request_id=checkout_request_id)
            except Transaction.DoesNotExist:
                logger.warning(f"Transaction not found for checkout_request_id: {checkout_request_id}")
                return JsonResponse({'error': 'Transaction not found'}, status=404)
            
            # Idempotency check: if transaction is already COMPLETED, don't re-process
            if transaction.status == 'COMPLETED':
                logger.info(f"✓ Transaction {transaction.id} already completed, ignoring duplicate callback")
                return JsonResponse({'status': 'success', 'message': 'Transaction already processed'}, status=200)
            
            if result.get('status') == 'COMPLETED':
                # Payment successful - record ledger deposit and sync user.balance atomically
                try:
                    from django.db import transaction as db_transaction
                    with db_transaction.atomic():
                        user = transaction.user

                        # Verify user is active
                        if not user.is_active:
                            raise TransactionError("User account is inactive")

                        try:
                            ledger_tx, updated_balance = record_deposit_and_update_balance(
                                user,
                                transaction.amount,
                                reference=f"payments:{transaction.id}",
                                metadata={'payments_tx': transaction.id}
                            )
                        except Exception as e:
                            raise TransactionError(f"Ledger deposit failed: {e}")

                        # Update existing payment transaction record
                        transaction.status = 'COMPLETED'
                        transaction.receipt_number = result.get('receipt_number')
                        transaction.mpesa_response = {
                            'receipt_number': result.get('receipt_number'),
                            'checkout_request_id': transaction.checkout_request_id,
                            'ledger_tx_id': getattr(ledger_tx, 'id', None),
                        }
                        transaction.description = f"Deposit successful: KES {transaction.amount}"
                        transaction.save()

                        logger.info(f"✅ Payment successful for user {user.phone_number}, amount: {transaction.amount}, new balance: {updated_balance}")

                    # Verify balance consistency
                    balance_check = verify_user_balance_consistency(user.id)
                    if not balance_check['is_consistent']:
                        logger.warning(f"⚠️ Balance inconsistency detected after deposit: {balance_check}")

                    # Create notification
                    create_notification(
                        user=user,
                        type_choice='DEPOSIT_CONFIRMED',
                        title='Deposit Confirmed',
                        message=f'Your deposit of KES {transaction.amount} has been confirmed',
                        color_class='green',
                        related_transaction_id=transaction.id
                    )

                except TransactionError as e:
                    logger.error(f"❌ Transaction processing failed for deposit {transaction.id}: {str(e)}")
                    transaction.status = 'FAILED'
                    # Truncate error message to fit 200-char field
                    error_msg = str(e)
                    transaction.description = error_msg[:190] if len(error_msg) > 190 else error_msg
                    transaction.save()
                    # Notify user of processing issue
                    create_notification(
                        user=transaction.user,
                        type_choice='DEPOSIT_FAILED',
                        title='Deposit Processing Error',
                        message='Your deposit was received but could not be credited. Please contact support.',
                        color_class='red',
                        related_transaction_id=transaction.id
                    )
                except Exception as e:
                    logger.error(f"❌ Unexpected error processing deposit {transaction.id}: {str(e)}")
                    transaction.status = 'FAILED'
                    # Truncate error message to fit 200-char field
                    error_msg = str(e)
                    transaction.description = error_msg[:190] if len(error_msg) > 190 else error_msg
                    transaction.save()
            else:
                # Payment failed - extract M-Pesa error message
                result_desc = result.get('result_desc', 'Payment failed. Please try again.')
                
                transaction.status = 'FAILED'
                # Truncate error message to fit 200-char field
                full_msg = f"M-Pesa error: {result_desc}"
                transaction.description = full_msg[:190] if len(full_msg) > 190 else full_msg
                transaction.save()
                
                # Create notification
                user = transaction.user
                create_notification(
                    user=user,
                    type_choice='DEPOSIT_FAILED',
                    title='Deposit Failed',
                    message=result_desc,
                    color_class='red',
                    related_transaction_id=transaction.id
                )
                
                logger.warning(f"❌ Payment failed for transaction {transaction.id}: {result_desc}")
                
            return JsonResponse({
                'message': 'Callback processed',
                'status': transaction.status,
                'description': transaction.description
            })
        
        except Exception as e:
            logger.error(f"Callback processing error: {str(e)}", exc_info=True)
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'error': 'Method not allowed'}, status=405)


@csrf_exempt
@require_http_methods(["GET"])
def get_user_transactions(request):
    """Get all transactions for a user"""
    user = get_authenticated_user(request)
    if not user:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    try:
        transactions = Transaction.objects.filter(user=user).order_by('-created_at')
        
        data = [
            {
                'id': txn.id,
                'type': txn.type,
                'amount': str(txn.amount),
                'status': txn.status,
                'description': txn.description or '',
                'created_at': txn.created_at.isoformat(),
                'reference': txn.reference or '',
            }
            for txn in transactions
        ]
        
        return JsonResponse(data, safe=False)
    except Exception as e:
        logger.error(f"Error fetching transactions: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)
