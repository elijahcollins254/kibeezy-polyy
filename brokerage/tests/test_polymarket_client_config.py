import os
from unittest.mock import patch

from brokerage.services.polymarket.client import PolymarketClobClient


class DummySettings:
    POLYMARKET_CLOB_URL = "https://clob.example.test"
    POLYMARKET_DATA_URL = "https://gamma.example.test"
    POLYMARKET_DEPOSIT_PRIVATE_KEY = "0xsettings-private"
    POLYMARKET_DEPOSIT_WALLET_ADDRESS = "0xsettings-wallet"
    POLYMARKET_RELAYER_API_KEY = "settings-relayer"
    POLYMARKET_RELAYER_API_KEY_ADDRESS = "0xsettings-relayer-address"


def test_client_uses_django_settings_for_polymarket_credentials():
    with patch("brokerage.services.polymarket.client.settings", DummySettings()):
        with patch.dict(os.environ, {}, clear=True):
            client = PolymarketClobClient()

            assert client.base_url == "https://clob.example.test"
            assert client.private_key == "0xsettings-private"
            assert client.wallet == "0xsettings-wallet"
            assert client.relayer_api_key == "settings-relayer"
            assert client.relayer_api_key_address == "0xsettings-relayer-address"
