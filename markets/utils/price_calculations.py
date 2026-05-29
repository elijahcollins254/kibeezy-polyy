"""
Price Calculation Utilities for LMSR (Logarithmic Market Scoring Rule)

This module contains all formulas for calculating market prices, costs, and payouts.
These formulas implement the LMSR AMM mechanism.

LMSR is a market maker mechanism that:
1. Maintains a cost function: C(q_yes, q_no) = b * log(exp(q_yes/b) + exp(q_no/b))
2. Derives prices from the cost function derivatives
3. Ensures YES + NO probabilities always sum to 1
4. Has bounded loss for the market maker
"""

import math

# Constants
PAYOUT_PER_SHARE = 100  # KES per share


def cost(q_yes: float, q_no: float, b: float) -> float:
    """
    Calculate the total cost (or wealth) of the market.
    
    Formula: C(q_yes, q_no) = b * ln(exp(q_yes/b) + exp(q_no/b))
    
    Args:
        q_yes: YES quantity issued
        q_no: NO quantity issued
        b: Liquidity parameter (higher = more liquidity, less price impact)
    
    Returns:
        Total cost in KES (when multiplied by share value 100)
    """
    try:
        exp_yes = math.exp(q_yes / b)
        exp_no = math.exp(q_no / b)
        return b * math.log(exp_yes + exp_no)
    except (ValueError, OverflowError):
        # Handle extreme values gracefully
        return b * max(q_yes, q_no) / b + b


def price_yes(q_yes: float, q_no: float, b: float) -> float:
    """
    Calculate the current YES price (probability).
    
    Formula: P_yes = exp(q_yes/b) / (exp(q_yes/b) + exp(q_no/b))
    
    Args:
        q_yes: YES quantity issued
        q_no: NO quantity issued
        b: Liquidity parameter
    
    Returns:
        Price as probability between 0 and 1
    """
    try:
        exp_yes = math.exp(q_yes / b)
        exp_no = math.exp(q_no / b)
        return exp_yes / (exp_yes + exp_no)
    except (ValueError, OverflowError):
        # Handle extreme deviations
        if q_yes > q_no:
            return 0.999
        elif q_no > q_yes:
            return 0.001
        return 0.5


def price_no(q_yes: float, q_no: float, b: float) -> float:
    """
    Calculate the current NO price (probability).
    
    Formula: P_no = 1 - P_yes
    
    Args:
        q_yes: YES quantity issued
        q_no: NO quantity issued
        b: Liquidity parameter
    
    Returns:
        Price as probability between 0 and 1
    """
    return 1.0 - price_yes(q_yes, q_no, b)


def calculate_cost_to_buy_shares(
    q_yes_before: float,
    q_no_before: float,
    shares: float,
    outcome: str,
    b: float
) -> float:
    """
    Calculate the KES cost to buy a given quantity of shares.
    
    Cost = (C_after - C_before) * 100
    where C is the cost function and 100 is the share value in KES.
    
    Args:
        q_yes_before: YES quantity before trade
        q_no_before: NO quantity before trade
        shares: Number of shares to buy
        outcome: "YES" or "NO"
        b: Liquidity parameter
    
    Returns:
        Cost in KES
    """
    if outcome.upper() == "YES":
        q_yes_after = q_yes_before + shares
        q_no_after = q_no_before
    else:
        q_yes_after = q_yes_before
        q_no_after = q_no_before + shares
    
    cost_before = cost(q_yes_before, q_no_before, b)
    cost_after = cost(q_yes_after, q_no_after, b)
    
    # Cost difference multiplied by share value (100 KES per share)
    cost_kes = (cost_after - cost_before) * PAYOUT_PER_SHARE
    return round(cost_kes, 2)


def calculate_payout_from_selling(
    q_yes_before: float,
    q_no_before: float,
    shares: float,
    outcome: str,
    b: float
) -> float:
    """
    Calculate the KES payout from selling shares back to the market.
    
    Payout = (C_before - C_after) * 100
    where C is the cost function.
    
    Args:
        q_yes_before: YES quantity before trade
        q_no_before: NO quantity before trade
        shares: Number of shares to sell
        outcome: "YES" or "NO"
        b: Liquidity parameter
    
    Returns:
        Payout in KES
    """
    if outcome.upper() == "YES":
        q_yes_after = q_yes_before - shares
        q_no_after = q_no_before
    else:
        q_yes_after = q_yes_before
        q_no_after = q_no_before - shares
    
    cost_before = cost(q_yes_before, q_no_before, b)
    cost_after = cost(q_yes_after, q_no_after, b)
    
    # Payout is the difference
    payout_kes = (cost_before - cost_after) * PAYOUT_PER_SHARE
    return round(payout_kes, 2)


# ============================================================================
# SETTLEMENT FORMULAS
# ============================================================================


def calculate_settlement_payout(shares: float) -> float:
    """
    Calculate settlement payout for a winning bet.
    
    Formula: Payout = shares × 100 KES
    
    This is the fixed payout amount given to winners when a market resolves.
    Each share is worth exactly 100 KES at settlement.
    
    Args:
        shares: Number of shares held
    
    Returns:
        Total payout in KES
    """
    payout = shares * PAYOUT_PER_SHARE
    return round(payout, 2)


def calculate_settlement_profit(payout: float, original_bet_amount: float) -> float:
    """
    Calculate profit/loss for a winning bet at settlement.
    
    Formula: Profit = Payout - Original Bet Amount
    
    Args:
        payout: Settlement payout in KES
        original_bet_amount: Amount initially bet in KES
    
    Returns:
        Profit in KES (can be negative if user bought at high price)
    """
    profit = payout - original_bet_amount
    return round(profit, 2)


# ============================================================================
# BOOTSTRAP FORMULAS
# ============================================================================


def calculate_q_for_probability(probability: float, b: float) -> float:
    """
    Given a desired YES probability and liquidity parameter b,
    calculate the q_yes value needed (assuming q_no = 0 for symmetry).
    
    Formula: q_yes = b * ln(probability / (1 - probability))
    
    This works because when q_no = 0:
        P_yes = exp(q_yes/b) / (exp(q_yes/b) + 1)
        
    Solving for q_yes:
        probability = exp(q_yes/b) / (exp(q_yes/b) + 1)
        probability * (exp(q_yes/b) + 1) = exp(q_yes/b)
        probability * exp(q_yes/b) + probability = exp(q_yes/b)
        probability = exp(q_yes/b) * (1 - probability)
        exp(q_yes/b) = probability / (1 - probability)
        q_yes/b = ln(probability / (1 - probability))
        q_yes = b * ln(probability / (1 - probability))
    
    Args:
        probability: Desired YES probability (0 < p < 1)
        b: Liquidity parameter (default 100)
    
    Returns:
        q_yes value needed
    """
    if probability <= 0 or probability >= 1:
        raise ValueError(f"Probability must be between 0 and 1, got {probability}")
    
    q_yes = b * math.log(probability / (1 - probability))
    return q_yes


def verify_bootstrap(q_yes: float, q_no: float, b: float, target_probability: float) -> bool:
    """
    Verify that bootstrapped q values produce the expected probability.
    
    Used to validate that market initialization was successful.
    
    Args:
        q_yes: Bootstrapped q_yes
        q_no: Bootstrapped q_no
        b: Liquidity parameter
        target_probability: Expected YES probability (0 < p < 1)
    
    Returns:
        True if actual probability is within 0.1% of target
    """
    actual_prob = price_yes(q_yes, q_no, b)
    tolerance = 0.001  # 0.1%
    return abs(actual_prob - target_probability) < tolerance
