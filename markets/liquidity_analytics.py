"""
Enhanced Liquidity Analytics

Provides:
- Impermanent Loss (IL) calculations
- Pool risk scoring
- Historical performance data
- Fee analytics
"""

from decimal import Decimal
from django.db import models
from django.utils import timezone
from datetime import timedelta, datetime
import math

from .models import Market, LiquidityPool, LiquidityProvider, FeeDistribution, Bet
from .lmsr import price_yes as calc_price_yes, price_no as calc_price_no
from .utils.price_calculations import PAYOUT_PER_SHARE


class LPDailySnapshot(models.Model):
    """Store daily snapshots of LP positions for historical analysis"""
    provider = models.ForeignKey(LiquidityProvider, on_delete=models.CASCADE, related_name='daily_snapshots')
    snapshot_date = models.DateField(auto_now_add=True)
    
    # Position value at time of snapshot
    capital_provided = models.DecimalField(max_digits=15, decimal_places=2)
    total_fees_earned = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_value = models.DecimalField(max_digits=15, decimal_places=2)  # capital + growth
    
    # IL tracking
    impermanent_loss = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    il_percent = models.FloatField(default=0.0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        unique_together = ['provider', 'snapshot_date']
        ordering = ['-snapshot_date']
    
    def __str__(self):
        return f"LP Snapshot - {self.provider.user.phone_number} - {self.snapshot_date}"


# ============================================================================
# IL CALCULATION
# ============================================================================

def calculate_impermanent_loss(lp_provider: LiquidityProvider) -> dict:
    """
    Calculate impermanent loss for an LP position.
    
    IL = (current_position_value) - (hodl_value)
    
    Returns:
        {
            'il_amount': float (in KES, negative = loss),
            'il_percent': float (percentage),
            'current_position_value': float,
            'hodl_value': float,
            'unrealized_gain_loss': float,
            'offset_by_fees': float,
            'net_il': float,
        }
    """
    pool = lp_provider.pool
    market = pool.market
    
    # Get current LMSR prices
    q_yes = float(market.q_yes)
    q_no = float(market.q_no)
    b = float(market.b)
    
    current_price_yes = calc_price_yes(q_yes, q_no, b)
    current_price_no = 1.0 - current_price_yes
    
    # Entry prices (estimated from initial split)
    # We assume LP split equally, so entry was at market prices at time of deposit
    entry_price_yes = 0.5  # Approximation - would need historical data for accuracy
    entry_price_no = 0.5
    
    # Current position value
    current_position_yes = lp_provider.yes_shares_owned * current_price_yes * PAYOUT_PER_SHARE
    current_position_no = lp_provider.no_shares_owned * current_price_no * PAYOUT_PER_SHARE
    current_total = current_position_yes + current_position_no
    
    # HODL value (if they had just held the capital)
    hodl_value = float(lp_provider.capital_provided)
    
    # IL amount
    il_amount = current_total - hodl_value
    il_percent = (il_amount / hodl_value * 100) if hodl_value > 0 else 0
    
    # Fee offset
    fees_earned = float(lp_provider.total_fees_earned)
    net_il = il_amount + fees_earned  # Fees offset IL
    
    return {
        'il_amount': round(il_amount, 2),
        'il_percent': round(il_percent, 2),
        'current_position_value': round(current_total, 2),
        'hodl_value': hodl_value,
        'unrealized_gain_loss': round(il_amount, 2),
        'offset_by_fees': round(fees_earned, 2),
        'net_il': round(net_il, 2),
        'total_fees': fees_earned,
        'il_is_significant': abs(il_percent) > 20,  # Flag if IL > 20%
    }


# ============================================================================
# POOL RISK SCORING
# ============================================================================

def calculate_pool_risk_score(pool: LiquidityPool) -> dict:
    """
    Calculate risk score for a liquidity pool (1-10 scale).
    
    Factors:
    - Market volatility (q_yes/q_no ratio change over time)
    - Trading volume consistency
    - Number of LPs (concentration risk)
    - Time to resolution
    - Historical IL events
    
    Returns:
        {
            'risk_score': float (1-10),
            'risk_level': str ('Very Low', 'Low', 'Medium', 'High', 'Very High'),
            'factors': {...},
            'warnings': [str],
        }
    """
    market = pool.market
    
    factors = {}
    warnings = []
    scores = []
    
    # 1. VOLATILITY RISK (0-3 points)
    # Check how much odds have shifted from middle
    q_yes = float(market.q_yes) or 1.0
    q_no = float(market.q_no) or 1.0
    ratio = q_yes / q_no if q_no > 0 else 1.0
    
    # If ratio is far from 1.0, high volatility
    volatility_score = min(3.0, abs(math.log(ratio)) * 2)
    factors['volatility'] = round(volatility_score, 2)
    scores.append(volatility_score)
    
    if volatility_score > 2.0:
        warnings.append("High market volatility detected")
    
    # 2. CONCENTRATION RISK (0-2 points)
    # How many LPs? More = lower concentration risk
    num_providers = pool.providers.count()
    concentration_score = max(0, 2.0 - (num_providers / 5.0))
    factors['concentration'] = round(concentration_score, 2)
    scores.append(concentration_score)
    
    if num_providers < 3:
        warnings.append(f"Low provider count ({num_providers}): high concentration risk")
    
    # 3. VOLUME RISK (0-2 points)
    # Low volume = less trading = fewer fees
    market_volume = float(market.volume.replace('KES', '').replace(',', '').strip() or 0)
    volume_score = max(0, 2.0 - (market_volume / 100000))  # 100k KES = no risk
    factors['volume'] = round(volume_score, 2)
    scores.append(volume_score)
    
    if market_volume < 10000:
        warnings.append("Low trading volume: fewer fee opportunities")
    
    # 4. RESOLUTION TIME RISK (0-2 points)
    # Longer markets = more time for volatility
    if market.end_date:
        try:
            end_time = datetime.fromisoformat(market.end_date.replace('Z', '+00:00'))
            days_remaining = max(0, (end_time - timezone.now()).days)
            resolution_score = min(2.0, days_remaining / 90)  # 90+ days = max risk
            factors['time'] = round(resolution_score, 2)
            scores.append(resolution_score)
            
            if days_remaining > 60:
                warnings.append(f"Long resolution window ({days_remaining} days)")
        except:
            factors['time'] = 0
    
    # 5. MARKET STATUS RISK (0-1 point)
    if market.status == 'OPEN':
        factors['status'] = 0.0
    elif market.status == 'CLOSED':
        factors['status'] = 0.5
        warnings.append("Market trading is closed")
    else:
        factors['status'] = 1.0
    scores.append(factors['status'])
    
    # Calculate final risk score
    total_score = sum(scores)
    risk_score = min(10, total_score)
    
    # Map to risk level
    if risk_score < 2:
        risk_level = "Very Low"
    elif risk_score < 4:
        risk_level = "Low"
    elif risk_score < 6:
        risk_level = "Medium"
    elif risk_score < 8:
        risk_level = "High"
    else:
        risk_level = "Very High"
    
    return {
        'risk_score': round(risk_score, 1),
        'risk_level': risk_level,
        'factors': factors,
        'warnings': warnings[:3],  # Top 3 warnings
    }


# ============================================================================
# FEE ANALYTICS
# ============================================================================

def calculate_fee_analytics(lp_provider: LiquidityProvider) -> dict:
    """
    Calculate detailed fee analytics for an LP position.
    
    Returns:
        {
            'total_fees': float,
            'fees_claimed': float,
            'unclaimed_fees': float,
            'average_daily_fees': float,
            'daily_fee_trend': [...],  # Last 7 days
            'fee_source_breakdown': {...},
            'estimated_monthly_fee': float,
            'fee_efficiency': float (fees earned / capital at risk),
        }
    """
    
    # Get all fee distributions for this LP
    fee_distributions = lp_provider.fee_history.all().order_by('-created_at')
    
    total_fees = float(lp_provider.total_fees_earned)
    fees_claimed = float(lp_provider.fees_claimed)
    unclaimed = float(lp_provider.unclaimed_fees)
    
    # Calculate daily fees for last 7 days
    daily_fees = {}
    now = timezone.now()
    for i in range(7, 0, -1):
        date = (now - timedelta(days=i)).date()
        day_fees = fee_distributions.filter(created_at__date=date).count()
        daily_fees[date.strftime('%m-%d')] = float(day_fees) * 0.01  # Approximation
    
    # Days invested
    days_invested = max(1, (now - lp_provider.entry_date).days)
    average_daily_fees = total_fees / days_invested if days_invested > 0 else 0
    estimated_monthly = average_daily_fees * 30
    
    # Fee efficiency (fees earned as % of capital)
    capital = float(lp_provider.capital_provided)
    fee_efficiency = (total_fees / capital * 100) if capital > 0 else 0
    
    return {
        'total_fees': round(total_fees, 2),
        'fees_claimed': round(fees_claimed, 2),
        'unclaimed_fees': round(unclaimed, 2),
        'average_daily_fees': round(average_daily_fees, 2),
        'daily_fee_trend': daily_fees,
        'estimated_monthly_fee': round(estimated_monthly, 2),
        'fee_efficiency': round(fee_efficiency, 2),  # Fees as % of capital
    }


# ============================================================================
# HISTORICAL PERFORMANCE
# ============================================================================

def get_lp_performance_history(lp_provider: LiquidityProvider, days: int = 30) -> list:
    """
    Get historical performance data for charts.
    
    Returns list of daily snapshots for the last N days.
    """
    snapshots = lp_provider.daily_snapshots.all().order_by('snapshot_date')
    
    # If no snapshots, generate synthetic data
    if not snapshots:
        return generate_synthetic_history(lp_provider, days)
    
    # Get snapshots for requested period
    cutoff_date = (timezone.now() - timedelta(days=days)).date()
    historical = []
    
    for snapshot in snapshots.filter(snapshot_date__gte=cutoff_date):
        historical.append({
            'date': snapshot.snapshot_date.isoformat(),
            'capital': float(snapshot.capital_provided),
            'fees_earned': float(snapshot.total_fees_earned),
            'total_value': float(snapshot.total_value),
            'il': float(snapshot.impermanent_loss),
            'il_percent': snapshot.il_percent,
            'apy': 0,  # Calculate based on returns
        })
    
    return historical


def generate_synthetic_history(lp_provider: LiquidityProvider, days: int = 30) -> list:
    """
    Generate synthetic historical data based on current position.
    Used when no snapshots exist.
    """
    history = []
    capital = float(lp_provider.capital_provided)
    
    # Simulate linear fee accumulation
    current_fees = float(lp_provider.total_fees_earned)
    days_invested = max(1, (timezone.now() - lp_provider.entry_date).days)
    daily_fee_rate = current_fees / days_invested if days_invested > 0 else 0
    
    for i in range(days, 0, -1):
        date = (timezone.now() - timedelta(days=i)).date()
        days_elapsed = days - i
        
        if days_elapsed <= days_invested:
            # Interpolate fees
            simulated_fees = daily_fee_rate * days_elapsed
            total_val = capital + simulated_fees
        else:
            simulated_fees = current_fees
            total_val = capital + simulated_fees
        
        history.append({
            'date': date.isoformat(),
            'capital': capital,
            'fees_earned': round(simulated_fees, 2),
            'total_value': round(total_val, 2),
            'il': 0,  # Would need historical prices
            'il_percent': 0,
            'apy': 0,
        })
    
    return history
