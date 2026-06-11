"""
Analytics and Financial Metrics Views for Admin Dashboard.

Provides aggregated data for analytics and financial dashboards.
"""

import json
from decimal import Decimal
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from datetime import timedelta
from django.db.models import Sum, Count, Q, F, Case, When
from markets.models import Market, Bet
from payments.models import Transaction
from users.models import CustomUser


def get_authenticated_user(request):
    """Get authenticated user from session or header"""
    if request.user and request.user.is_authenticated:
        return request.user
    
    phone_number = request.headers.get('X-User-Phone-Number')
    if phone_number:
        try:
            from api.validators import normalize_phone_number
            phone_number = normalize_phone_number(phone_number)
            return CustomUser.objects.get(phone_number=phone_number)
        except CustomUser.DoesNotExist:
            return None
    
    return None


@require_http_methods(["GET"])
def analytics_dashboard(request):
    """
    Get comprehensive analytics dashboard data.
    Includes user metrics, market metrics, and activity trends.
    """
    # Check authentication and admin status
    user = get_authenticated_user(request)
    if not user or not (user.is_staff or user.is_superuser):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    try:
        # User metrics
        total_users = CustomUser.objects.filter(is_active=True).count()
        active_traders = Bet.objects.values('user').distinct().count()
        
        # Market metrics
        total_markets = Market.objects.count()
        open_markets = Market.objects.filter(status='OPEN').count()
        resolved_markets = Market.objects.filter(status='RESOLVED').count()
        
        # Betting activity
        total_bets = Bet.objects.count()
        
        # Volume and liquidity
        total_volume_kes = Bet.objects.aggregate(
            total=Sum(F('amount') * Case(When(action='BUY', then=1), default=0))
        )['total'] or Decimal('0')
        
        total_sell_volume = Bet.objects.aggregate(
            total=Sum(F('amount') * Case(When(action='SELL', then=1), default=0))
        )['total'] or Decimal('0')
        
        # Category breakdown
        category_volumes = {}
        for market in Market.objects.all():
            market_bets = Bet.objects.filter(
                market=market,
                action='BUY'
            ).aggregate(volume=Sum('amount'))['volume'] or Decimal('0')
            
            if market.category not in category_volumes:
                category_volumes[market.category] = 0
            category_volumes[market.category] += float(market_bets)
        
        # Growth trends (last 7 days)
        week_ago = timezone.now() - timedelta(days=7)
        new_users_week = CustomUser.objects.filter(
            date_joined__gte=week_ago
        ).count()
        
        new_bets_week = Bet.objects.filter(
            timestamp__gte=week_ago
        ).count()
        
        volume_week = Bet.objects.filter(
            timestamp__gte=week_ago,
            action='BUY'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        
        # Market health
        markets_by_status = Market.objects.values('status').annotate(count=Count('id'))
        
        # Top markets by volume
        top_markets = []
        for market in Market.objects.all()[:5]:
            buy_volume = Bet.objects.filter(
                market=market,
                action='BUY'
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
            
            bet_count = Bet.objects.filter(market=market).count()
            
            top_markets.append({
                'id': market.id,
                'question': market.question,
                'category': market.category,
                'volume': float(buy_volume),
                'bet_count': bet_count,
                'status': market.status,
                'yes_probability': market.yes_probability,
            })
        
        return JsonResponse({
            'users': {
                'total': total_users,
                'active_traders': active_traders,
                'new_this_week': new_users_week,
            },
            'markets': {
                'total': total_markets,
                'open': open_markets,
                'resolved': resolved_markets,
                'by_status': list(markets_by_status),
            },
            'activity': {
                'total_bets': total_bets,
                'new_bets_week': new_bets_week,
            },
            'volume': {
                'total_buy_volume_kes': float(total_volume_kes),
                'total_sell_volume_kes': float(total_sell_volume),
                'volume_this_week_kes': float(volume_week),
            },
            'categories': category_volumes,
            'top_markets': top_markets,
        })
    
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Analytics dashboard error: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["GET"])
def financials_dashboard(request):
    """
    Get comprehensive financial metrics for the company.
    Includes revenue, payouts, fees, and risk exposure.
    """
    # Check authentication and admin status
    user = get_authenticated_user(request)
    if not user or not (user.is_staff or user.is_superuser):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    try:
        TRADING_FEE_PERCENT = 2  # 2% fee
        
        # =================================================================
        # REVENUE CALCULATIONS
        # =================================================================
        
        # Total volume (what users spent on buys)
        total_buy_volume = Bet.objects.filter(
            action='BUY'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        
        # Commission from buy volume
        commission_from_buys = total_buy_volume * Decimal(TRADING_FEE_PERCENT) / Decimal('100')
        
        # Deposit/withdrawal fees (from Transaction model)
        deposit_volume = Transaction.objects.filter(
            type='DEPOSIT'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        
        withdrawal_volume = Transaction.objects.filter(
            type='WITHDRAWAL'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        
        total_revenue = commission_from_buys
        
        # =================================================================
        # PAYOUT CALCULATIONS
        # =================================================================
        
        # Resolved markets - calculate winners' payouts
        resolved_markets = Market.objects.filter(status='RESOLVED')
        total_payouts_kes = Decimal('0')
        
        for market in resolved_markets:
            winning_bets = Bet.objects.filter(
                market=market,
                outcome=market.resolved_outcome,
                action='BUY'
            )
            
            for bet in winning_bets:
                # Win: get back amount + profit (but lose to fees already taken)
                payout = bet.amount + (bet.quantity * Decimal(str(PAYOUT_PER_SHARE)))
                total_payouts_kes += payout
        
        # =================================================================
        # MARKET EXPOSURE & RISK
        # =================================================================
        
        # For each OPEN market, calculate potential loss if market resolves opposite to current odds
        total_potential_loss = Decimal('0')
        potential_loss_by_market = []
        
        for market in Market.objects.filter(status='OPEN'):
            # Simulate loss: if market resolves to NO (worst case for us)
            no_bets = Bet.objects.filter(market=market, outcome='No', action='BUY')
            no_potential_payout = no_bets.aggregate(
                total=Sum(F('quantity') * Decimal(str(PAYOUT_PER_SHARE)))
            )['total'] or Decimal('0')
            
            # Simulate loss: if market resolves to YES
            yes_bets = Bet.objects.filter(market=market, outcome='Yes', action='BUY')
            yes_potential_payout = yes_bets.aggregate(
                total=Sum(F('quantity') * Decimal(str(PAYOUT_PER_SHARE)))
            )['total'] or Decimal('0')
            
            # Worst case loss
            market_loss = max(no_potential_payout, yes_potential_payout)
            total_potential_loss += market_loss
            
            buy_volume = Bet.objects.filter(
                market=market,
                action='BUY'
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
            
            potential_loss_by_market.append({
                'market_id': market.id,
                'question': market.question,
                'volume': float(buy_volume),
                'potential_loss': float(market_loss),
                'yes_probability': market.yes_probability,
            })
        
        # =================================================================
        # NET POSITION
        # =================================================================
        
        # Estimate company liquidity reserve
        total_user_balance = CustomUser.objects.aggregate(
            total=Sum('balance')
        )['total'] or Decimal('0')
        
        # Company margin (revenue collected - payouts issued)
        net_position = total_revenue - total_payouts_kes
        
        # Health score: 0-100
        # 0 = badly exposed, 100 = well protected
        if total_potential_loss > 0:
            health_score = min(100, int((total_revenue / total_potential_loss) * 100)) if total_revenue > 0 else 0
        else:
            health_score = 100
        
        # =================================================================
        # COMPILE RESPONSE
        # =================================================================
        
        return JsonResponse({
            'revenue': {
                'total_commission_kes': float(commission_from_buys),
                'commission_percentage': TRADING_FEE_PERCENT,
                'deposit_volume_kes': float(deposit_volume),
                'withdrawal_volume_kes': float(withdrawal_volume),
            },
            'volume': {
                'total_buy_volume_kes': float(total_buy_volume),
                'resolved_payout_kes': float(total_payouts_kes),
            },
            'exposure': {
                'total_potential_loss_kes': float(total_potential_loss),
                'net_position_kes': float(net_position),
                'health_score': health_score,  # 0-100
                'market_exposure': [
                    {
                        'market_id': m['market_id'],
                        'question': m['question'],
                        'volume': m['volume'],
                        'potential_loss': m['potential_loss'],
                        'yes_probability': m['yes_probability'],
                    }
                    for m in potential_loss_by_market[:10]  # Top 10
                ],
            },
            'liquidity': {
                'total_user_balance_kes': float(total_user_balance),
                'estimated_reserve_kes': float(net_position),
                'safety_buffer': 'Good' if health_score > 70 else 'Moderate' if health_score > 40 else 'At Risk',
            },
            'summary': {
                'open_markets': Market.objects.filter(status='OPEN').count(),
                'resolved_markets': Market.objects.filter(status='RESOLVED').count(),
                'total_users': CustomUser.objects.filter(is_active=True).count(),
            }
        })
    
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Financial dashboard error: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)
