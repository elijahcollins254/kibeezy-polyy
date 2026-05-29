"""
Liquidity Provider Configuration Constants

Central configuration for all liquidity provision system parameters.
"""

from .utils.price_calculations import PAYOUT_PER_SHARE

# ============================================================================
# LMSR PARAMETERS
# ============================================================================

# Default liquidity parameter B for LMSR cost function
# Higher B = more liquidity, less slippage, flatter price curve
# Lower B = less liquidity, more slippage, steeper price curve
DEFAULT_LIQUIDITY_PARAMETER_B = 100.0


# ============================================================================
# FEE STRUCTURE
# ============================================================================

# Trading fee percentage - applied to every buy/sell order
# This fee is collected and distributed to liquidity providers
TRADING_FEE_PERCENT = 0.5  # 0.5%

# Withdrawal fee percentage - charged when LP withdraws capital
# Applied to the total withdrawal amount
WITHDRAWAL_FEE_PERCENT = 0.1  # 0.1%

# Early withdrawal penalty - charged if LP withdraws within lockup period
# Applied to the withdrawal amount if withdrawn too early
EARLY_WITHDRAWAL_PENALTY = 0.02  # 2%

# Lockup period in days - penalty-free withdrawal only after this duration
EARLY_WITHDRAWAL_LOCKUP_DAYS = 7


# ============================================================================
# LP POOL CONFIGURATION
# ============================================================================

# Minimum deposit amount to become a liquidity provider
MINIMUM_LP_DEPOSIT = 100.0  # KES

# Maximum number of liquidity providers per market
# Set to 0 for unlimited
MAX_LPS_PER_MARKET = 0

# Fee distribution model
# Options: 'EQUAL' (equal split), 'PRO_RATA' (proportional to share)
FEE_DISTRIBUTION_MODEL = 'EQUAL'

# Whether to automatically initialize pools when markets are created
AUTO_INITIALIZE_POOLS = True


# ============================================================================
# TRADING INTEGRATION
# ============================================================================

# Whether to apply trading fees (disable for testing)
APPLY_TRADING_FEES = True

# Round fees to nearest currency unit (in KES cents)
FEE_ROUNDING_UNITS = 0.01  # 1 cent

# Minimum fee to distribute (fees smaller than this accumulate)
MINIMUM_FEE_TO_DISTRIBUTE = 0.50  # 50 cents


# ============================================================================
# APY CALCULATION
# ============================================================================

# Number of days in a year (for APY calculations)
DAYS_PER_YEAR = 365

# Minimum days invested to calculate meaningful APY
MINIMUM_DAYS_FOR_APY = 1


# ============================================================================
# DATABASE OPTIMIZATION
# ============================================================================

# Batch size for fee distribution queries
# Larger = faster but more memory
FEE_DISTRIBUTION_BATCH_SIZE = 100

# How often to calculate pool statistics cache (in seconds)
POOL_STATS_CACHE_TTL = 300  # 5 minutes


# ============================================================================
# LEGAL & COMPLIANCE
# ============================================================================

# Disclaimer text shown to users before providing liquidity
LP_RISK_DISCLAIMER = """
Providing liquidity involves several risks:
1. IMPERMANENT LOSS: If market odds shift significantly, your LP position may lose value relative to simply holding capital
2. MARKET RISK: If the market resolves with extreme odds, slippage could exceed fee income
3. LIQUIDITY RISK: You may not be able to withdraw immediately if the market is under heavy trading
4. REGULATORY RISK: Prediction markets face regulatory uncertainties in various jurisdictions

Fee income typically offsets small IL losses, but high-volatility markets carry elevated risk.
"""

# Terms accepted for liquidity provision
LP_TERMS_VERSION = "1.0"
LP_TERMS_DATE = "2026-04-18"


# ============================================================================
# MIGRATION & TESTING UTILITIES
# ============================================================================

def get_config_summary():
    """Return a summary of current configuration"""
    return {
        'lmsr_b': DEFAULT_LIQUIDITY_PARAMETER_B,
        'trading_fee_percent': TRADING_FEE_PERCENT,
        'withdrawal_fee_percent': WITHDRAWAL_FEE_PERCENT,
        'early_withdrawal_penalty': EARLY_WITHDRAWAL_PENALTY,
        'lockup_days': EARLY_WITHDRAWAL_LOCKUP_DAYS,
        'min_deposit': MINIMUM_LP_DEPOSIT,
        'distribution_model': FEE_DISTRIBUTION_MODEL,
    }


def validate_config():
    """Validate configuration parameters"""
    errors = []
    
    if DEFAULT_LIQUIDITY_PARAMETER_B <= 0:
        errors.append("DEFAULT_LIQUIDITY_PARAMETER_B must be > 0")
    
    if TRADING_FEE_PERCENT < 0 or TRADING_FEE_PERCENT >= 100:
        errors.append("TRADING_FEE_PERCENT must be between 0 and 99.99")
    
    if WITHDRAWAL_FEE_PERCENT < 0 or WITHDRAWAL_FEE_PERCENT >= 100:
        errors.append("WITHDRAWAL_FEE_PERCENT must be between 0 and 99.99")
    
    if EARLY_WITHDRAWAL_PENALTY < 0 or EARLY_WITHDRAWAL_PENALTY >= 100:
        errors.append("EARLY_WITHDRAWAL_PENALTY must be between 0 and 99.99")
    
    if EARLY_WITHDRAWAL_LOCKUP_DAYS < 0:
        errors.append("EARLY_WITHDRAWAL_LOCKUP_DAYS must be >= 0")
    
    if MINIMUM_LP_DEPOSIT <= 0:
        errors.append("MINIMUM_LP_DEPOSIT must be > 0")
    
    if FEE_DISTRIBUTION_MODEL not in ['EQUAL', 'PRO_RATA']:
        errors.append("FEE_DISTRIBUTION_MODEL must be 'EQUAL' or 'PRO_RATA'")
    
    return errors


if __name__ == '__main__':
    # Print configuration on module import
    import json
    
    errors = validate_config()
    if errors:
        print("⚠️  Configuration Errors:")
        for error in errors:
            print(f"  - {error}")
    else:
        print("✓ Configuration valid")
        print("\nLP Configuration Summary:")
        print(json.dumps(get_config_summary(), indent=2))
