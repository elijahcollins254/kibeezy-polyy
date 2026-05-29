"""
Analytics and financial dashboard endpoints for admin panel
"""

import json
import logging
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db.models import Sum, Count, Q, F
from datetime import datetime, timedelta
from decimal import Decimal
from .models import Market, Bet
from payments.models import Transaction
from users.models import CustomUser
from api.validators import normalize_phone_number

logger = logging.getLogger(__name__)

COMMISSION_RATE = 0.02  # 2% fee


def is_admin(user, request=None):
    """Check if user is admin"""
    if user and user.is_authenticated and user.is_staff:
        return True
    
    if request and request.headers.get('X-User-Phone-Number'):
        phone_number = request.headers.get('X-User-Phone-Number')
        try:
            phone_number = normalize_phone_number(phone_number)
            user_obj = CustomUser.objects.get(phone_number=phone_number)
            return user_obj.is_staff and user_obj.is_superuser
        except CustomUser.DoesNotExist:
            return False
    
    return False


@require_http_methods(["GET"])
def analytics_dashboard(request):
    """
    Get comprehensive analytics data for dashboard
    
    Returns:
    {
        "metrics": {
            "total_users": int,
            "active_users_30d": int,
            "total_markets": int,
            "open_markets": int,
            "resolved_markets": int,
        },
        "financial": {
            "total_volume_wagered": float,  # Total KES bet across all markets
            "commission_earned": float,      # 2% of total volume
            "total_payouts": float,          # Amount paid to winners
            "total_deposits": float,         # User deposits
            "total_withdrawals": float,      # User withdrawals
            "net_cash_flow": float,          # Deposits - Withdrawals
        },
        "by_category": {
            "Sports": {"volume": float, "markets": int, "commission": float},
            ...
        },
        "top_markets": [
            {
                "id": int,
                "question": str,
                "volume": float,
                "yes_probability": int,
                "status": str,
                "commission": float
            }
        ],
        "daily_volume": [  # Last 30 days
            {"date": "2026-04-16", "volume": float}
        ]
    }
    """
    if not is_admin(request.user, request):
        return JsonResponse({'error': 'Admin access required'}, status=403)
    
    try:
        # Key Metrics
        total_users = CustomUser.objects.filter(is_active=True).count()
        total_markets = Market.objects.count()
        open_markets = Market.objects.filter(status='OPEN').count()
        resolved_markets = Market.objects.filter(status='RESOLVED').count()
        
        # Active users in last 30 days
        thirty_days_ago = datetime.now() - timedelta(days=30)
        active_users_30d = CustomUser.objects.filter(
            last_login__gte=thirty_days_ago
        ).count()
        
        # Financial Metrics
        # Total volume = sum of all bet amounts
        total_bets = Bet.objects.aggregate(
            total_amount=Sum('amount')
        )
        total_volume = float(total_bets['total_amount'] or 0)
        
        # Commission = 2% of total volume
        commission_earned = total_volume * COMMISSION_RATE
        
        # Total payouts (resolved bets that won)
        payouts = Bet.objects.filter(
            result='WON'
        ).aggregate(
            total_payout=Sum('payout')
        )
        total_payouts = float(payouts['total_payout'] or 0)
        
        # Deposits and withdrawals from transactions
        deposits = Transaction.objects.filter(
            type='DEPOSIT',
            status='COMPLETED'
        ).aggregate(
            total=Sum('amount')
        )
        total_deposits = float(deposits['total'] or 0)
        
        withdrawals = Transaction.objects.filter(
            type='WITHDRAWAL',
            status='COMPLETED'
        ).aggregate(
            total=Sum('amount')
        )
        total_withdrawals = float(withdrawals['total'] or 0)
        
        net_cash_flow = total_deposits - total_withdrawals
        
        # Volume by category
        by_category = {}
        categories = Market.objects.values('category').distinct()
        for cat_obj in categories:
            category = cat_obj['category']
            cat_bets = Bet.objects.filter(
                market__category=category
            ).aggregate(
                volume=Sum('amount'),
                count=Count('market', distinct=True)
            )
            by_category[category] = {
                'volume': float(cat_bets['volume'] or 0),
                'markets': cat_bets['count'] or 0,
                'commission': float(cat_bets['volume'] or 0) * COMMISSION_RATE
            }
        
        # Top markets by volume
        top_markets_data = []
        markets = Market.objects.all()
        for market in markets[:20]:
            market_bets = Bet.objects.filter(market=market).aggregate(
                volume=Sum('amount')
            )
            volume = float(market_bets['volume'] or 0)
            if volume > 0:
                top_markets_data.append({
                    'id': market.id,
                    'question': market.question,
                    'volume': volume,
                    'yes_probability': market.yes_probability,
                    'status': market.status,
                    'commission': float(volume * COMMISSION_RATE),
                    'category': market.category,
                })
        
        # Sort by volume
        top_markets_data.sort(key=lambda x: x['volume'], reverse=True)
        top_markets = top_markets_data[:10]
        
        # Daily volume for last 30 days
        daily_volume = []
        for i in range(29, -1, -1):
            date = (datetime.now() - timedelta(days=i)).date()
            day_bets = Bet.objects.filter(
                timestamp__date=date
            ).aggregate(
                volume=Sum('amount')
            )
            daily_volume.append({
                'date': str(date),
                'volume': float(day_bets['volume'] or 0)
            })
        
        return JsonResponse({
            'metrics': {
                'total_users': total_users,
                'active_users_30d': active_users_30d,
                'total_markets': total_markets,
                'open_markets': open_markets,
                'resolved_markets': resolved_markets,
            },
            'financial': {
                'total_volume_wagered': round(total_volume, 2),
                'commission_earned': round(commission_earned, 2),
                'total_payouts': round(total_payouts, 2),
                'total_deposits': round(total_deposits, 2),
                'total_withdrawals': round(total_withdrawals, 2),
                'net_cash_flow': round(net_cash_flow, 2),
            },
            'by_category': by_category,
            'top_markets': top_markets,
            'daily_volume': daily_volume,
        })
    
    except Exception as e:
        logger.error(f"Analytics error: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["GET"])
def risk_dashboard(request):
    """
    Get risk and exposure metrics
    
    Returns:
    {
        "market_exposure": [
            {
                "market_id": int,
                "question": str,
                "yes_probability": int,
                "status": str,
                "volume": float,
                "potential_loss_if_yes": float,
                "potential_loss_if_no": float,
                "max_exposure": float
            }
        ],
        "portfolio_health": {
            "total_potential_exposure": float,
            "liquidity_reserve": float,
            "health_score": 0-100,
            "risk_level": "LOW" | "MEDIUM" | "HIGH",
            "recommendation": str,
        }
    }
    """
    if not is_admin(request.user, request):
        return JsonResponse({'error': 'Admin access required'}, status=403)
    
    try:
        market_exposure = []
        total_exposure = 0
        
        for market in Market.objects.filter(status='OPEN'):
            # Get market volume
            market_bets = Bet.objects.filter(
                market=market,
                result='PENDING'
            ).aggregate(
                yes_volume=Sum('amount', filter=Q(outcome='Yes')),
                no_volume=Sum('amount', filter=Q(outcome='No'))
            )
            
            yes_volume = float(market_bets['yes_volume'] or 0)
            no_volume = float(market_bets['no_volume'] or 0)
            total_volume = yes_volume + no_volume
            
            if total_volume == 0:
                continue
            
            # If market resolves YES, platform must pay out to YES holders
            # Risk = (YES volume / total) * max_payout_per_share * held_shares
            # Simplified: max loss if everyone holds winning shares
            
            yes_prob = market.yes_probability / 100.0
            no_prob = 1 - yes_prob
            
            # Potential loss if market resolves YES
            loss_if_yes = yes_volume * 0.5  # Rough estimate
            # Potential loss if market resolves NO
            loss_if_no = no_volume * 0.5
            
            max_exposure = max(loss_if_yes, loss_if_no)
            total_exposure += max_exposure
            
            market_exposure.append({
                'market_id': market.id,
                'question': market.question[:50],
                'yes_probability': market.yes_probability,
                'status': market.status,
                'volume': total_volume,
                'yes_volume': yes_volume,
                'no_volume': no_volume,
                'potential_loss_if_yes': round(loss_if_yes, 2),
                'potential_loss_if_no': round(loss_if_no, 2),
                'max_exposure': round(max_exposure, 2),
            })
        
        # Get total user balance (liquidity reserve)
        user_balances = CustomUser.objects.aggregate(
            total_balance=Sum('balance')
        )
        liquidity_reserve = float(user_balances['total_balance'] or 0)
        
        # Calculate health score (0-100)
        if total_exposure > 0:
            coverage_ratio = liquidity_reserve / total_exposure
            # Coverage > 2x = 100 score, coverage < 0.5x = 0 score
            health_score = min(100, max(0, int((coverage_ratio / 2) * 100)))
        else:
            health_score = 100
        
        # Determine risk level
        if coverage_ratio > 1.5:
            risk_level = "LOW"
            recommendation = "Good position. You can handle most market resolutions."
        elif coverage_ratio > 0.8:
            risk_level = "MEDIUM"
            recommendation = "Moderate exposure. Monitor large markets closely."
        else:
            risk_level = "HIGH"
            recommendation = "High risk! Consider reducing market sizes or pausing new markets."
        
        # Sort by exposure
        market_exposure.sort(key=lambda x: x['max_exposure'], reverse=True)
        
        return JsonResponse({
            'market_exposure': market_exposure[:20],  # Top 20 risks
            'portfolio_health': {
                'total_potential_exposure': round(total_exposure, 2),
                'liquidity_reserve': round(liquidity_reserve, 2),
                'coverage_ratio': round(liquidity_reserve / total_exposure if total_exposure > 0 else 999, 2),
                'health_score': health_score,
                'risk_level': risk_level,
                'recommendation': recommendation,
            }
        })
    
    except Exception as e:
        logger.error(f"Risk dashboard error: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)
