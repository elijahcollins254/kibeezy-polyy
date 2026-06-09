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
        return self.client.get_orderbook(token_id)

    def place_order(self, market_id: str, side: str, size: float, price: float, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        return self.client.place_order(market_id=market_id, side=side, size=size, price=price, metadata=metadata)

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        return self.client.cancel_order(order_id)

    def get_positions(self, account_id: str) -> List[Dict[str, Any]]:
        return self.client.get_positions(account_id)

    def get_trade_history(self, market_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        return self.client.get_trade_history(market_id, limit=limit)
