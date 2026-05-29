"""
Bootstrap initialization functions for LMSR markets.

When a market is created with an initial probability, we need to calculate
the q_yes and q_no values that produce that probability.
"""

from .lmsr import calculate_q_for_probability, verify_bootstrap, price_yes


def bootstrap_market(initial_probability: float, b: float = 100.0) -> tuple:
    """
    Bootstrap a market with an initial probability.
    
    Args:
        initial_probability: Desired YES probability at market start (0 < p < 1)
        b: Liquidity parameter
    
    Returns:
        (q_yes, q_no) tuple
    """
    q_yes = calculate_q_for_probability(initial_probability, b)
    q_no = 0.0  # By convention, we use q_no = 0 and set q_yes to the desired value
    
    return round(q_yes, 6), round(q_no, 6)
