"""Polymarket client split by API role.

This module provides two lightweight clients:
- `PolymarketDataClient` for Data/Gamma endpoints (read-only market data and metadata)
- `PolymarketClobClient` for CLOB trading endpoints (orderbook, orders, positions)

`PolymarketClient` composes the two and routes calls appropriately.
"""
import requests
from typing import Any, Dict, List, Optional
from django.conf import settings
import json
from urllib.parse import urlparse
import logging

from brokerage.services.polymarket.auth import build_l2_headers

logger = logging.getLogger(__name__)


class PolymarketDataClient:
    """Client for Data/Gamma APIs (read-only market data).

    Defaults to environment `POLY_DATA_BASE_URL` or `POLY_GAMMA_BASE_URL` or falls
    back to `https://data-api.polymarket.com`.
    """
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (
            base_url
            or getattr(settings, 'POLY_DATA_BASE_URL', None)
            or getattr(settings, 'POLY_GAMMA_BASE_URL', None)
            or 'https://data-api.polymarket.com'
        )
        self.session = requests.Session()

    def get_markets(self, params: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/markets"
        resp = self.session.get(url, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def get_market(self, market_id: str) -> Dict[str, Any]:
        url = f"{self.base_url}/markets/{market_id}"
        resp = self.session.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def get_trade_history(self, market_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/markets/{market_id}/trades"
        resp = self.session.get(url, params={'limit': limit}, timeout=10)
        resp.raise_for_status()
        return resp.json()
    
    def get_positions(self, account_id: str) -> List[Dict[str, Any]]:
        """Query positions from the Data API (user-level positions/holdings)."""
        url = f"{self.base_url}/positions"
        resp = self.session.get(url, params={'account_id': account_id}, timeout=10)
        resp.raise_for_status()
        return resp.json()


class PolymarketClobClient:
    """Client for CLOB trading endpoints.

    Defaults to `POLY_CLOB_BASE_URL` or `POLYMARKET_BASE_URL` or `https://clob.polymarket.com`.
    Attaches L2 headers per-request when credentials are configured.
    """
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        self.base_url = (
            base_url
            or getattr(settings, 'POLY_CLOB_BASE_URL', None)
            or getattr(settings, 'POLYMARKET_BASE_URL', None)
            or 'https://clob.polymarket.com'
        )
        self.api_key = api_key or getattr(settings, 'POLYMARKET_API_KEY', None)
        self.api_secret = getattr(settings, 'POLY_API_SECRET', None) or getattr(settings, 'POLYMARKET_API_SECRET', None)
        self.api_passphrase = getattr(settings, 'POLY_API_PASSPHRASE', None) or getattr(settings, 'POLYMARKET_API_PASSPHRASE', None)
        self.poly_address = getattr(settings, 'POLY_ADDRESS', None) or getattr(settings, 'POLYMARKET_ADDRESS', None)
        self.session = requests.Session()

    def _maybe_build_l2_headers(self, method: str, full_url: str, body: Optional[str]) -> Dict[str, str]:
        if not all([self.api_key, self.api_secret, self.api_passphrase, self.poly_address]):
            return {}

        parsed = urlparse(full_url)
        path = parsed.path or '/'
        if parsed.query:
            path = f"{path}?{parsed.query}"

        try:
            return build_l2_headers(
                api_key=self.api_key,
                secret_b64=self.api_secret,
                passphrase=self.api_passphrase,
                address=self.poly_address,
                method=method,
                path=path,
                body=body,
            )
        except Exception as e:
            logger.warning(f"Failed to build L2 headers: {e}")
            return {}

    def get_orderbook(self, token_id: str) -> Dict[str, Any]:
        url = f"{self.base_url}/orderbook/{token_id}"
        headers = self._maybe_build_l2_headers('GET', url, None)
        resp = self.session.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def place_order(self, market_id: str, side: str, size: float, price: float, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        url = f"{self.base_url}/orders"
        payload = {
            'market_id': market_id,
            'side': side,
            'size': size,
            'price': price,
        }
        if metadata:
            payload['metadata'] = metadata
        body = json.dumps(payload, separators=(',', ':'))
        headers = self._maybe_build_l2_headers('POST', url, body)
        resp = self.session.post(url, data=body, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        url = f"{self.base_url}/orders/{order_id}"
        headers = self._maybe_build_l2_headers('DELETE', url, None)
        resp = self.session.delete(url, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def get_positions(self, account_id: str) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/positions"
        headers = self._maybe_build_l2_headers('GET', url, None)
        resp = self.session.get(url, params={'account_id': account_id}, headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()


class PolymarketClient:
    """High-level client that routes Data vs CLOB calls to the right client."""
    def __init__(self, data_base_url: Optional[str] = None, clob_base_url: Optional[str] = None, api_key: Optional[str] = None):
        self.data = PolymarketDataClient(base_url=data_base_url)
        self.clob = PolymarketClobClient(base_url=clob_base_url, api_key=api_key)

    # Data endpoints
    def get_markets(self, params: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        return self.data.get_markets(params=params)

    def get_market(self, market_id: str) -> Dict[str, Any]:
        return self.data.get_market(market_id)

    def get_trade_history(self, market_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        return self.data.get_trade_history(market_id, limit=limit)

    # CLOB endpoints
    def get_orderbook(self, token_id: str) -> Dict[str, Any]:
        return self.clob.get_orderbook(token_id)

    def place_order(self, market_id: str, side: str, size: float, price: float, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        return self.clob.place_order(market_id=market_id, side=side, size=size, price=price, metadata=metadata)

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        return self.clob.cancel_order(order_id)

    def get_positions(self, account_id: str) -> List[Dict[str, Any]]:
        # Positions are served by the Data API (user-level holdings/positions)
        return self.data.get_positions(account_id)

