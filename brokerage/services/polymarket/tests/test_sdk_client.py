from types import SimpleNamespace

import pytest

from brokerage.services.polymarket import client as polymarket_client_module


class DummyPaginator:
    def __init__(self, items):
        self._items = items

    def first_page(self):
        return SimpleNamespace(items=self._items)

    def iter_items(self):
        return iter(self._items)


class DummyPublicClient:
    instances = []

    def __init__(self):
        self.calls = []
        type(self).instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def list_markets(self, **kwargs):
        self.calls.append(kwargs)
        return DummyPaginator([
            SimpleNamespace(
                id="market-1",
                slug="alpha-market",
                question="Will it happen?",
                outcomes=SimpleNamespace(yes=SimpleNamespace(token_id="yes-token")),
                clob_token_ids=["yes-token"],
            )
        ])


class DummySecureClient:
    instances = []

    def __init__(self):
        self.calls = []
        type(self).instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def close(self):
        self.calls.append("close")

    @classmethod
    async def create(cls, **kwargs):
        instance = cls()
        instance.calls.append(kwargs)
        return instance

    async def setup_trading_approvals(self):
        self.calls.append("setup")

    async def create_limit_order(self, **kwargs):
        self.calls.append(("create_limit_order", kwargs))
        return SimpleNamespace(signature="signed-order")

    async def place_limit_order(self, **kwargs):
        self.calls.append(("place_limit_order", kwargs))
        return SimpleNamespace(order_id="order-123", ok=True, trade_ids=("trade-1",), status="accepted")

    async def create_market_order(self, **kwargs):
        self.calls.append(("create_market_order", kwargs))
        return SimpleNamespace(signature="signed-order")

    async def place_market_order(self, **kwargs):
        self.calls.append(("place_market_order", kwargs))
        return SimpleNamespace(order_id="market-order-123", ok=True, trade_ids=("trade-2",), status="accepted")

    async def list_account_trades(self, **kwargs):
        # Return a paginator with a single trade matching the requested id
        tid = kwargs.get('id')
        if tid is None:
            return DummyPaginator([])
        # Provide a mock trade object with id, size and price
        return DummyPaginator([SimpleNamespace(id=tid, size=2, price=0.52)])


@pytest.fixture
def patch_sdk(monkeypatch):
    monkeypatch.setattr(polymarket_client_module, "PublicClient", DummyPublicClient)
    monkeypatch.setattr(polymarket_client_module, "AsyncSecureClient", DummySecureClient)



def test_get_markets_uses_official_public_client(patch_sdk):
    client = polymarket_client_module.PolymarketClient()

    markets = client.get_markets(params={"closed": False})

    assert markets[0]["id"] == "market-1"
    assert markets[0]["slug"] == "alpha-market"
    assert markets[0]["question"] == "Will it happen?"
    assert polymarket_client_module.PublicClient.instances[0].calls[0] == {"closed": False, "page_size": 20}


def test_get_markets_accepts_limit_and_uses_page_size(patch_sdk):
    client = polymarket_client_module.PolymarketClient()

    markets = client.get_markets(params={"closed": False, "limit": 1})

    assert markets[0]["id"] == "market-1"
    assert markets[0]["slug"] == "alpha-market"
    assert markets[0]["question"] == "Will it happen?"
    assert polymarket_client_module.PublicClient.instances[0].calls[0] == {"closed": False, "page_size": 20}


def test_place_limit_order_uses_official_secure_client(patch_sdk):
    client = polymarket_client_module.PolymarketClient(
        private_key="0x" + "a" * 64,
        wallet="0xwallet",
        relayer_api_key="relayer-key",
        relayer_api_key_address="0xAac175DdffedbDfAB0D52B281e5CE18058F5ccc2",
    )

    response = client.place_limit_order(
        token_id="yes-token",
        price=0.52,
        size=2,
        side="BUY",
    )

    assert response["order_id"] == "order-123"
