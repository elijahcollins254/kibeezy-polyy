"""
Trading fee calculation and management service.
"""
from decimal import Decimal
from django.conf import settings
from typing import Dict, Any, Tuple


class FeeService:
    """Service for calculating and managing trading fees."""
    
    @staticmethod
    def calculate_trading_fee(amount: Decimal) -> Decimal:
        """
        Calculate trading fee based on order amount.
        
        Args:
            amount: Order amount in base currency (KES)
        
        Returns:
            Trading fee as Decimal
        """
        fee_pct = Decimal(str(settings.TRADING_FEE_PCT))
        fee = (amount * fee_pct / Decimal('100')).quantize(Decimal('0.01'))
        return fee
    
    @staticmethod
    def get_total_cost(amount: Decimal) -> Tuple[Decimal, Decimal]:
        """
        Get total cost including fee.
        
        Args:
            amount: Order amount in base currency (KES)
        
        Returns:
            Tuple of (fee, total_cost)
        """
        fee = FeeService.calculate_trading_fee(amount)
        total_cost = amount + fee
        return fee, total_cost
    
    @staticmethod
    def format_fee_info(amount: Decimal) -> Dict[str, Any]:
        """
        Return fee information in user-friendly format.
        
        Args:
            amount: Order amount in base currency (KES)
        
        Returns:
            Dict with amount, fee, fee_pct, and total_cost
        """
        fee, total_cost = FeeService.get_total_cost(amount)
        return {
            'amount': float(amount),
            'fee': float(fee),
            'fee_pct': float(settings.TRADING_FEE_PCT),
            'total_cost': float(total_cost),
        }
    
    @staticmethod
    def format_fee_display(fee: Decimal, amount: Decimal) -> str:
        """
        Format fee for display to user.
        
        Args:
            fee: Fee amount
            amount: Original amount
        
        Returns:
            Formatted string like "KES 5.00 (0.5%)"
        """
        fee_pct = (fee / amount * Decimal('100')).quantize(Decimal('0.01')) if amount > 0 else Decimal('0')
        return f"KES {fee} ({fee_pct}%)"
