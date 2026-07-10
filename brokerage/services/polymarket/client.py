"""Polymarket client split by API role.

This module provides:
- `PolymarketDataClient` for Data/Gamma endpoints (read-only market data and metadata)
- `PolymarketClobClient` for CLOB trading endpoints using py-clob-client-v2
- `PolymarketClient` composing both clients

Uses py-clob-client-v2 for proper L1 signing and authentication.
"""
import requests
from typing import Any, Dict, List, Optional
from django.conf import settings
import json
import logging
import os
from pathlib import Path

# Load local .env if present so the service uses the same values as the shell.
try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

if load_dotenv is not None:
    env_path = Path(__file__).resolve().parents[3] / '.env'
    if env_path.exists():
        load_dotenv(env_path, override=False)

logger = logging.getLogger(__name__)


class PolymarketDepositWalletRequired(Exception):
    """Raised when Polymarket rejects the maker address and requires deposit wallet flow."""
    pass

try:
    from py_clob_client_v2 import (
        ClobClient,
        OrderArgs,
        MarketOrderArgs,
        OrderType,
        Side,
        BalanceAllowanceParams,
        AssetType,
    )
    HAS_SDK = True
except ImportError:
    HAS_SDK = False
    logger.error("py-clob-client-v2 not installed. Install it for order placement.")


class PolymarketDataClient:
    """Client for Data/Gamma APIs (read-only market data).

    Defaults to environment `POLY_DATA_BASE_URL` or `POLY_GAMMA_BASE_URL` or falls
    back to `https://data-api.polymarket.com`.
    """
    def __init__(self, base_url: Optional[str] = None, private_key: Optional[str] = None, funder_address: Optional[str] = None, signature_type: Optional[int] = None):
        self.base_url = (
            base_url
            or getattr(settings, 'POLY_DATA_BASE_URL', None)
            or getattr(settings, 'POLY_GAMMA_BASE_URL', None)
            or 'https://gamma-api.polymarket.com'
        )
        self.clob_base_url = (
            getattr(settings, 'POLY_CLOB_BASE_URL', None)
            or getattr(settings, 'POLYMARKET_BASE_URL', None)
            or os.getenv('POLY_CLOB_BASE_URL')
            or os.getenv('POLYMARKET_CLOB_PROXY_URL')
            or 'https://clob.polymarket.com'
        )
        self.session = requests.Session()

    def get_markets(self, params: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/markets"
        try:
            resp = self.session.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            # Fallback to Gamma API if data-api fails
            if 'data-api' in url:
                url = url.replace('data-api.polymarket.com', 'gamma-api.polymarket.com')
                resp = self.session.get(url, params=params, timeout=10)
                resp.raise_for_status()
                return resp.json()
            raise

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

    def get_price_history(self, token_id: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        url = f"{self.clob_base_url}/prices-history"
        query = {'market': token_id}
        if params:
            query.update({key: value for key, value in params.items() if value not in (None, '')})
        resp = self.session.get(url, params=query, timeout=10)
        resp.raise_for_status()
        return resp.json()
    
    def get_positions(self, account_id: str) -> List[Dict[str, Any]]:
        """Query positions from the Data API (user-level positions/holdings)."""
        url = f"{self.base_url}/positions"
        resp = self.session.get(url, params={'user': account_id}, timeout=10)
        resp.raise_for_status()
        return resp.json()


class PolymarketClobClient:
    """Client for CLOB trading endpoints using py-clob-client-v2 SDK.

    Uses L1 authentication (private key) to derive API credentials and place orders.
    Configured via environment variables or Django settings.
    """
    def __init__(
        self,
        base_url: Optional[str] = None,
        private_key: Optional[str] = None,
        funder_address: Optional[str] = None,
        signature_type: Optional[int] = None,
    ):
        if not HAS_SDK:
            raise RuntimeError("py-clob-client-v2 is required. Install it to use PolymarketClobClient.")

        # Use Cloudflare Worker proxy to bypass geoblocking (if configured)
        # This allows requests from non-US regions to work
        self.base_url = (
            base_url
            or getattr(settings, 'POLY_CLOB_BASE_URL', None)
            or getattr(settings, 'POLYMARKET_BASE_URL', None)
            or os.getenv('POLY_CLOB_BASE_URL')  # Check environment for proxy URL
            or os.getenv('POLYMARKET_CLOB_PROXY_URL')  # Alternative: dedicated proxy env var
            or 'https://clob.polymarket.com'  # Fallback: direct (may fail if geoblocked)
        )

        # Get credentials from provided args, settings or environment.
        # Prefer the deposit-wallet address when it is configured so the maker
        # address matches what Polymarket expects for deposit-wallet trading.
        deposit_wallet_address = (
            os.getenv('DEPOSIT_WALLET_ADDRESS')
            or os.getenv('POLY_DEPOSIT_ADDRESS')
            or getattr(settings, 'DEPOSIT_WALLET_ADDRESS', None)
            or getattr(settings, 'POLY_DEPOSIT_ADDRESS', None)
        )
        self.private_key = (
            private_key
            or os.getenv('POLY_DEPOSIT_PRIVATE_KEY')
            or getattr(settings, 'POLY_DEPOSIT_PRIVATE_KEY', None)
            or os.getenv('POLY_PRIVATE_KEY')
            or getattr(settings, 'POLY_PRIVATE_KEY', None)
        )
        self.funder_address = (
            funder_address
            or deposit_wallet_address
            or os.getenv('POLY_ADDRESS')
            or getattr(settings, 'POLY_ADDRESS', None)
            or getattr(settings, 'POLYMARKET_ADDRESS', None)
        )
        # signature_type: 0=EOA, 1=Email, 2=Proxy/Deposit
        raw_sig_type = (
            signature_type
            if signature_type is not None
            else getattr(settings, 'POLY_SIGNATURE_TYPE', None)
            or os.getenv('POLY_SIGNATURE_TYPE')
        )
        if raw_sig_type in (None, ''):
            raw_sig_type = 2 if deposit_wallet_address else 0
        self.signature_type = int(raw_sig_type)

        self._client = None
        self._init_client()

    def _init_client(self):
        """Initialize the ClobClient with authentication."""
        if not self.private_key:
            logger.warning("POLY_PRIVATE_KEY not set. Order placement will fail.")
            return

        try:
            logger.info(
                "Initializing Polymarket CLOB client with signer=%s signature_type=%s",
                self.funder_address,
                self.signature_type,
            )
            self._client = ClobClient(
                host=self.base_url,
                key=self.private_key,
                chain_id=137,  # Polygon mainnet
                signature_type=self.signature_type,
                funder=self.funder_address,
            )
            # Derive and set API credentials for L2 requests
            creds = self._client.derive_api_key()
            self._client.set_api_creds(creds)
            logger.info("Polymarket CLOB client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Polymarket CLOB client: {e}")
            self._client = None

    def get_orderbook(self, token_id: str) -> Dict[str, Any]:
        """Fetch order book for a token."""
        if not self._client:
            raise RuntimeError("CLOB client not initialized")
        
        book = self._client.get_order_book(token_id)
        return book

    def get_midpoint(self, token_id: str) -> float:
        """Get midpoint price for a token."""
        if not self._client:
            raise RuntimeError("CLOB client not initialized")
        
        mid = self._client.get_midpoint(token_id)
        return float(mid.get('mid', 0))

    def place_market_order(self, token_id: str, amount: float, side: str) -> Dict[str, Any]:
        """
        Place a market order using py-clob-client-v2.
        
        Args:
            token_id: Token ID to trade
            amount: Amount in USD to spend (for BUY) or shares to sell (for SELL)
            side: 'BUY' or 'SELL'
        
        Returns:
            Order response dict
        """
        if not self._client:
            raise RuntimeError("CLOB client not initialized")

        try:
            side_enum = Side.BUY if side.upper() == 'BUY' else Side.SELL
            
            # Create market order
            market_order = MarketOrderArgs(
                token_id=token_id,
                amount=amount,
                side=side_enum,
                order_type=OrderType.FOK,  # Fill-or-Kill
            )
            
            # Sign the order
            signed_order = self._client.create_market_order(market_order)
            
            # Post the order
            response = self._client.post_order(signed_order, OrderType.FOK)
            
            logger.info(f"Market order placed: {side} {amount} {token_id}")
            return response
        except Exception as e:
            msg = str(e) or ''
            logger.error(f"Failed to place market order: {e}")
            # Detect common Polymarket rejection when using EOA maker address
            if 'maker address not allowed' in msg.lower():
                raise PolymarketDepositWalletRequired(
                    "Polymarket rejected the maker address ('maker address not allowed'). This account requires the deposit wallet flow.\n"
                    "Fix: use the Polymarket deposit wallet for trading (set POLY_PRIVATE_KEY to the deposit wallet key or configure per-user deposit wallets)."
                )
            raise

    def place_limit_order(self, token_id: str, price: float, size: float, side: str) -> Dict[str, Any]:
        """
        Place a limit order using py-clob-client-v2.
        
        Args:
            token_id: Token ID to trade
            price: Limit price (0.0-1.0)
            size: Number of shares
            side: 'BUY' or 'SELL'
        
        Returns:
            Order response dict
        """
        if not self._client:
            raise RuntimeError("CLOB client not initialized")

        try:
            side_enum = Side.BUY if side.upper() == 'BUY' else Side.SELL
            
            # Create limit order
            limit_order = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=side_enum,
            )
            
            # Sign the order
            signed_order = self._client.create_order(limit_order)
            
            # Post the order (GTC = Good Till Cancelled)
            response = self._client.post_order(signed_order, OrderType.GTC)
            
            logger.info(f"Limit order placed: {side} {size}@{price} {token_id}")
            return response
        except Exception as e:
            msg = str(e) or ''
            logger.error(f"Failed to place limit order: {e}")
            if 'maker address not allowed' in msg.lower():
                raise PolymarketDepositWalletRequired(
                    "Polymarket rejected the maker address ('maker address not allowed'). This account requires the deposit wallet flow.\n"
                    "Fix: use the Polymarket deposit wallet for trading (set POLY_PRIVATE_KEY to the deposit wallet key or configure per-user deposit wallets)."
                )
            raise

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel an order."""
        if not self._client:
            raise RuntimeError("CLOB client not initialized")
        
        return self._client.cancel_orders([order_id])

    def get_balance(self) -> float:
        """Get account balance in USD."""
        if not self._client:
            raise RuntimeError("CLOB client not initialized")
        
        try:
            balance_data = self._client.get_balance_allowance(
                BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            )
            balance_wei = int(balance_data.get('balance', 0))
            balance_usd = balance_wei / 1e6  # Convert from wei to USD
            return balance_usd
        except Exception as e:
            logger.error(f"Failed to fetch balance: {e}")
            return 0.0

    def get_positions(self, account_id: str) -> List[Dict[str, Any]]:
        """Get user positions."""
        if not self._client:
            raise RuntimeError("CLOB client not initialized")
        
        # This would need to be implemented based on py-clob-client-v2 API
        # For now, return empty list
        return []


class PolymarketClient:
    """High-level client that routes Data vs CLOB calls to the right client."""
    def __init__(self, data_base_url: Optional[str] = None, clob_base_url: Optional[str] = None):
        self.data = PolymarketDataClient(base_url=data_base_url)
        try:
            self.clob = PolymarketClobClient(base_url=clob_base_url)
        except RuntimeError as e:
            logger.warning(f"CLOB client unavailable: {e}")
            self.clob = None

    # Data endpoints
    def get_markets(self, params: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        return self.data.get_markets(params=params)

    def get_market(self, market_id: str) -> Dict[str, Any]:
        return self.data.get_market(market_id)

    def get_trade_history(self, market_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        return self.data.get_trade_history(market_id, limit=limit)

    def get_price_history(self, token_id: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        return self.data.get_price_history(token_id, params=params)

    # CLOB endpoints
    def get_orderbook(self, token_id: str) -> Dict[str, Any]:
        if not self.clob:
            raise RuntimeError("CLOB client not available")
        return self.clob.get_orderbook(token_id)

    def place_order(self, market_id: str, side: str, size: float, price: float, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        if not self.clob:
            raise RuntimeError("CLOB client not available")
        return self.clob.place_market_order(market_id, size, side)

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        if not self.clob:
            raise RuntimeError("CLOB client not available")
        return self.clob.cancel_order(order_id)

    def get_positions(self, account_id: str) -> List[Dict[str, Any]]:
        # Positions are served by the Data API (user-level holdings/positions)
        return self.data.get_positions(account_id)


    def get_market(self, market_id: str) -> Dict[str, Any]:
        return self.data.get_market(market_id)

    def get_trade_history(self, market_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        return self.data.get_trade_history(market_id, limit=limit)

    def get_price_history(self, token_id: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        return self.data.get_price_history(token_id, params=params)

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
