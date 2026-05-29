"""
Liquidity Provider (LP) Service Layer

Handles all operations for the Simple Fee Distribution model:
- Depositing capital into liquidity pools
- Withdrawing liquidity
- Distributing trading fees to LPs
- Claiming accumulated fees

Phase 1 Implementation: All fees split equally among LPs
"""

from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from datetime import timedelta

from .models import (
    Market,
    LiquidityPool,
    LiquidityProvider,
    FeeDistribution,
    Bet,
)
from .lmsr import (
    price_yes as calc_price_yes,
    price_no as calc_price_no,
    cost as calc_cost,
)
from .utils.price_calculations import PAYOUT_PER_SHARE

# ============================================================================
# CONFIGURATION CONSTANTS
# ============================================================================

# Liquidity parameters
DEFAULT_LIQUIDITY_PARAMETER_B = 100.0

# Fee structure  
TRADING_FEE_PERCENT = 0.5  # 0.5% on every trade
WITHDRAWAL_FEE_PERCENT = 0.1  # 0.1% on withdrawal
EARLY_WITHDRAWAL_PENALTY = 0.02  # 2% if withdrawn within 7 days

EARLY_WITHDRAWAL_LOCKUP_DAYS = 7  # Lockup period for penalty-free withdrawal


# ============================================================================
# LIQUIDITY POOL INITIALIZATION
# ============================================================================

def initialize_liquidity_pool(market: Market) -> LiquidityPool:
    """
    Initialize a new liquidity pool for a market.
    Called automatically when market is created.
    
    Args:
        market: Market instance
    
    Returns:
        LiquidityPool instance
    """
    pool, created = LiquidityPool.objects.get_or_create(
        market=market,
        defaults={
            'fee_percent': TRADING_FEE_PERCENT,
            'withdrawal_fee_percent': WITHDRAWAL_FEE_PERCENT,
            'early_withdrawal_penalty': EARLY_WITHDRAWAL_PENALTY,
        }
    )
    return pool


# ============================================================================
# DEPOSITS & WITHDRAWALS
# ============================================================================

@transaction.atomic
def deposit_liquidity(
    market: Market,
    user,
    amount_kes: float,
) -> dict:
    """
    User deposits capital into the liquidity pool.
    
    Strategy: Deposit capital split 50/50 into YES/NO at current market price.
    This is "market-neutral" - LP is not betting on outcome, just earning fees.
    
    Args:
        market: Market instance
        user: User depositing liquidity
        amount_kes: Amount in KES to deposit
    
    Returns:
        {
            'success': bool,
            'lp_provider': LiquidityProvider,
            'yes_shares': float,
            'no_shares': float,
            'capital_provided': float,
            'message': str,
        }
    """
    if amount_kes <= 0:
        return {
            'success': False,
            'message': 'Deposit amount must be positive',
        }
    
    # Check user balance
    if user.balance < amount_kes:
        return {
            'success': False,
            'message': f'Insufficient balance. You have {user.balance:.2f} KES but need {amount_kes:.2f} KES',
        }
    
    # Get or create pool
    pool = initialize_liquidity_pool(market)
    
    # Get current market price
    q_yes = float(market.q_yes)
    q_no = float(market.q_no)
    b = float(market.b)
    
    p_yes = calc_price_yes(q_yes, q_no, b)
    p_no = calc_price_no(q_yes, q_no, b)
    
    # Split capital 50/50
    half_capital = amount_kes / 2
    
    # Calculate shares to buy at current prices
    # Cost = shares * probability * 100 (PAYOUT_PER_SHARE)
    yes_shares = half_capital / (p_yes * PAYOUT_PER_SHARE)
    no_shares = half_capital / (p_no * PAYOUT_PER_SHARE)
    
    # Deduct balance from user
    user.balance -= Decimal(str(amount_kes))
    user.save()
    
    # Get or create LP provider record
    lp_provider, created = LiquidityProvider.objects.get_or_create(
        user=user,
        pool=pool,
        defaults={
            'capital_provided': Decimal(str(amount_kes)),
            'yes_shares_owned': 0.0,
            'no_shares_owned': 0.0,
        }
    )
    
    # If LP already has position, add to it
    if not created:
        lp_provider.capital_provided += Decimal(str(amount_kes))
    
    # Update LP's share ownership
    lp_provider.yes_shares_owned += yes_shares
    lp_provider.no_shares_owned += no_shares
    lp_provider.save()
    
    # Update pool's total shares
    pool.total_yes_shares += yes_shares
    pool.total_no_shares += no_shares
    pool.save()
    
    return {
        'success': True,
        'lp_provider': lp_provider,
        'yes_shares': yes_shares,
        'no_shares': no_shares,
        'capital_provided': float(lp_provider.capital_provided),
        'lp_share_percent': lp_provider.lp_share_percent,
        'message': f'Successfully deposited {amount_kes} KES. Received {yes_shares:.4f} YES + {no_shares:.4f} NO shares.',
    }


@transaction.atomic
def withdraw_liquidity(lp_provider: LiquidityProvider) -> dict:
    """
    Withdraw all liquidity from pool with associated fees.
    
    Charges:
    - Withdrawal fee: 0.1% of withdrawal amount
    - Early withdrawal penalty: 2% if withdrawn within 7 days
    
    Args:
        lp_provider: LiquidityProvider instance to withdraw
    
    Returns:
        {
            'success': bool,
            'withdrawal_amount_kes': float,
            'fees_earned': float,
            'withdrawal_fee': float,
            'early_penalty': float,
            'net_amount': float,
            'message': str,
        }
    """
    pool = lp_provider.pool
    market = pool.market
    
    q_yes = float(market.q_yes)
    q_no = float(market.q_no)
    b = float(market.b)
    
    p_yes = calc_price_yes(q_yes, q_no, b)
    p_no = calc_price_no(q_yes, q_no, b)
    
    # Calculate current value of shares
    yes_value = lp_provider.yes_shares_owned * p_yes * PAYOUT_PER_SHARE
    no_value = lp_provider.no_shares_owned * p_no * PAYOUT_PER_SHARE
    total_shares_value = yes_value + no_value
    
    # Apply withdrawal fees
    withdrawal_fee = (total_shares_value * pool.withdrawal_fee_percent) / 100
    
    # Check for early withdrawal penalty
    days_invested = (timezone.now() - lp_provider.entry_date).days
    early_penalty = 0
    if days_invested < EARLY_WITHDRAWAL_LOCKUP_DAYS:
        early_penalty = (total_shares_value * pool.early_withdrawal_penalty) / 100
    
    # Net amount after fees
    net_withdrawal = total_shares_value - withdrawal_fee - early_penalty
    
    # Add any unclaimed fees
    fees_available = lp_provider.total_available_claimable
    total_payout = net_withdrawal + float(fees_available)
    
    # Update pool - remove shares
    pool.total_yes_shares -= lp_provider.yes_shares_owned
    pool.total_no_shares -= lp_provider.no_shares_owned
    pool.save()
    
    # Refund user balance (net withdrawal + fees earned)
    user = lp_provider.user
    user.balance += Decimal(str(total_payout))
    user.save()
    
    # Mark LP provider as withdrawn (delete record)
    lp_provider.delete()
    
    return {
        'success': True,
        'withdrawal_amount_kes': total_shares_value,
        'fees_earned': float(lp_provider.total_fees_earned),
        'withdrawal_fee': withdrawal_fee,
        'early_penalty': early_penalty,
        'net_amount': total_payout,
        'days_invested': days_invested,
        'message': f'Withdrawal complete. Received {total_payout:.2f} KES (shares: {net_withdrawal:.2f}, fees: {fees_available:.2f}, penalties: {withdrawal_fee + early_penalty:.2f})',
    }


# ============================================================================
# FEE DISTRIBUTION (Called when trades execute)
# ============================================================================

@transaction.atomic
def distribute_trading_fee(pool: LiquidityPool, fee_amount_kes: float, source_bet: Bet = None) -> dict:
    """
    Distribute a trading fee to all liquidity providers equally.
    
    Called after every trade by the trading service.
    
    Args:
        pool: LiquidityPool instance
        fee_amount_kes: Amount of fee to distribute
        source_bet: The Bet that generated this fee (optional, for audit trail)
    
    Returns:
        {
            'success': bool,
            'num_providers': int,
            'per_provider_fee': float,
            'message': str,
        }
    """
    providers = pool.providers.all()
    
    if not providers.exists():
        # No LPs in pool yet, fee is not distributed
        return {
            'success': False,
            'num_providers': 0,
            'message': 'No liquidity providers in pool',
        }
    
    num_providers = providers.count()
    per_provider_fee = fee_amount_kes / num_providers
    
    # Distribute fee to each LP equally
    for provider in providers:
        provider.total_fees_earned += Decimal(str(per_provider_fee))
        provider.unclaimed_fees += Decimal(str(per_provider_fee))
        provider.last_fee_update = timezone.now()
        provider.save()
        
        # Create audit trail
        FeeDistribution.objects.create(
            pool=pool,
            provider=provider,
            fee_amount=Decimal(str(per_provider_fee)),
            source_bet=source_bet,
            is_claimed=False,
        )
    
    # Update pool totals
    pool.total_fees_collected += Decimal(str(fee_amount_kes))
    pool.total_unclaimed_fees += Decimal(str(fee_amount_kes))
    pool.save()
    
    return {
        'success': True,
        'num_providers': num_providers,
        'per_provider_fee': per_provider_fee,
        'total_distributed': fee_amount_kes,
        'message': f'Fee {fee_amount_kes:.2f} KES distributed to {num_providers} providers',
    }


# ============================================================================
# FEE CLAIMING
# ============================================================================

@transaction.atomic
def claim_fees(lp_provider: LiquidityProvider) -> dict:
    """
    LP claims accumulated fees.
    
    Updates their fees_claimed and clears unclaimed_fees.
    In production, this would trigger a payment to user's wallet/account.
    
    Args:
        lp_provider: LiquidityProvider instance
    
    Returns:
        {
            'success': bool,
            'amount_claimed': float,
            'remaining_balance': float,
            'message': str,
        }
    """
    if lp_provider.unclaimed_fees <= 0:
        return {
            'success': False,
            'amount_claimed': 0,
            'remaining_balance': 0,
            'message': 'No fees to claim',
        }
    
    amount_to_claim = float(lp_provider.unclaimed_fees)
    
    # Update the provider
    lp_provider.fees_claimed += lp_provider.unclaimed_fees
    lp_provider.unclaimed_fees = Decimal('0')
    lp_provider.save()
    
    # Add claimed fees to user's balance
    user = lp_provider.user
    user.balance += Decimal(str(amount_to_claim))
    user.save()
    
    # Mark distributions as claimed
    FeeDistribution.objects.filter(
        provider=lp_provider,
        is_claimed=False,
    ).update(
        is_claimed=True,
        claimed_at=timezone.now(),
    )
    
    # In a real system, this would trigger payment processing (M-Pesa withdrawal, etc.)
    # For now, just return the data
    
    return {
        'success': True,
        'amount_claimed': amount_to_claim,
        'remaining_balance': float(lp_provider.total_available_claimable),
        'message': f'Successfully claimed {amount_to_claim:.2f} KES in fees',
    }


# ============================================================================
# POOL STATISTICS & INSIGHTS
# ============================================================================

def get_pool_stats(pool: LiquidityPool) -> dict:
    """
    Get current statistics for a liquidity pool.
    
    Returns:
        {
            'market_id': int,
            'market_question': str,
            'num_providers': int,
            'total_unclaimed_fees': float,
            'total_fees_collected': float,
            'total_liquidity_yes_shares': float,
            'total_liquidity_no_shares': float,
            'fee_percent': float,
            'providers': [...]
        }
    """
    providers = pool.providers.all()
    
    provider_data = []
    for provider in providers:
        provider_data.append({
            'user_id': provider.user.id,
            'user_phone': provider.user.phone_number if hasattr(provider.user, 'phone_number') else 'N/A',
            'lp_share_percent': provider.lp_share_percent,
            'yes_shares': provider.yes_shares_owned,
            'no_shares': provider.no_shares_owned,
            'total_fees_earned': float(provider.total_fees_earned),
            'unclaimed_fees': float(provider.unclaimed_fees),
            'entry_date': provider.entry_date.isoformat(),
        })
    
    return {
        'market_id': pool.market.id,
        'market_question': pool.market.question,
        'num_providers': providers.count(),
        'total_unclaimed_fees': float(pool.total_unclaimed_fees),
        'total_fees_collected': float(pool.total_fees_collected),
        'total_liquidity_yes_shares': pool.total_yes_shares,
        'total_liquidity_no_shares': pool.total_no_shares,
        'fee_percent': pool.fee_percent,
        'withdrawal_fee_percent': pool.withdrawal_fee_percent,
        'early_withdrawal_penalty': pool.early_withdrawal_penalty,
        'providers': provider_data,
    }


def get_lp_performance(lp_provider: LiquidityProvider) -> dict:
    """
    Get detailed performance metrics for a single LP.
    
    Returns:
        {
            'user': str,
            'market': str,
            'capital_provided': float,
            'days_invested': int,
            'total_fees_earned': float,
            'unclaimed_fees': float,
            'fees_claimed': float,
            'lp_share_percent': float,
            'estimated_apy': float,
            'yes_shares': float,
            'no_shares': float,
        }
    """
    days_invested = max(1, (timezone.now() - lp_provider.entry_date).days)
    
    # Calculate simple APY
    fees_earned = float(lp_provider.total_fees_earned)
    annualized_fees = (fees_earned / days_invested) * 365
    capital = float(lp_provider.capital_provided)
    estimated_apy = (annualized_fees / capital * 100) if capital > 0 else 0
    
    return {
        'user': lp_provider.user.phone_number if hasattr(lp_provider.user, 'phone_number') else str(lp_provider.user),
        'market': lp_provider.pool.market.question[:60],
        'capital_provided': capital,
        'days_invested': days_invested,
        'total_fees_earned': fees_earned,
        'unclaimed_fees': float(lp_provider.unclaimed_fees),
        'fees_claimed': float(lp_provider.fees_claimed),
        'lp_share_percent': lp_provider.lp_share_percent,
        'estimated_apy': estimated_apy,
        'yes_shares': lp_provider.yes_shares_owned,
        'no_shares': lp_provider.no_shares_owned,
    }


# ============================================================================
# IMPERMANENT LOSS CALCULATION
# ============================================================================

def calculate_impermanent_loss(lp_provider: LiquidityProvider) -> dict:
    """
    Calculate the impermanent loss for an LP position.
    
    IL occurs when market odds shift, causing the position value to diverge from
    the initial capital. This is offset by fees earned.
    
    Returns:
        {
            'il_amount': float (KES),
            'il_percent': float,
            'current_position_value': float,
            'hold_value': float,
            'fees_earned': float,
            'net_il_offset_by_fees': float,
            'fees_offset_percent': float,
            'entry_price_yes': float,
            'entry_price_no': float,
            'current_price_yes': float,
            'current_price_no': float,
        }
    """
    market = lp_provider.pool.market
    capital = float(lp_provider.capital_provided)
    fees_earned = float(lp_provider.total_fees_earned)
    
    # Current market prices
    q_yes = float(market.q_yes)
    q_no = float(market.q_no)
    b = float(market.b)
    
    current_price_yes = calc_price_yes(q_yes, q_no, b)
    current_price_no = calc_price_no(q_yes, q_no, b)
    
    # Estimate entry prices (50/50 split assumption)
    # This is approximate - ideal would store entry prices at deposit time
    entry_price_yes = 0.5
    entry_price_no = 0.5
    
    # Current position value based on share holdings
    yes_value = lp_provider.yes_shares_owned * current_price_yes * PAYOUT_PER_SHARE
    no_value = lp_provider.no_shares_owned * current_price_no * PAYOUT_PER_SHARE
    current_position_value = yes_value + no_value
    
    # "Hold value" = if we just held the capital
    hold_value = capital
    
    # Impermanent loss
    il_amount = hold_value - current_position_value
    il_percent = (il_amount / hold_value * 100) if hold_value > 0 else 0
    
    # How much are fees offsetting IL?
    fees_offset_percent = (fees_earned / il_amount * 100) if il_amount > 0 else 0
    
    return {
        'il_amount': float(il_amount),
        'il_percent': float(il_percent),
        'current_position_value': float(current_position_value),
        'hold_value': float(hold_value),
        'fees_earned': float(fees_earned),
        'net_il_offset_by_fees': float(max(0, il_amount - fees_earned)),
        'fees_offset_percent': float(min(100, fees_offset_percent)),
        'entry_price_yes': entry_price_yes,
        'entry_price_no': entry_price_no,
        'current_price_yes': current_price_yes,
        'current_price_no': current_price_no,
    }


# ============================================================================
# POOL RISK SCORING
# ============================================================================

def calculate_pool_risk_score(pool: LiquidityPool) -> dict:
    """
    Calculate risk score (1-10) for a liquidity pool.
    
    Factors considered:
    - Market volatility (price movements)
    - Trading volume consistency
    - Number of LPs (concentration risk)
    - Time to market resolution
    
    Returns:
        {
            'risk_score': int (1-10),
            'risk_label': str,
            'volatility_score': int,
            'concentration_score': int,
            'volume_score': int,
            'time_to_resolution_score': int,
            'factors': dict,
        }
    """
    market = pool.market
    providers = pool.providers.all()
    
    # Factor 1: Number of LPs (concentration)
    # More LPs = less concentrated risk
    num_providers = providers.count()
    concentration_score = min(10, max(1, 11 - (num_providers // 2)))  # 1-10 scale
    
    # Factor 2: Volatility (approximate from price range)
    # Using market question length and type as proxy (ideally track price history)
    q_yes = float(market.q_yes)
    q_no = float(market.q_no)
    total_q = q_yes + q_no
    if total_q > 0:
        price_ratio = max(q_yes, q_no) / total_q
        # More extreme odds = more volatile
        volatility_score = min(10, max(1, int((price_ratio - 0.5) * 20 + 5)))
    else:
        volatility_score = 5
    
    # Factor 3: Volume (trading activity)
    # Get recent bet count as proxy for volume
    from .models import Bet
    recent_bets = Bet.objects.filter(market=market, created_at__gte=timezone.now() - timedelta(days=7)).count()
    volume_score = min(10, max(1, recent_bets // 5 if recent_bets > 0 else 1))
    
    # Factor 4: Time to resolution
    # Market expiration in days
    now = timezone.now()
    resolution_diff = market.resolution_date - now
    days_remaining = max(0, resolution_diff.total_seconds() / (24 * 3600))
    
    if days_remaining < 1:
        time_score = 10  # Highest risk - resolving soon
    elif days_remaining < 7:
        time_score = 8
    elif days_remaining < 30:
        time_score = 5
    else:
        time_score = 2  # Lowest risk - lots of time
    
    # Calculate overall risk score (weighted average)
    risk_score = int(
        (volatility_score * 0.35 +  # Volatility weight 35%
         concentration_score * 0.25 +  # Concentration weight 25%
         volume_score * 0.20 +  # Volume weight 20%
         time_score * 0.20) / 10  # Time weight 20%
    )
    risk_score = max(1, min(10, risk_score))
    
    # Risk labels
    if risk_score <= 3:
        risk_label = "Low Risk"
    elif risk_score <= 6:
        risk_label = "Medium Risk"
    else:
        risk_label = "High Risk"
    
    return {
        'risk_score': risk_score,
        'risk_label': risk_label,
        'volatility_score': volatility_score,
        'concentration_score': concentration_score,
        'volume_score': volume_score,
        'time_to_resolution_score': time_score,
        'factors': {
            'num_providers': num_providers,
            'days_remaining': days_remaining,
            'recent_bets': recent_bets,
        }
    }


# ============================================================================
# FEE ANALYTICS
# ============================================================================

def get_fee_analytics(lp_provider: LiquidityProvider) -> dict:
    """
    Get detailed fee breakdown and analytics for an LP position.
    
    Returns:
        {
            'total_fees_earned': float,
            'fees_claimed': float,
            'unclaimed_fees': float,
            'avg_fee_per_day': float,
            'fee_trend': list[{'date': str, 'fees': float}],
            'biggest_fee_day': {'date': str, 'amount': float},
            'lowest_fee_day': {'date': str, 'amount': float},
        }
    """
    fees_earned = float(lp_provider.total_fees_earned)
    fees_claimed = float(lp_provider.fees_claimed)
    unclaimed_fees = float(lp_provider.unclaimed_fees)
    
    # Days invested
    days_invested = max(1, (timezone.now() - lp_provider.entry_date).days)
    avg_fee_per_day = fees_earned / days_invested if days_invested > 0 else 0
    
    # Get fee history grouped by day
    fee_distributions = (
        FeeDistribution.objects
        .filter(provider=lp_provider)
        .order_by('created_at')
    )
    
    fee_trend = []
    fee_by_day = {}
    
    for dist in fee_distributions:
        date_key = dist.created_at.date().isoformat()
        if date_key not in fee_by_day:
            fee_by_day[date_key] = 0
        fee_by_day[date_key] += float(dist.fee_amount)
    
    # Sort and create trend
    for date_str in sorted(fee_by_day.keys()):
        fee_trend.append({
            'date': date_str,
            'fees': round(fee_by_day[date_str], 2)
        })
    
    # Find biggest and lowest fee days
    biggest_fee_day = max(fee_by_day.items(), key=lambda x: x[1]) if fee_by_day else (None, 0)
    lowest_fee_day = min(fee_by_day.items(), key=lambda x: x[1]) if fee_by_day else (None, 0)
    
    return {
        'total_fees_earned': fees_earned,
        'fees_claimed': fees_claimed,
        'unclaimed_fees': unclaimed_fees,
        'avg_fee_per_day': round(avg_fee_per_day, 2),
        'fee_trend': fee_trend,
        'biggest_fee_day': {
            'date': biggest_fee_day[0] or 'N/A',
            'amount': round(biggest_fee_day[1], 2)
        } if biggest_fee_day[0] else {'date': 'N/A', 'amount': 0},
        'lowest_fee_day': {
            'date': lowest_fee_day[0] or 'N/A',
            'amount': round(lowest_fee_day[1], 2)
        } if lowest_fee_day[0] else {'date': 'N/A', 'amount': 0},
        'days_invested': days_invested,
    }
