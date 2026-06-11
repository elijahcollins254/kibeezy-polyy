from typing import Any, Dict, List, Optional
from .client import PolymarketClient


class PolymarketAdapter:
    """Adapter layer that exposes a stable interface to the rest of the system.

    This isolates direct client usage and allows swapping providers (e.g., Kalshi) later.
    """
    def __init__(self, client: Optional[PolymarketClient] = None):
        self.client = client or PolymarketClient()

    def get_markets(self, params: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        return self.client.get_markets(params=params)

    def get_market(self, market_id: str) -> Dict[str, Any]:
        return self.client.get_market(market_id)

    def get_orderbook(self, token_id: str) -> Dict[str, Any]:
        """Get order book for a token."""
        if not self.client.clob:
            raise RuntimeError("CLOB client not available")
        return self.client.clob.get_orderbook(token_id)

    def get_midpoint(self, token_id: str) -> float:
        """Get midpoint price for a token."""
        if not self.client.clob:
            raise RuntimeError("CLOB client not available")
        return self.client.clob.get_midpoint(token_id)

    def place_market_order(
        self,
        token_id: str,
        amount: float,
        side: str,
    ) -> Dict[str, Any]:
        """
        Place a market order on Polymarket.
        
        Args:
            token_id: Token ID from market.clobTokenIds
            amount: Amount in USD to spend (for BUY) or shares (for SELL)
            side: 'BUY' or 'SELL'
        
        Returns:
            Order response from Polymarket
        """
        if not self.client.clob:
            raise RuntimeError("CLOB client not available")
        return self.client.clob.place_market_order(token_id, amount, side)

    def place_limit_order(
        self,
        token_id: str,
        price: float,
        size: float,
        side: str,
    ) -> Dict[str, Any]:
        """
        Place a limit order on Polymarket.
        
        Args:
            token_id: Token ID from market.clobTokenIds
            price: Limit price (0.0-1.0 representing probabilities)
            size: Number of shares
            side: 'BUY' or 'SELL'
        
        Returns:
            Order response from Polymarket
        """
        if not self.client.clob:
            raise RuntimeError("CLOB client not available")
        return self.client.clob.place_limit_order(token_id, price, size, side)

    def place_order(self, market_id: str, side: str, size: float, price: float, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Legacy method for backward compatibility. 
        Routes to appropriate order type based on price value.
        """
        # Interpret: if price is set, it's a limit order; otherwise market
        # For now, assume market order
        return self.place_market_order(market_id, size, side)

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        if not self.client.clob:
            raise RuntimeError("CLOB client not available")
        return self.client.clob.cancel_order(order_id)

    def get_positions(self, account_id: str) -> List[Dict[str, Any]]:
        """Get user positions."""
        if not self.client.clob:
            raise RuntimeError("CLOB client not available")
        return self.client.clob.get_positions(account_id)

    def get_trade_history(self, market_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        return self.client.data.get_trade_history(market_id, limit=limit)

    def get_balance(self) -> float:
        """Get account balance in USD."""
        if not self.client.clob:
            raise RuntimeError("CLOB client not available")
        return self.client.clob.get_balance()

