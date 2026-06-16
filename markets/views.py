import json
import logging
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.db import models
from django.utils import timezone
from django.conf import settings
from decimal import Decimal
from .models import Market, Bet, ChatMessage
from .services import (
    buy_yes_shares,
    buy_no_shares,
    sell_yes_shares,
    sell_no_shares,
    get_market_prices,
    is_market_open,
)
from .bitcoin_service import BitcoinPriceService
from payments.models import Transaction
from api.validators import validate_amount, validate_bet_outcome, ValidationError
from users.models import CustomUser
from notifications.views import create_notification
from brokerage.services.fee_service import FeeService


def parse_volume_value(volume_str: str) -> int:
    """Convert a formatted volume string to an integer amount in KES."""
    if not volume_str:
        return 0
    normalized = volume_str.replace('KES', '').replace('KES', '').replace(' ', '').strip()
    if normalized.endswith(('M', 'm')):
        try:
            return int(float(normalized[:-1]) * 1_000_000)
        except ValueError:
            return 0
    if normalized.endswith(('K', 'k')):
        try:
            return int(float(normalized[:-1]) * 1_000)
        except ValueError:
            return 0
    try:
        return int(float(normalized))
    except ValueError:
        return 0


def format_volume_value(amount: int) -> str:
    """Format a KES amount into a human-readable volume string."""
    if amount >= 1_000_000:
        return f"KES {amount / 1_000_000:.1f}M".replace('.0M', 'M')
    if amount >= 1_000:
        return f"KES {amount / 1_000:.1f}K".replace('.0K', 'K')
    return f"KES {amount}"

logger = logging.getLogger(__name__)

def get_authenticated_user(request):
    """
    Get authenticated user from either:
    1. Session (if session cookie exists)
    2. X-User-Phone-Number header (for phone auth)
    3. X-User-Email header (for Google OAuth users)
    """
    # Try session-based auth first
    if request.user and request.user.is_authenticated:
        return request.user
    
    # Fall back to phone number header (phone auth)
    phone_number = request.headers.get('X-User-Phone-Number')
    if phone_number:
        try:
            user = CustomUser.objects.get(phone_number=phone_number)
            if user.is_active:
                return user
        except CustomUser.DoesNotExist:
            pass
    
    # Fall back to email header (Google OAuth)
    email = request.headers.get('X-User-Email')
    if email:
        try:
            user = CustomUser.objects.get(email=email)
            if user.is_active:
                return user
        except CustomUser.DoesNotExist:
            pass
    
    return None


def list_markets(request):
    """
    List all markets, grouping markets with the same question.
    Markets with identical questions are grouped as OPTION_LIST markets on the frontend.
    This creates a Polymarket-like UI where only one card per question is shown on home page,
    and all options are displayed inside the market detail page.
    """
    markets = Market.objects.all().order_by('question', 'id')
    grouped_markets = {}
    
    for market in markets:
        # Determine effective status based on trading_end_time
        effective_status = market.status
        if market.status == 'OPEN' and market.trading_end_time and timezone.now() >= market.trading_end_time:
            effective_status = 'CLOSED'
        
        market_dict = {
            'id': market.id,
            'question': market.question,
            'category': market.category,
            'description': market.description,
            'image_url': market.image_url,
            'market_type': market.market_type,
            'yes_probability': market.yes_probability,
            'options': market.options,
            'volume': market.volume,
            'status': effective_status,
            'trading_end_time': market.trading_end_time.isoformat() if market.trading_end_time else None,
            'end_date': market.end_date,
            'resolved_outcome': market.resolved_outcome,
            'created_at': market.created_at.isoformat(),
            'y_probability': market.yes_probability,
            'no_probability': 100 - market.yes_probability,
            # LMSR state - required for frontend calculations
            'q_yes': float(market.q_yes),
            'q_no': float(market.q_no),
            'b': float(market.b),
        }
        
        # Add multiplier info for easier UX
        if market.yes_probability > 0 and market.yes_probability < 100:
            market_dict['yes_multiplier'] = round(100 / market.yes_probability, 2)
            market_dict['no_multiplier'] = round(100 / (100 - market.yes_probability), 2)
        
        # Group markets by question (for creating Polymarket-style multi-option displays)
        question_key = market.question
        
        if question_key not in grouped_markets:
            # First market with this question - use as base
            grouped_markets[question_key] = {
                'primary_market': market_dict,
                'related_markets': []
            }
        else:
            # Additional market with same question - add to related markets
            grouped_markets[question_key]['related_markets'].append(market_dict)
    
    # Convert grouped markets into final format
    markets_data = []
    for question, group in grouped_markets.items():
        primary = group['primary_market']
        related = group['related_markets']
        
        # If there are no related markets, just return the primary market as-is
        if not related:
            markets_data.append(primary)
        else:
            # If there are related markets with same question, convert to OPTION_LIST format
            # This groups them together as options for a single market card
            options = []
            
            # Add primary market as first option
            options.append({
                'id': primary['id'],
                'market_id': primary['id'],
                'label': primary.get('description', 'Option 1'),
                'yes_probability': primary['yes_probability'],
                'no_probability': primary['no_probability'],
                'volume': primary.get('volume', 'KES 0'),
                'status': primary['status'],
            })
            
            # Add related markets as additional options
            for related_market in related:
                options.append({
                    'id': related_market['id'],
                    'market_id': related_market['id'],
                    'label': related_market.get('description', 'Option'),
                    'yes_probability': related_market['yes_probability'],
                    'no_probability': related_market['no_probability'],
                    'volume': related_market.get('volume', 'KES 0'),
                    'status': related_market['status'],
                })
            
            # Return grouped market as OPTION_LIST
            grouped_market = {
                'id': primary['id'],  # Use primary market ID for routing
                'question': primary['question'],
                'category': primary['category'],
                'description': primary['description'],
                'image_url': primary['image_url'],
                'market_type': 'OPTION_LIST',  # Force to OPTION_LIST for display
                'options': options,
                'volume': primary['volume'],
                'status': primary['status'],
                'trading_end_time': primary['trading_end_time'],
                'end_date': primary['end_date'],
                'resolved_outcome': primary['resolved_outcome'],
                'created_at': primary['created_at'],
                'yes_probability': primary['yes_probability'],  # Primary market's probability
                'no_probability': primary['no_probability'],
                # LMSR state from primary market
                'q_yes': primary['q_yes'],
                'q_no': primary['q_no'],
                'b': primary['b'],
            }
            
            markets_data.append(grouped_market)
    
    return JsonResponse(markets_data, safe=False)

@csrf_exempt
@require_http_methods(["POST"])
def place_bet(request):
    # Get authenticated user from session or header
    user = get_authenticated_user(request)
    if not user:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    try:
        data = json.loads(request.body)
        market_id = data.get('market_id')
        outcome = data.get('outcome')
        amount = data.get('amount')

        if not all([market_id, outcome, amount]):
            return JsonResponse({'error': 'Missing bet details: market_id, outcome, amount'}, status=400)
        
        # Validate outcome
        try:
            outcome = validate_bet_outcome(outcome)
        except ValidationError as e:
            return JsonResponse({'error': e.message}, status=400)
        
        # Get action type early to determine amount validation
        action = data.get('action', 'buy').lower()
        if action not in ['buy', 'sell']:
            return JsonResponse({'error': 'Invalid action. Must be buy or sell'}, status=400)
        
        # Validate amount based on action type
        # For BUY: amount is KES (max 2 decimal places)
        # For SELL: amount is shares (can have higher precision for fractional shares)
        try:
            if action == 'buy':
                # BUY orders: amount in KES with max 2 decimal places
                amount = validate_amount(amount, min_amount=Decimal('1'), max_amount=Decimal('100000'))
            else:
                # SELL orders: amount is shares (can be fractional)
                amount = Decimal(str(amount))
                if amount <= 0:
                    raise ValidationError('Amount must be positive')
                if amount > Decimal('1000000'):
                    raise ValidationError('Amount cannot exceed 1,000,000 shares')
        except ValidationError as e:
            return JsonResponse({'error': e.message}, status=400)

        try:
            market = Market.objects.get(id=market_id)
        except Market.DoesNotExist:
            return JsonResponse({'error': 'Market not found'}, status=404)
        
        # Check if market is open (both status and trading_end_time)
        if market.status != 'OPEN':
            return JsonResponse({'error': f'Market is {market.status.lower()}'}, status=400)
        
        # Check if trading has ended
        if market.trading_end_time and timezone.now() >= market.trading_end_time:
            return JsonResponse({'error': 'Trading for this market has ended'}, status=400)
        
        # Handle OPTION_LIST markets
        option_id = None
        option_label = None
        entry_probability = market.yes_probability
        
        if market.market_type == 'OPTION_LIST':
            option_id = data.get('option_id')
            if not option_id:
                return JsonResponse({'error': 'option_id is required for option list markets'}, status=400)
            
            # Find the option and get its probability
            if market.options and isinstance(market.options, list):
                matching_option = next((opt for opt in market.options if opt.get('id') == option_id), None)
                if not matching_option:
                    return JsonResponse({'error': f'Option {option_id} not found'}, status=400)
                
                option_label = matching_option.get('label')
                if outcome == 'Yes':
                    entry_probability = matching_option.get('yes_probability', 50)
                else:
                    entry_probability = matching_option.get('no_probability', 50)
        
        # Get order type (MARKET or LIMIT)
        order_type = data.get('order_type', 'MARKET')
        if order_type not in ['MARKET', 'LIMIT']:
            order_type = 'MARKET'

        try:
            quantity = int(data.get('quantity', 1))
        except (TypeError, ValueError):
            return JsonResponse({'error': 'Quantity must be an integer'}, status=400)

        if quantity < 1:
            return JsonResponse({'error': 'Quantity must be at least 1'}, status=400)

        limit_price = None
        if order_type == 'LIMIT':
            limit_price_raw = data.get('limit_price')
            if limit_price_raw in [None, '']:
                return JsonResponse({'error': 'Limit price is required for limit orders'}, status=400)
            try:
                limit_price = validate_amount(limit_price_raw, min_amount=Decimal('0.01'), max_amount=Decimal('100'))
            except ValidationError as e:
                return JsonResponse({'error': e.message}, status=400)
        
        # For MARKET BUY orders with KES amounts, calculate fractional shares
        # For SELL orders, amount is already in shares
        calculated_quantity = Decimal(str(quantity))
        if order_type == 'MARKET' and action == 'buy' and market.market_type == 'BINARY':
            # Calculate shares based on amount and current probability
            current_price = Decimal(str(entry_probability))
            if current_price > 0:
                calculated_quantity = amount / current_price
            else:
                calculated_quantity = Decimal('1')
        elif order_type == 'MARKET' and action == 'sell':
            # For SELL orders, amount is already in shares
            calculated_quantity = amount
        
        # Handle balance for MARKET orders only (LIMIT orders don't deduct balance immediately)
        lmsr_result = None  # Will store LMSR result for balance updates
        
        # Calculate trading fee for all orders
        fee, total_cost = FeeService.get_total_cost(amount)
        
        if order_type == 'MARKET':
            if action == 'buy':
                # Check if user has sufficient balance for amount + fee
                required_balance = total_cost
                if required_balance > user.balance:
                    return JsonResponse({
                        'error': f'Insufficient balance. Need KES {total_cost} (KES {amount} + KES {fee} fee), but have KES {user.balance}'
                    }, status=400)
                # Deduct both amount and fee from balance
                user.balance -= required_balance
                user.save()
            else:  # sell - only deduct fee
                if fee > user.balance:
                    return JsonResponse({
                        'error': f'Insufficient balance for trading fee. Need KES {fee}, but have KES {user.balance}'
                    }, status=400)
                user.balance -= fee
                user.save()
        else:  # LIMIT order - validate but don't deduct yet
            if action == 'buy':
                # Check if user has sufficient balance for when order is filled (amount + fee)
                required_balance = total_cost
                if required_balance > user.balance:
                    return JsonResponse({
                        'error': f'Insufficient balance for limit order. Need KES {total_cost} (KES {amount} + KES {fee} fee), but have KES {user.balance}'
                    }, status=400)
            else:  # sell
                if fee > user.balance:
                    return JsonResponse({
                        'error': f'Insufficient balance for trading fee. Need KES {fee}'
                    }, status=400)
        
        # Validate shares for SELL orders (both MARKET and LIMIT)
        if action == 'sell':
            # Calculate available shares to sell for this market/outcome
            buy_quantity = Bet.objects.filter(
                user=user,
                market=market,
                outcome=outcome,
                action='BUY',
                option_id=option_id
            ).aggregate(total=models.Sum('quantity'))['total'] or 0
            
            sell_quantity = Bet.objects.filter(
                user=user,
                market=market,
                outcome=outcome,
                action='SELL',
                order_status='FILLED',
                option_id=option_id
            ).aggregate(total=models.Sum('quantity'))['total'] or 0
            
            available_quantity = buy_quantity - sell_quantity
            
            if amount > Decimal(str(available_quantity)):
                return JsonResponse({
                    'error': f'Cannot sell {amount} shares. You only own {available_quantity} shares of {outcome} on this market.'
                }, status=400)

        # Create the bet with appropriate order_status
        order_status = 'FILLED' if order_type == 'MARKET' else 'PENDING'
        bet = Bet.objects.create(
            user=user,
            market=market,
            outcome=outcome,
            amount=amount,
            trading_fee=fee,
            total_cost=total_cost,
            entry_probability=entry_probability,
            option_id=option_id,
            option_label=option_label,
            order_type=order_type,
            limit_price=limit_price,
            quantity=calculated_quantity,
            action=action.upper(),
            order_status=order_status,
        )
        
        # Create transaction record only for MARKET orders
        if order_type == 'MARKET':
            transaction_type = 'BET_SELL' if action == 'sell' else 'BET'
            if market.market_type == 'OPTION_LIST' and option_label:
                description = f'Position closed on: {option_label}' if action == 'sell' else f'Bet placed on: {option_label}'
            else:
                description = f'Position closed on: {market.question}' if action == 'sell' else f'Bet placed on: {market.question}'
            
            Transaction.objects.create(
                user=user,
                type=transaction_type,
                amount=total_cost,
                phone_number=user.phone_number,
                status='COMPLETED',
                description=description,
                related_bet=bet,
                metadata={
                    'base_amount': str(amount),
                    'trading_fee': str(fee),
                    'fee_pct': float(settings.TRADING_FEE_PCT),
                }
            )
        
        # Create notification
        if order_type == 'MARKET':
            action_text = 'sold' if action == 'sell' else 'placed'
            notification_type = 'BET_SOLD' if action == 'sell' else 'BET_PLACED'
            notification_title = 'Position Closed' if action == 'sell' else 'Bet Placed'
            message = f'Your prediction of {outcome} for KES {amount} has been {action_text} (Fee: KES {fee})'
        else:  # LIMIT order
            notification_type = 'LIMIT_ORDER_PLACED'
            notification_title = 'Limit Order Placed'
            order_action = 'sell' if action == 'sell' else 'buy'
            message = f'Limit {order_action} order placed: {quantity} shares at {limit_price}% for {outcome} (Fee: KES {fee})'
        
        create_notification(
            user=user,
            type_choice=notification_type,
            title=notification_title,
            message=message,
            color_class='green' if action == 'sell' else 'purple',
            related_market_id=market.id,
            related_bet_id=bet.id
        )
        
        # LMSR-based price update for all markets
        # Execute the trade through LMSR services and update market state
        if market.market_type == 'BINARY':
            # Check if market is open
            open_status, reason = is_market_open(market)
            if not open_status:
                logger.warning(f"Market {market.id} is not open for trading: {reason}")
                # Still update volume
                current_volume = parse_volume_value(market.volume)
                market.volume = format_volume_value(current_volume + int(amount))
                market.save()
                # Return early - trade was recorded as limit order
                return JsonResponse({
                    'status': 'market_closed',
                    'message': reason,
                    'bet_id': bet.id if order_type == 'LIMIT' else None
                })
            
            try:
                shares = float(calculated_quantity)
                
                # Execute trade based on action
                if action == 'buy':
                    if outcome.upper() == 'YES':
                        result = buy_yes_shares(market, shares)
                    else:
                        result = buy_no_shares(market, shares)
                else:  # sell
                    if outcome.upper() == 'YES':
                        result = sell_yes_shares(market, shares)
                    else:
                        result = sell_no_shares(market, shares)
                
                # Process trading fee and distribute to LPs
                if result:
                    from markets.services import process_trading_fee
                    cost_or_payout = result.get('cost_kes') or result.get('payout_kes', 0)
                    process_trading_fee(market, cost_or_payout, bet)
                
                # Update balance for SELL orders with actual LMSR payout
                if action == 'sell' and result:
                    sell_payout_kes = result.get('payout_kes', Decimal('0'))
                    user.balance += Decimal(str(sell_payout_kes))
                    user.save()
                    logger.info(
                        f"SELL balance updated for user {user.id}: "
                        f"received {sell_payout_kes} KES from selling {shares} shares"
                    )
                
                # Update market probability from new LMSR prices
                prices = get_market_prices(market)
                market.yes_probability = int(prices['yes_price_pct'])
                
                logger.info(
                    f"LMSR trade executed: market={market.id}, "
                    f"outcome={outcome}, action={action}, "
                    f"shares={shares}, new_price={market.yes_probability}%"
                )
                
            except ValueError as e:
                logger.error(f"Invalid LMSR trade for market {market.id}: {str(e)}")
                # Trade still recorded, but market price doesn't move
            except Exception as e:
                logger.error(f"LMSR calculation error for market {market.id}: {str(e)}")
        
        elif market.market_type == 'OPTION_LIST' and market.options:
            # LMSR for option markets (TODO: implement per-option LMSR)
            # For now, simple probability adjustment
            for opt in market.options:
                if opt.get('id') == option_id:
                    if outcome == 'Yes':
                        opt['yes_probability'] = min(99, opt.get('yes_probability', 50) + 1)
                    else:
                        opt['no_probability'] = min(99, opt.get('no_probability', 50) + 1)
                        opt['yes_probability'] = 100 - opt['no_probability']
                    break
            market.options = market.options  # Trigger update

        current_volume = parse_volume_value(market.volume)
        market.volume = format_volume_value(current_volume + int(amount))
        market.save()
        
        # Record price history after market is updated
        from markets.models import PriceHistory
        if market.market_type == 'BINARY':
            PriceHistory.objects.create(
                market=market,
                yes_probability=market.yes_probability,
                no_probability=100 - market.yes_probability
            )
        elif market.market_type == 'OPTION_LIST' and market.options:
            for opt in market.options:
                PriceHistory.objects.create(
                    market=market,
                    option_id=opt.get('id'),
                    yes_probability=opt.get('yes_probability', 50),
                    no_probability=opt.get('no_probability', 50)
                )
        
        action_verb = 'sold' if action == 'sell' else 'placed'
        logger.info(f"Bet {action_verb} by {user.phone_number}: {outcome} {amount} on market {market_id}")

        response_msg = 'Position closed successfully' if action == 'sell' else 'Bet placed successfully'
        
        # Prepare market state response
        market_response = {
            'q_yes': float(market.q_yes),
            'q_no': float(market.q_no),
            'yes_probability': market.yes_probability,
        }
        
        # Include execution price if available from LMSR trade
        if result and isinstance(result, dict):
            market_response['execution_price'] = result.get('execution_price', market.yes_probability)
            market_response['new_yes_price'] = result.get('new_yes_price', market.yes_probability)
        
        return JsonResponse({
            'message': response_msg, 
            'bet_id': bet.id,
            'new_balance': str(user.balance),
            'market': market_response
        })
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Market.DoesNotExist:
        return JsonResponse({'error': 'Market not found'}, status=404)
    except ValidationError as e:
        return JsonResponse({'error': e.message}, status=400)
    except Exception as e:
        logger.error(f"Place bet error: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def get_user_available_shares(request, market_id):
    """Get available shares user owns for a specific market/outcome to auto-populate sell form."""
    user = get_authenticated_user(request)
    if not user:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    try:
        market = Market.objects.get(id=market_id)
    except Market.DoesNotExist:
        return JsonResponse({'error': 'Market not found'}, status=404)
    
    outcome = request.GET.get('outcome')
    if not outcome or outcome not in ['Yes', 'No']:
        return JsonResponse({'error': 'Invalid outcome'}, status=400)
    
    option_id = request.GET.get('option_id')
    
    # Calculate available shares
    filter_kwargs = {
        'user': user,
        'market': market,
        'outcome': outcome,
        'action': 'BUY',
    }
    if option_id:
        filter_kwargs['option_id'] = option_id
    
    buy_quantity = Bet.objects.filter(**filter_kwargs).aggregate(
        total=models.Sum('quantity')
    )['total'] or 0
    
    sell_filter_kwargs = {
        'user': user,
        'market': market,
        'outcome': outcome,
        'action': 'SELL',
        'order_status': 'FILLED',
    }
    if option_id:
        sell_filter_kwargs['option_id'] = option_id
    
    sell_quantity = Bet.objects.filter(**sell_filter_kwargs).aggregate(
        total=models.Sum('quantity')
    )['total'] or 0
    
    available_quantity = buy_quantity - sell_quantity
    
    return JsonResponse({
        'available_quantity': max(0, available_quantity),
        'buy_quantity': buy_quantity,
        'sell_quantity': sell_quantity,
    })


@csrf_exempt
@require_http_methods(["GET", "POST"])
def market_chat(request, market_id):
    """Chat messages for a single market."""
    try:
        try:
            market = Market.objects.get(id=market_id)
        except Market.DoesNotExist:
            return JsonResponse({'error': 'Market not found'}, status=404)

        if request.method == 'GET':
            messages = ChatMessage.objects.filter(market=market).select_related('user', 'parent__user').order_by('created_at')
            return JsonResponse({
                'messages': [
                    {
                        'id': msg.id,
                        'user_id': msg.user.id,
                        'user_name': f"@{msg.user.username}" if msg.user.username else msg.user.full_name,
                        'phone_number': msg.user.phone_number,
                        'message': msg.message,
                        'created_at': msg.created_at.isoformat(),
                        'parent_id': msg.parent_id,
                        'parent_user_name': f"@{msg.parent.user.username}" if msg.parent and msg.parent.user.username else (msg.parent.user.full_name if msg.parent else None),
                    }
                    for msg in messages
                ]
            })

        # POST
        user = get_authenticated_user(request)
        if not user:
            return JsonResponse({'error': 'Authentication required'}, status=401)

        data = json.loads(request.body)
        message = data.get('message', '').strip()
        reply_to = data.get('reply_to')

        if not message:
            return JsonResponse({'error': 'Message cannot be empty'}, status=400)

        parent_message = None
        if reply_to:
            try:
                parent_message = ChatMessage.objects.get(id=reply_to, market=market)
            except ChatMessage.DoesNotExist:
                return JsonResponse({'error': 'Reply target not found'}, status=400)

        chat_message = ChatMessage.objects.create(
            user=user,
            market=market,
            parent=parent_message,
            message=message,
        )

        return JsonResponse({
            'message': {
                'id': chat_message.id,
                'user_id': user.id,
                'user_name': f"@{user.username}" if user.username else user.full_name,
                'phone_number': user.phone_number,
                'message': chat_message.message,
                'created_at': chat_message.created_at.isoformat(),
                'parent_id': chat_message.parent_id,
                'parent_user_name': f"@{chat_message.parent.user.username}" if chat_message.parent and chat_message.parent.user.username else (chat_message.parent.user.full_name if chat_message.parent else None),
            }
        }, status=201)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Market chat error: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["GET"])
def market_details(request, market_id):
    """Return market public details for comments, top holders, positions, activity, and related markets."""
    try:
        try:
            market = Market.objects.get(id=market_id)
        except Market.DoesNotExist:
            return JsonResponse({'error': 'Market not found'}, status=404)

        comments = ChatMessage.objects.filter(market=market).select_related('user', 'parent__user').order_by('created_at')
        bets = Bet.objects.filter(market=market).select_related('user').order_by('-timestamp')

        # Build comment list
        comment_data = [
            {
                'id': msg.id,
                'user_id': msg.user.id,
                'user_name': f"@{msg.user.username}" if msg.user.username else msg.user.full_name,
                'phone_number': msg.user.phone_number,
                'message': msg.message,
                'created_at': msg.created_at.isoformat(),
                'parent_id': msg.parent_id,
                'parent_user_name': f"@{msg.parent.user.username}" if msg.parent and msg.parent.user.username else (msg.parent.user.full_name if msg.parent else None),
            }
            for msg in comments
        ]

        # Public positions list
        positions = [
            {
                'id': bet.id,
                'user_id': bet.user.id,
                'user_name': f"@{bet.user.username}" if bet.user.username else bet.user.full_name,
                'outcome': bet.outcome,
                'order_type': bet.order_type,
                'limit_price': str(bet.limit_price) if bet.limit_price is not None else None,
                'quantity': bet.quantity,
                'amount': str(bet.amount),
                'entry_probability': bet.entry_probability,
                'result': bet.result,
                'timestamp': bet.timestamp.isoformat(),
            }
            for bet in bets
        ]

        # Group top holders by user and outcome
        holder_map = {}
        for bet in bets:
            key = (bet.user.id, bet.outcome)
            if key not in holder_map:
                holder_map[key] = {
                    'user_id': bet.user.id,
                    'user_name': f"@{bet.user.username}" if bet.user.username else bet.user.full_name,
                    'outcome': bet.outcome,
                    'shares': 0,
                    'average_price': Decimal('0.00'),
                    'amount_total': Decimal('0.00'),
                }
            holder_map[key]['shares'] += bet.quantity or 1
            holder_map[key]['amount_total'] += bet.amount

        for holder in holder_map.values():
            shares = Decimal(holder['shares']) if holder['shares'] else Decimal('1')
            holder['average_price'] = str((holder['amount_total'] / shares).quantize(Decimal('0.01')))
            holder['shares'] = int(holder['shares'])
            holder.pop('amount_total', None)

        yes_holders = sorted(
            [holder for holder in holder_map.values() if holder['outcome'] == 'Yes'],
            key=lambda h: h['shares'],
            reverse=True
        )
        no_holders = sorted(
            [holder for holder in holder_map.values() if holder['outcome'] == 'No'],
            key=lambda h: h['shares'],
            reverse=True
        )

        # Build activity stream
        activity = [
            {
                'id': bet.id,
                'user_id': bet.user.id,
                'user_name': f"@{bet.user.username}" if bet.user.username else bet.user.full_name,
                'action': f"bought {bet.quantity or 1} {bet.outcome}",
                'amount': str(bet.amount),
                'limit_price': str(bet.limit_price) if bet.limit_price is not None else None,
                'order_type': bet.order_type,
                'timestamp': bet.timestamp.isoformat(),
            }
            for bet in bets
        ]

        # Get related markets (markets with same question) to show as options
        related_markets = Market.objects.filter(question=market.question).exclude(id=market_id).order_by('id')
        related_options = []
        
        for related_market in related_markets:
            related_options.append({
                'id': related_market.id,
                'question': related_market.question,
                'description': related_market.description,
                'image_url': related_market.image_url,
                'yes_probability': related_market.yes_probability,
                'no_probability': 100 - related_market.yes_probability,
                'volume': related_market.volume,
                'status': related_market.status,
                'end_date': related_market.end_date,
            })

        return JsonResponse({
            'market_id': market.id,
            'comments': comment_data,
            'positions': positions,
            'top_holders': {
                'yes': yes_holders,
                'no': no_holders,
            },
            'activity': activity,
            'related_markets': related_options,  # Markets with same question shown as options
        })
    except Exception as e:
        logger.error(f"Market details error: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(['GET'])
def get_price_history(request, market_id):
    """Get historical price data for a market based on time period"""
    try:
        from datetime import datetime, timedelta
        from django.utils import timezone
        
        market = Market.objects.get(id=market_id)
        period = request.GET.get('period', 'ALL')
        option_id = request.GET.get('option_id')
        
        # Calculate time range based on period
        now = timezone.now()
        time_ranges = {
            '1H': now - timedelta(hours=1),
            '6H': now - timedelta(hours=6),
            '1D': now - timedelta(days=1),
            '1W': now - timedelta(weeks=1),
            '1M': now - timedelta(days=30),
            'ALL': now - timedelta(days=365),
        }
        
        start_time = time_ranges.get(period, now - timedelta(days=365))
        
        # Fetch price history
        from markets.models import PriceHistory
        query = PriceHistory.objects.filter(
            market=market,
            timestamp__gte=start_time
        )
        if option_id:
            query = query.filter(option_id=option_id)
        else:
            query = query.filter(option_id__isnull=True)  # For BINARY markets
        
        history = query.order_by('timestamp')
        
        # If no history, return empty array
        if not history.exists():
            return JsonResponse({
                'market_id': market.id,
                'period': period,
                'option_id': option_id,
                'data': []
            })
        
        # Format data for frontend
        data = [
            {
                'timestamp': h.timestamp.isoformat(),
                'yes_probability': h.yes_probability,
                'no_probability': h.no_probability,
            }
            for h in history
        ]
        
        return JsonResponse({
            'market_id': market.id,
            'period': period,
            'option_id': option_id,
            'data': data
        })
    except Market.DoesNotExist:
        return JsonResponse({'error': 'Market not found'}, status=404)
    except Exception as e:
        logger.error(f"Price history error: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["POST"])
@csrf_exempt
def preview_trade_price(request):
    """
    Preview the execution price and slippage for a trade without placing it.
    
    POST /api/markets/preview-price/
    {
        "market_id": 1,
        "outcome": "Yes",
        "amount": 5000,
        "action": "buy"  // or "sell"
    }
    """
    try:
        data = json.loads(request.body)
        market_id = data.get('market_id')
        outcome = data.get('outcome')
        amount = data.get('amount')
        action = data.get('action', 'buy').lower()
        
        if not all([market_id, outcome, amount]):
            return JsonResponse({'error': 'Missing: market_id, outcome, amount'}, status=400)
        
        try:
            outcome = validate_bet_outcome(outcome)
            # Validate amount based on action type
            # For BUY: amount is KES (max 2 decimal places)
            # For SELL: amount is shares (can have higher precision for fractional shares)
            if action == 'buy':
                amount = validate_amount(amount, min_amount=Decimal('1'), max_amount=Decimal('100000'))
            else:
                # SELL: amount is shares (can be fractional)
                amount = Decimal(str(amount))
                if amount <= 0:
                    raise ValidationError('Amount must be positive')
                if amount > Decimal('1000000'):
                    raise ValidationError('Amount cannot exceed 1,000,000 shares')
        except ValidationError as e:
            return JsonResponse({'error': e.message}, status=400)
        
        market = Market.objects.get(id=market_id)
        
        # Check if market is open
        open_status, reason = is_market_open(market)
        if not open_status:
            return JsonResponse({
                'error': f'Market is not open: {reason}',
                'market_id': market.id,
                'is_lmsr': False,
            }, status=400)
        
        # Get current market prices
        current_prices = get_market_prices(market)
        
        # For previewing, we don't actually execute the trade,
        # just return the current market prices and a simple estimate
        try:
            if action == 'buy':
                # Rough estimate: shares = amount / currentPrice (in KES)
                current_price_kes = current_prices['yes_price_kes'] if outcome.upper() == 'YES' else current_prices['no_price_kes']
                estimated_shares = float(amount) / current_price_kes if current_price_kes > 0 else 0
                
                return JsonResponse({
                    'market_id': market.id,
                    'outcome': outcome,
                    'amount': str(amount),
                    'action': 'buy',
                    'current_yes_price': current_prices['yes_price_kes'],
                    'current_no_price': current_prices['no_price_kes'],
                    'estimated_execution_price': current_price_kes,
                    'estimated_shares': round(estimated_shares, 2),
                    'is_lmsr': True,
                    'message': f"You'll receive approximately {estimated_shares:.2f} shares at KES {current_price_kes} per share"
                })
            else:  # sell
                # For sell, amount represents shares
                shares_to_sell = float(amount)
                current_price_kes = current_prices['yes_price_kes'] if outcome.upper() == 'YES' else current_prices['no_price_kes']
                estimated_proceeds = shares_to_sell * current_price_kes
                
                return JsonResponse({
                    'market_id': market.id,
                    'outcome': outcome,
                    'shares': str(shares_to_sell),
                    'action': 'sell',
                    'current_yes_price': current_prices['yes_price_kes'],
                    'current_no_price': current_prices['no_price_kes'],
                    'estimated_execution_price': current_price_kes,
                    'estimated_proceeds_kes': round(estimated_proceeds, 2),
                    'is_lmsr': True,
                    'message': f"You'll receive approximately {estimated_proceeds:.2f} KES for {shares_to_sell} shares"
                })
        except Exception as e:
            logger.error(f"LMSR preview error: {str(e)}")
            return JsonResponse({'error': f'Price calculation error: {str(e)}'}, status=500)
    
    except Market.DoesNotExist:
        return JsonResponse({'error': 'Market not found'}, status=404)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Price preview error: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["POST"])
@csrf_exempt
def bootstrap_market_liquidity(request):
    """
    Bootstrap a market with initial LMSR liquidity (Admin only).
    Sets the market's q_yes and q_no based on desired initial probability.
    
    POST /api/markets/bootstrap/
    {
        "market_id": 1,
        "initial_probability": 50,  # YES probability (0-100)
        "b": 100.0  # Liquidity parameter (optional, defaults to 100)
    }
    """
    try:
        data = json.loads(request.body)
        market_id = data.get('market_id')
        initial_probability = data.get('initial_probability', 50)
        b = float(data.get('b', 100.0))
        
        # Check if user is authenticated and is staff/admin
        user = get_authenticated_user(request)
        if not user or not (user.is_staff or user.is_superuser):
            return JsonResponse({'error': 'Unauthorized - admin access required'}, status=403)
        
        if not market_id:
            return JsonResponse({'error': 'market_id required'}, status=400)
        
        try:
            initial_prob = float(initial_probability)
            if not (0 < initial_prob < 100):
                return JsonResponse({'error': 'Initial probability must be between 0 and 100'}, status=400)
        except (ValueError, TypeError):
            return JsonResponse({'error': 'Invalid initial probability'}, status=400)
        
        market = Market.objects.get(id=market_id)
        
        # Check if already bootstrapped
        if market.q_yes != 0 or market.q_no != 0:
            return JsonResponse({'error': 'Market already bootstrapped'}, status=400)
        
        # Calculate q_yes and q_no for desired probability
        from .bootstrap import bootstrap_market
        q_yes, q_no = bootstrap_market(initial_prob / 100.0, b)
        
        market.q_yes = q_yes
        market.q_no = q_no
        market.b = b
        market.yes_probability = int(initial_prob)
        market.save()
        
        logger.info(
            f"Bootstrapped market {market_id} with "
            f"q_yes={q_yes}, q_no={q_no}, b={b}, initial_prob={initial_prob}%"
        )
        
        return JsonResponse({
            'status': 'success',
            'market_id': market.id,
            'q_yes': round(q_yes, 6),
            'q_no': round(q_no, 6),
            'b': b,
            'initial_probability': initial_prob,
            'message': f'Market bootstrapped with {initial_prob}% YES probability'
        })
    except Market.DoesNotExist:
        return JsonResponse({'error': 'Market not found'}, status=404)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Bootstrap error: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["GET"])
def get_bitcoin_market(request):
    """
    Get Bitcoin Up/Down market with current price data
    
    Endpoint: GET /api/markets/bitcoin/
    
    Returns:
        - Market data with current Bitcoin price
        - YES/NO probabilities
        - Multipliers for trading
        - Live price data
    """
    try:
        market_data = BitcoinPriceService.get_bitcoin_market_with_price()
        return JsonResponse(market_data, status=200)
    except Exception as e:
        logger.error(f"Error fetching Bitcoin market: {str(e)}")
        return JsonResponse(
            {'error': 'Failed to fetch Bitcoin market data'}, 
            status=500
        )


@require_http_methods(["GET"])
def get_bitcoin_price(request):
    """
    Get current Bitcoin price only (lightweight endpoint)
    
    Endpoint: GET /api/markets/bitcoin/price/
    
    Returns:
        - current_price: Bitcoin price in USD
        - timestamp: When the price was fetched
        - source: Which API provided the data
    """
    try:
        price = BitcoinPriceService.get_current_bitcoin_price()
        
        if price is None:
            return JsonResponse(
                {'error': 'Unable to fetch Bitcoin price'},
                status=503
            )
        
        return JsonResponse({
            'current_price': price,
            'formatted_price': f"${price:,.2f}",
            'timestamp': timezone.now().isoformat(),
            'source': 'coingecko'
        }, status=200)
    except Exception as e:
        logger.error(f"Error fetching Bitcoin price: {str(e)}")
        return JsonResponse(
            {'error': 'Failed to fetch Bitcoin price'},
            status=500
        )


