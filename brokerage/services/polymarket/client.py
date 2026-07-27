"""Polymarket integration backed by the official polymarket-client SDK.

The prior implementation depended on a custom wrapper around py-clob-client-v2.
This module now exposes the same brokerage-facing methods, but delegates to the
official public and secure clients from polymarket-client.
"""
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from django.conf import settings
except Exception:  # pragma: no cover - used in lightweight test environments
    settings = None

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency
    load_dotenv = None

if load_dotenv is not None:
    env_path = Path(__file__).resolve().parents[3] / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)

try:
    from polymarket import AsyncSecureClient, PublicClient, RelayerApiKey
except Exception as exc:  # pragma: no cover - dependency availability is runtime-configured
    AsyncSecureClient = None
    PublicClient = None
    RelayerApiKey = None
    logger = logging.getLogger(__name__)
    logger.warning("polymarket-client is not installed: %s", exc)
else:
    logger = logging.getLogger(__name__)


class PolymarketDepositWalletRequired(Exception):
    """Raised when Polymarket rejects the maker address and requires deposit wallet flow."""


class PolymarketDataClient:
    """Read-only market data client backed by the official public SDK."""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or (
            getattr(settings, "POLYMARKET_DATA_URL", None) if settings is not None else None
        ) or os.getenv("POLYMARKET_DATA_URL")

    def _client(self) -> PublicClient:
        if PublicClient is None:
            raise RuntimeError("polymarket-client is required")
        return PublicClient()

    def get_markets(self, params: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        with self._client() as client:
            paginator = client.list_markets(**(params or {}), page_size=20)
            first_page = paginator.first_page()
            return [
                {
                    "id": getattr(item, "id", None),
                    "slug": getattr(item, "slug", None),
                    "question": getattr(item, "question", None),
                    "outcomes": {
                        "yes": {
                            "token_id": getattr(getattr(getattr(item, "outcomes", None), "yes", None), "token_id", None),
                        }
                    },
                    "clob_token_ids": getattr(item, "clob_token_ids", None),
                }
                for item in first_page.items
            ]

    def get_market(self, market_id: str) -> Dict[str, Any]:
        with self._client() as client:
            market = client.get_market(id=market_id)
            return {
                "id": getattr(market, "id", None),
                "slug": getattr(market, "slug", None),
                "question": getattr(market, "question", None),
                "outcomes": {
                    "yes": {
                        "token_id": getattr(getattr(getattr(market, "outcomes", None), "yes", None), "token_id", None),
                    }
                },
                "clob_token_ids": getattr(market, "clob_token_ids", None),
            }

    def get_trade_history(self, market_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        with self._client() as client:
            trades = client.list_trades(market=market_id, page_size=limit)
            first_page = trades.first_page()
            return [
                {
                    "id": getattr(item, "id", None),
                    "price": getattr(item, "price", None),
                    "size": getattr(item, "size", None),
                }
                for item in first_page.items
            ]

    def get_price_history(self, token_id: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        with self._client() as client:
            return client.get_price_history(token_id=token_id, **(params or {}))

    def get_positions(self, account_id: str) -> List[Dict[str, Any]]:
        with self._client() as client:
            paginator = client.list_positions(user=account_id, page_size=20)
            first_page = paginator.first_page()
            return [
                {
                    "id": getattr(item, "id", None),
                    "size": getattr(item, "size", None),
                    "token_id": getattr(item, "token_id", None),
                    "market": getattr(item, "market", None),
                }
                for item in first_page.items
            ]


class PolymarketClobClient:
    """Trading client backed by AsyncSecureClient from polymarket-client."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        private_key: Optional[str] = None,
        wallet: Optional[str] = None,
        relayer_api_key: Optional[str] = None,
        relayer_api_key_address: Optional[str] = None,
    ):
        self.base_url = base_url or (
            getattr(settings, "POLYMARKET_CLOB_URL", None) if settings is not None else None
        ) or os.getenv("POLYMARKET_CLOB_URL")
        self.private_key = private_key or os.getenv("POLYMARKET_DEPOSIT_PRIVATE_KEY") or os.getenv("POLY_DEPOSIT_PRIVATE_KEY")
        self.wallet = wallet or os.getenv("POLYMARKET_DEPOSIT_WALLET_ADDRESS") or os.getenv("POLY_DEPOSIT_ADDRESS")
        self.relayer_api_key = relayer_api_key or os.getenv("POLYMARKET_RELAYER_API_KEY")
        self.relayer_api_key_address = relayer_api_key_address or os.getenv("POLYMARKET_RELAYER_API_KEY_ADDRESS")
        self._secure_client = None

    async def _get_client(self):
        if AsyncSecureClient is None:
            raise RuntimeError("polymarket-client is required")
        if self._secure_client is None:
            api_key = None
            if RelayerApiKey is not None and self.relayer_api_key and self.relayer_api_key_address:
                api_key = RelayerApiKey(key=self.relayer_api_key, address=self.relayer_api_key_address)
            self._secure_client = await AsyncSecureClient.create(
                private_key=self.private_key,
                wallet=self.wallet,
                api_key=api_key,
            )
        return self._secure_client

    async def _close_client(self):
        if self._secure_client is not None:
            await self._secure_client.close()
            self._secure_client = None

    def get_orderbook(self, token_id: str) -> Dict[str, Any]:
        raise NotImplementedError("Order book reads should use the public client directly")

    def get_midpoint(self, token_id: str) -> float:
        raise NotImplementedError("Midpoint reads should use the public client directly")

    def place_market_order(self, token_id: str, amount: float, side: str) -> Dict[str, Any]:
        return self._run_sync(self._place_market_order(token_id, amount, side))

    async def _place_market_order(self, token_id: str, amount: float, side: str) -> Dict[str, Any]:
        client = await self._get_client()
        response = await client.create_market_order(token_id=token_id, side=side.upper(), amount=amount)
        return {"order_id": getattr(response, "order_id", None), "ok": True, "raw": response}

    def place_limit_order(self, token_id: str, price: float, size: float, side: str) -> Dict[str, Any]:
        return self._run_sync(self._place_limit_order(token_id, price, size, side))

    async def _place_limit_order(self, token_id: str, price: float, size: float, side: str) -> Dict[str, Any]:
        client = await self._get_client()
        response = await client.create_limit_order(token_id=token_id, price=price, size=size, side=side.upper())
        return {"order_id": getattr(response, "order_id", None), "ok": True, "raw": response}

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        return self._run_sync(self._cancel_order(order_id))

    async def _cancel_order(self, order_id: str) -> Dict[str, Any]:
        client = await self._get_client()
        response = await client.cancel_order(order_id=order_id)
        return {"order_id": order_id, "ok": True, "raw": response}

    def get_balance(self) -> float:
        # Use the secure client to fetch collateral balance/allowance
        return self._run_sync(self._get_balance())

    async def _get_balance(self) -> float:
        client = await self._get_client()
        try:
            balance_data = await client.get_balance_allowance(asset_type='COLLATERAL')
            # BalanceAllowance model may present numeric fields or dict-like
            balance = getattr(balance_data, 'balance', None)
            if balance is None and isinstance(balance_data, dict):
                balance = balance_data.get('balance', 0)
            balance_wei = int(balance or 0)
            balance_usd = balance_wei / 1e6
            return float(balance_usd)
        except Exception as e:
            logger.error(f"Failed to fetch balance: {e}")
            return 0.0

    def get_positions(self, account_id: str) -> List[Dict[str, Any]]:
        raise NotImplementedError("Portfolio queries should use the public client directly")

    def _run_sync(self, coro):
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        else:
            return loop.run_until_complete(coro)


class PolymarketClient:
    """High-level client that routes brokerage integration through the official SDK."""

    def __init__(
        self,
        data_base_url: Optional[str] = None,
        clob_base_url: Optional[str] = None,
        private_key: Optional[str] = None,
        wallet: Optional[str] = None,
        relayer_api_key: Optional[str] = None,
        relayer_api_key_address: Optional[str] = None,
    ):
        self.data = PolymarketDataClient(base_url=data_base_url)
        self.clob = PolymarketClobClient(
            base_url=clob_base_url,
            private_key=private_key,
            wallet=wallet,
            relayer_api_key=relayer_api_key,
            relayer_api_key_address=relayer_api_key_address,
        )

    def get_markets(self, params: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        return self.data.get_markets(params=params)

    def get_market(self, market_id: str) -> Dict[str, Any]:
        return self.data.get_market(market_id)

    def get_trade_history(self, market_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        return self.data.get_trade_history(market_id, limit=limit)

    def get_price_history(self, token_id: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        return self.data.get_price_history(token_id=token_id, params=params)

    def get_orderbook(self, token_id: str) -> Dict[str, Any]:
        return self.data.get_market(token_id)

    def place_order(self, market_id: str, side: str, size: float, price: float, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        return self.clob.place_market_order(token_id=market_id, amount=size, side=side)

    def place_market_order(self, token_id: str, amount: float, side: str) -> Dict[str, Any]:
        return self.clob.place_market_order(token_id=token_id, amount=amount, side=side)

    def place_limit_order(self, token_id: str, price: float, size: float, side: str) -> Dict[str, Any]:
        return self.clob.place_limit_order(token_id=token_id, price=price, size=size, side=side)

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        return self.clob.cancel_order(order_id=order_id)

    def get_positions(self, account_id: str) -> List[Dict[str, Any]]:
        return self.data.get_positions(account_id)
