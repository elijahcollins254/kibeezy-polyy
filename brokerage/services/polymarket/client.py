"""Polymarket integration backed by the official polymarket-client SDK.

The prior implementation depended on a custom wrapper around py-clob-client-v2.
This module now exposes the same brokerage-facing methods, but delegates to the
official public and secure clients from polymarket-client.
"""
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


def _get_setting(name: str, default: Optional[str] = None) -> Optional[str]:
    if settings is not None:
        try:
            value = getattr(settings, name, None)
        except Exception:
            # Django settings may be present but not configured in test
            # environments (raises ImproperlyConfigured). Fall back to env.
            value = None
        if value not in (None, ""):
            return value
    if decouple_config is not None:
        value = decouple_config(name, default=None)
        if value not in (None, ""):
            return value
    env_value = os.getenv(name)
    if env_value not in (None, ""):
        return env_value
    return default

try:
    from django.conf import settings
except Exception:  # pragma: no cover - used in lightweight test environments
    settings = None

try:
    from decouple import config as decouple_config
except Exception:  # pragma: no cover - optional dependency
    decouple_config = None

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
        self.base_url = base_url or _get_setting("POLYMARKET_DATA_URL")

    def _client(self) -> PublicClient:
        if PublicClient is None:
            raise RuntimeError("polymarket-client is required")
        return PublicClient()

    def _serialize_market(self, item: Any) -> Dict[str, Any]:
        if item is None:
            return {}

        try:
            payload = item.model_dump()
        except Exception:
            payload = {}

        if not isinstance(payload, dict):
            payload = {}

        base_fields = {
            "id": getattr(item, "id", None),
            "slug": getattr(item, "slug", None),
            "question": getattr(item, "question", None),
            "title": getattr(item, "question", None),
            "description": getattr(item, "description", None),
            "category": getattr(item, "category", None),
            "image": getattr(item, "image", None),
            "icon": getattr(item, "icon", None),
            "outcomes": getattr(item, "outcomes", None),
            "metrics": getattr(item, "metrics", None),
            "prices": getattr(item, "prices", None),
            "state": getattr(item, "state", None),
            "resolution": getattr(item, "resolution", None),
            "sports": getattr(item, "sports", None),
            "events": getattr(item, "events", None),
            "tags": getattr(item, "tags", None),
            "position_ids": getattr(item, "position_ids", None),
        }
        base_fields.update(payload)

        outcome_data = getattr(item, "outcomes", None)
        yes_outcome = getattr(outcome_data, "yes", None) if outcome_data is not None else None
        no_outcome = getattr(outcome_data, "no", None) if outcome_data is not None else None
        if isinstance(base_fields.get("outcomes"), dict):
            yes_token_id = None
            no_token_id = None
            if isinstance(base_fields["outcomes"].get("yes"), dict):
                yes_token_id = base_fields["outcomes"]["yes"].get("token_id")
            if isinstance(base_fields["outcomes"].get("no"), dict):
                no_token_id = base_fields["outcomes"]["no"].get("token_id")
            base_fields["yes_token_id"] = yes_token_id
            base_fields["no_token_id"] = no_token_id
        else:
            base_fields["yes_token_id"] = getattr(yes_outcome, "token_id", None)
            base_fields["no_token_id"] = getattr(no_outcome, "token_id", None)

        if base_fields.get("state") is not None and isinstance(base_fields.get("state"), dict):
            base_fields["active"] = base_fields["state"].get("active")
            base_fields["closed"] = base_fields["state"].get("closed")
            base_fields["end_date"] = base_fields["state"].get("end_date")
            base_fields["start_date"] = base_fields["state"].get("start_date")
        return base_fields

    def get_markets(self, params: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        request_params = dict(params or {})
        limit = request_params.pop('limit', None)
        offset = request_params.pop('offset', None)
        page_size = request_params.pop('page_size', 20)
        active = request_params.pop('active', None)
        if active is not None and 'closed' not in request_params:
            request_params['closed'] = not bool(active)
        if limit is not None:
            try:
                page_size = int(limit)
            except (TypeError, ValueError):
                page_size = page_size
        with self._client() as client:
            paginator = client.list_markets(**request_params, page_size=page_size)
            items = paginator.iter_items()
            if offset is not None:
                try:
                    offset_value = int(offset)
                except (TypeError, ValueError):
                    offset_value = 0
                for _ in range(max(offset_value, 0)):
                    try:
                        next(items)
                    except StopIteration:
                        break

            fetched_items = []
            if limit is None:
                fetched_items = list(items)
            else:
                try:
                    limit_value = int(limit)
                except (TypeError, ValueError):
                    limit_value = 0
                for _ in range(max(limit_value, 0)):
                    try:
                        fetched_items.append(next(items))
                    except StopIteration:
                        break

            return [self._serialize_market(item) for item in fetched_items]

    def get_market(self, market_id: str) -> Dict[str, Any]:
        with self._client() as client:
            market = client.get_market(id=market_id)
            return self._serialize_market(market)

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
        self.base_url = base_url or _get_setting("POLYMARKET_CLOB_URL", "https://clob.polymarket.com")
        self.private_key = (
            private_key
            or _get_setting("POLYMARKET_DEPOSIT_PRIVATE_KEY")
            or _get_setting("POLY_DEPOSIT_PRIVATE_KEY")
            or _get_setting("POLYMARKET_PRIVATE_KEY")
        )
        self.wallet = (
            wallet
            or _get_setting("POLYMARKET_DEPOSIT_WALLET_ADDRESS")
            or _get_setting("POLY_DEPOSIT_ADDRESS")
            or _get_setting("POLYMARKET_WALLET_ADDRESS")
        )
        self.relayer_api_key = relayer_api_key or _get_setting("POLYMARKET_RELAYER_API_KEY")
        self.relayer_api_key_address = relayer_api_key_address or _get_setting("POLYMARKET_RELAYER_API_KEY_ADDRESS")
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
        # Use the SDK's place_market_order which posts the signed order and
        # returns an AcceptedOrder or RejectedOrder (with fields like order_id,
        # trade_ids, status, etc.). We map that to a simple dict for callers.
        response = await client.place_market_order(token_id=token_id, side=side.upper(), amount=amount)
        # AcceptedOrder has attributes like ok, order_id, status, making_amount, taking_amount, trade_ids
        if getattr(response, "ok", False):
            # If the order produced immediate trades (trade_ids), fetch
            # trade details so callers receive fills with size/price.
            trade_ids = tuple(getattr(response, "trade_ids", ()) or ())
            fills: List[Dict[str, Any]] = []
            if trade_ids:
                # Use the same secure client to fetch account trades by id
                try:
                    # list_account_trades returns a paginator; use first_page()
                    for tid in trade_ids:
                        paginator = await client.list_account_trades(id=tid)
                        first = paginator.first_page()
                        for t in first.items:
                            fills.append({
                                "id": getattr(t, "id", None),
                                "size": float(getattr(t, "size", 0)),
                                "price": float(getattr(t, "price", 0)),
                            })
                except Exception:
                    # Best-effort: if fetching trade details fails, leave fills empty
                    fills = []

            return {
                "order_id": getattr(response, "order_id", None),
                "ok": True,
                "status": getattr(response, "status", None),
                "making_amount": getattr(response, "making_amount", None),
                "taking_amount": getattr(response, "taking_amount", None),
                "trade_ids": trade_ids,
                "transactions_hashes": tuple(getattr(response, "transactions_hashes", ()) or ()),
                "fills": fills,
                "raw": response,
            }
        else:
            # RejectedOrder contains error code/message
            return {"order_id": None, "ok": False, "code": getattr(response, "code", None), "message": getattr(response, "message", None), "raw": response}

    def place_limit_order(self, token_id: str, price: float, size: float, side: str) -> Dict[str, Any]:
        return self._run_sync(self._place_limit_order(token_id, price, size, side))

    async def _place_limit_order(self, token_id: str, price: float, size: float, side: str) -> Dict[str, Any]:
        client = await self._get_client()
        # Use SDK's place_limit_order which posts the signed order and returns
        # an AcceptedOrder or RejectedOrder similar to market orders.
        response = await client.place_limit_order(token_id=token_id, price=price, size=size, side=side.upper())
        if getattr(response, "ok", False):
            trade_ids = tuple(getattr(response, "trade_ids", ()) or ())
            fills: List[Dict[str, Any]] = []
            if trade_ids:
                try:
                    for tid in trade_ids:
                        paginator = await client.list_account_trades(id=tid)
                        first = paginator.first_page()
                        for t in first.items:
                            fills.append({
                                "id": getattr(t, "id", None),
                                "size": float(getattr(t, "size", 0)),
                                "price": float(getattr(t, "price", 0)),
                            })
                except Exception:
                    fills = []

            return {
                "order_id": getattr(response, "order_id", None),
                "ok": True,
                "status": getattr(response, "status", None),
                "making_amount": getattr(response, "making_amount", None),
                "taking_amount": getattr(response, "taking_amount", None),
                "trade_ids": trade_ids,
                "transactions_hashes": tuple(getattr(response, "transactions_hashes", ()) or ()),
                "fills": fills,
                "raw": response,
            }
        else:
            return {"order_id": None, "ok": False, "code": getattr(response, "code", None), "message": getattr(response, "message", None), "raw": response}

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
