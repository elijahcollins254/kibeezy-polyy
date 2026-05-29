"""
LMSR Trading Service Functions

Handles all market operations: buying/selling shares, calculating costs/payouts.
All trading operations are atomic and update the market's q_yes, q_no values.

Fee Distribution Integration:
After trades execute, fees are automatically distributed to liquidity providers.
"""

from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from .models import Market, Bet
from .lmsr import (
    cost,
    price_yes,
    price_no,
    calculate_cost_to_buy_shares,
    calculate_payout_from_selling,
    PAYOUT_PER_SHARE,
)

# Import LP configuration and service
try:
    from .lp_config import TRADING_FEE_PERCENT, APPLY_TRADING_FEES
    from .liquidity_service import distribute_trading_fee
    LIQUIDITY_SERVICE_AVAILABLE = True
except ImportError:
    LIQUIDITY_SERVICE_AVAILABLE = False
    TRADING_FEE_PERCENT = 0.5
    APPLY_TRADING_FEES = False


@transaction.atomic
def buy_yes_shares(market: Market, shares: float) -> dict:
    """
    Buy YES shares in an LMSR market.
    
    Updates market.q_yes and returns the cost in KES.
    
    Args:
        market: Market instance
        shares: Number of shares to buy
    
    Returns:
        {
            'cost_kes': float,  # KES cost
            'shares': float,    # Shares acquired
            'execution_price': float,  # Price paid (as % probability)
            'new_yes_price': float,    # New YES price after trade
        }
    """
    q_yes_before = float(market.q_yes)
    q_no_before = float(market.q_no)
    b = float(market.b)
    
    # Calculate cost
    cost_kes = calculate_cost_to_buy_shares(q_yes_before, q_no_before, shares, "YES", b)
    
    # Get prices before and after
    price_before = price_yes(q_yes_before, q_no_before, b)
    
    # Update market quantities
    market.q_yes = q_yes_before + shares
    market.save()
    
    # Get new price
    price_after = price_yes(float(market.q_yes), q_no_before, b)
    execution_price = (price_before + price_after) / 2
    
    return {
        "cost_kes": cost_kes,
        "shares": float(shares),
        "execution_price": round(execution_price * 100, 2),
        "new_yes_price": round(price_after * 100, 2),
    }


@transaction.atomic
def buy_no_shares(market: Market, shares: float) -> dict:
    """
    Buy NO shares in an LMSR market.
    
    Updates market.q_no and returns the cost in KES.
    
    Args:
        market: Market instance
        shares: Number of shares to buy
    
    Returns:
        {
            'cost_kes': float,
            'shares': float,
            'execution_price': float,
            'new_yes_price': float,
        }
    """
    q_yes_before = float(market.q_yes)
    q_no_before = float(market.q_no)
    b = float(market.b)
    
    # Calculate cost
    cost_kes = calculate_cost_to_buy_shares(q_yes_before, q_no_before, shares, "NO", b)
    
    # Get prices
    price_yes_before = price_yes(q_yes_before, q_no_before, b)
    
    # Update market quantities
    market.q_no = q_no_before + shares
    market.save()
    
    # Get new price
    price_yes_after = price_yes(q_yes_before, float(market.q_no), b)
    execution_price = (price_yes_before + price_yes_after) / 2
    
    return {
        "cost_kes": cost_kes,
        "shares": float(shares),
        "execution_price": round(execution_price * 100, 2),
        "new_yes_price": round(price_yes_after * 100, 2),
    }


@transaction.atomic
def sell_yes_shares(market: Market, shares: float) -> dict:
    """
    Sell YES shares back to the market.
    
    Updates market.q_yes and returns the payout in KES.
    
    Args:
        market: Market instance
        shares: Number of shares to sell
    
    Returns:
        {
            'payout_kes': float,
            'shares': float,
            'execution_price': float,
            'new_yes_price': float,
        }
    """
    q_yes_before = float(market.q_yes)
    q_no_before = float(market.q_no)
    b = float(market.b)
    
    if q_yes_before < shares:
        raise ValueError(
            f"Cannot sell {shares} YES shares when only {q_yes_before} exist"
        )
    
    # Calculate payout
    payout_kes = calculate_payout_from_selling(q_yes_before, q_no_before, shares, "YES", b)
    
    # Get prices
    price_yes_before = price_yes(q_yes_before, q_no_before, b)
    
    # Update market quantities
    market.q_yes = q_yes_before - shares
    market.save()
    
    # Get new price
    price_yes_after = price_yes(float(market.q_yes), q_no_before, b)
    execution_price = (price_yes_before + price_yes_after) / 2
    
    return {
        "payout_kes": payout_kes,
        "shares": float(shares),
        "execution_price": round(execution_price * 100, 2),
        "new_yes_price": round(price_yes_after * 100, 2),
    }


@transaction.atomic
def sell_no_shares(market: Market, shares: float) -> dict:
    """
    Sell NO shares back to the market.
    
    Updates market.q_no and returns the payout in KES.
    
    Args:
        market: Market instance
        shares: Number of shares to sell
    
    Returns:
        {
            'payout_kes': float,
            'shares': float,
            'execution_price': float,
            'new_yes_price': float,
        }
    """
    q_yes_before = float(market.q_yes)
    q_no_before = float(market.q_no)
    b = float(market.b)
    
    if q_no_before < shares:
        raise ValueError(
            f"Cannot sell {shares} NO shares when only {q_no_before} exist"
        )
    
    # Calculate payout
    payout_kes = calculate_payout_from_selling(q_yes_before, q_no_before, shares, "NO", b)
    
    # Get prices
    price_yes_before = price_yes(q_yes_before, q_no_before, b)
    
    # Update market quantities
    market.q_no = q_no_before - shares
    market.save()
    
    # Get new price
    price_yes_after = price_yes(q_yes_before, float(market.q_no), b)
    execution_price = (price_yes_before + price_yes_after) / 2
    
    return {
        "payout_kes": payout_kes,
        "shares": float(shares),
        "execution_price": round(execution_price * 100, 2),
        "new_yes_price": round(price_yes_after * 100, 2),
    }


def get_market_prices(market: Market) -> dict:
    """
    Get current market prices without executing any trade.
    
    Args:
        market: Market instance
    
    Returns:
        {
            'yes_price': float,  # YES probability (0-1)
            'no_price': float,   # NO probability (0-1)
            'yes_price_pct': float,  # YES as percentage
            'no_price_pct': float,   # NO as percentage
            'yes_price_kes': float,  # YES price in KES
            'no_price_kes': float,   # NO price in KES
        }
    """
    yes_prob = price_yes(float(market.q_yes), float(market.q_no), float(market.b))
    no_prob = price_no(float(market.q_yes), float(market.q_no), float(market.b))
    
    return {
        "yes_price": round(yes_prob, 4),
        "no_price": round(no_prob, 4),
        "yes_price_pct": round(yes_prob * 100, 2),
        "no_price_pct": round(no_prob * 100, 2),
        "yes_price_kes": round(yes_prob * PAYOUT_PER_SHARE, 2),
        "no_price_kes": round(no_prob * PAYOUT_PER_SHARE, 2),
    }


def is_market_open(market: Market) -> tuple:
    """
    Check if a market is currently open for trading.
    
    Args:
        market: Market instance
    
    Returns:
        (is_open: bool, reason: str)
    """
    if market.status != "OPEN":
        return False, f"Market is {market.status}"
    
    if market.trading_end_time and timezone.now() >= market.trading_end_time:
        return False, "Trading has ended"
    
    return True, "Market is open"


@transaction.atomic
def process_trading_fee(market: Market, amount_kes: float, bet: Bet = None) -> dict:
    """
    Apply trading fee and distribute to liquidity providers.
    
    Called after every trade to calculate and distribute fees.
    
    Args:
        market: Market instance
        amount_kes: Original trade amount in KES
        bet: The Bet record that generated this fee (optional)
    
    Returns:
        {
            'success': bool,
            'fee_charged_kes': float,
            'net_amount': float,
            'num_providers': int,
            'message': str,
        }
    """
    if not APPLY_TRADING_FEES or not LIQUIDITY_SERVICE_AVAILABLE:
        return {
            'success': False,
            'fee_charged_kes': 0,
            'net_amount': amount_kes,
            'num_providers': 0,
            'message': 'Fee distribution not enabled',
        }
    
    try:
        # Get or create the pool
        pool = market.liquidity_pool
    except:
        # Market doesn't have a liquidity pool yet
        return {
            'success': False,
            'fee_charged_kes': 0,
            'net_amount': amount_kes,
            'num_providers': 0,
            'message': 'Market has no liquidity pool',
        }
    
    # Calculate fee
    fee_charged = (amount_kes * TRADING_FEE_PERCENT) / 100
    net_amount = amount_kes - fee_charged
    
    # Distribute fee to LPs
    distribution_result = distribute_trading_fee(pool, fee_charged, bet)
    
    return {
        'success': distribution_result.get('success', False),
        'fee_charged_kes': fee_charged,
        'net_amount': net_amount,
        'num_providers': distribution_result.get('num_providers', 0),
        'message': distribution_result.get('message', 'Fee processed'),
    }
