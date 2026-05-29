import json
import logging
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from decimal import Decimal
from .models import Market, Bet
from payments.models import Transaction
from users.models import CustomUser
from api.validators import normalize_phone_number
from .utils.price_calculations import PAYOUT_PER_SHARE

logger = logging.getLogger(__name__)

def get_authenticated_user(request):
    """
    Get authenticated user from either:
    1. Session (if session cookie exists)
    2. X-User-Phone-Number header (for phone auth development)
    3. Email from localStorage sent via X-User-Email header (for Google OAuth users)
    """
    # First try session
    if request.user and request.user.is_authenticated:
        logger.info(f"User authenticated via session: {request.user.id}")
        return request.user
    
    logger.debug(f"Session check failed - request.user: {request.user}, is_authenticated: {request.user.is_authenticated if request.user else 'N/A'}")
    
    # Fallback to phone number header (for traditional auth)
    phone_number = request.headers.get('X-User-Phone-Number')
    if phone_number:
        try:
            # Normalize phone number
            phone_number = normalize_phone_number(phone_number)
            user = CustomUser.objects.get(phone_number=phone_number)
            if user.is_active:
                logger.info(f"User authenticated via phone header: {phone_number}")
                return user
        except CustomUser.DoesNotExist:
            logger.debug(f"Phone number not found: {phone_number}")
    
    # Fallback to email header (for Google OAuth users)
    email = request.headers.get('X-User-Email')
    if email:
        try:
            user = CustomUser.objects.get(email=email)
            if user.is_active:
                logger.info(f"User authenticated via email header: {email}")
                return user
        except CustomUser.DoesNotExist:
            logger.debug(f"Email not found: {email}")
    
    logger.warning(f"No authentication method worked. Headers: {dict(request.headers)}")
    return None

@csrf_exempt
@require_http_methods(["GET"])
def user_dashboard(request):
    # Check authentication
    user = get_authenticated_user(request)
    if not user:
        logger.warning(f"Dashboard access denied - user not authenticated")
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    user_identifier = user.phone_number or user.email or f"ID:{user.id}"
    logger.info(f"Dashboard loaded for user: {user_identifier}")
    
    try:
        
        # Get user bets with market info - only BUY actions for portfolio
        bets = Bet.objects.filter(user=user).select_related('market').order_by('-timestamp')
        
        bets_data = []
        portfolio_value = Decimal('0.00')
        
        # Track net positions for portfolio calculation: (market_id, outcome) -> net_quantity
        net_positions = {}
        
        for bet in bets:
            bets_data.append({
                'id': bet.id,
                'market_id': bet.market.id,
                'market_question': bet.market.question,
                'outcome': bet.outcome,
                'amount': str(bet.amount),
                'entry_probability': bet.entry_probability,
                'result': bet.result,
                'payout': str(bet.payout) if bet.payout else None,
                'timestamp': bet.timestamp.isoformat(),
                # Current market state for position value calculation
                'current_yes_probability': bet.market.yes_probability,
                'market_q_yes': float(bet.market.q_yes),
                'market_q_no': float(bet.market.q_no),
                'market_b': float(bet.market.b),
            })
            
            # For PENDING bets, accumulate net positions (BUY adds, SELL subtracts)
            if bet.result == 'PENDING':
                position_key = (bet.market.id, bet.outcome)
                share_quantity = float(bet.quantity or 1)
                
                if position_key not in net_positions:
                    net_positions[position_key] = {
                        'net_quantity': 0,
                        'market': bet.market,
                        'outcome': bet.outcome,
                    }
                
                # Add for BUY, subtract for SELL
                if bet.action == 'BUY':
                    net_positions[position_key]['net_quantity'] += share_quantity
                elif bet.action == 'SELL':
                    net_positions[position_key]['net_quantity'] -= share_quantity
        
        # Calculate portfolio value based on net positions
        for position_key, position_data in net_positions.items():
            net_quantity = position_data['net_quantity']
            market = position_data['market']
            outcome = position_data['outcome']
            
            # Skip if net position is zero or negative (all shares sold or oversold)
            if net_quantity <= 0:
                continue
            
            # Calculate market probability
            from markets.lmsr import price_yes
            
            try:
                market_price = price_yes(
                    float(market.q_yes),
                    float(market.q_no),
                    float(market.b)
                )
            except:
                market_price = float(market.yes_probability) / 100.0
            
            # Determine winning probability based on outcome
            if outcome == 'Yes':
                winning_prob = market_price
            else:
                winning_prob = 1.0 - market_price
            
            # Position value = net_quantity * max_payout * probability
            position_value = Decimal(str(net_quantity)) * Decimal(str(PAYOUT_PER_SHARE)) * Decimal(str(winning_prob))
            portfolio_value += position_value
        
        # Get user statistics
        stats = user.get_user_statistics()
        
        return JsonResponse({
            'user': {
                'id': user.id,
                'phone_number': user.phone_number,
                'full_name': user.full_name,
                'balance': str(user.balance),
                'kyc_verified': user.kyc_verified,
                'joined': user.date_joined.isoformat()
            },
            'statistics': stats,
            'bets': bets_data,
            'total_bets': len(bets_data),
            'portfolio': {
                'total_value': str(portfolio_value.quantize(Decimal('0.01')))
            }
        })
    except Exception as e:
        logger.error(f"Dashboard error for user {user.phone_number if user else 'unknown'}: {str(e)}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def transaction_history(request):
    # Check authentication
    user = get_authenticated_user(request)
    if not user:
        logger.warning(f"History access denied - user not authenticated")
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    try:
        user_identifier = user.phone_number or user.email or f"ID:{user.id}"
        logger.info(f"Transaction history loaded for user: {user_identifier}")
        transactions = Transaction.objects.filter(user=user)[:50]  # Last 50 transactions
        
        transactions_data = []
        for txn in transactions:
            transactions_data.append({
                'id': txn.id,
                'type': txn.type,
                'amount': str(txn.amount),
                'status': txn.status,
                'description': txn.description,
                'created_at': txn.created_at.isoformat()
            })
        
        return JsonResponse({
            'transactions': transactions_data,
            'total': len(transactions_data)
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["POST"])
@csrf_exempt
@require_http_methods(["POST"])
def initiate_withdrawal(request):
    """Initiate M-Pesa withdrawal for user"""
    # Get authenticated user from session or header
    user = get_authenticated_user(request)
    if not user:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    try:
        data = json.loads(request.body)
        amount = Decimal(str(data.get('amount')))
        
        if not amount or amount <= 0:
            return JsonResponse({'error': 'Invalid amount'}, status=400)
        
        # Check if user has enough balance
        if amount > user.balance:
            return JsonResponse({'error': f'Insufficient balance. Available: KES {user.balance}'}, status=400)
        
        # Deduct from balance immediately (can be refunded if withdrawal fails)
        user.balance -= amount
        user.save()
        
        # Create transaction record
        transaction = Transaction.objects.create(
            user=user,
            type='WITHDRAWAL',
            amount=amount,
            phone_number=user.phone_number,
            status='PENDING',
            description=f'Withdrawal of KES {amount}'
        )
        
        # TODO: Integrate with M-Pesa API to send money
        # For now, simulate successful withdrawal
        transaction.status = 'COMPLETED'
        transaction.save()
        
        return JsonResponse({
            'message': 'Withdrawal initiated successfully',
            'transaction_id': transaction.id,
            'amount': str(amount),
            'new_balance': str(user.balance)
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
