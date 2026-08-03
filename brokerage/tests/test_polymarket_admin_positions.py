from unittest.mock import Mock

from django.test import SimpleTestCase

from brokerage.api.market_views import build_polymarket_admin_payload


class PolymarketAdminPayloadTests(SimpleTestCase):
    def test_build_polymarket_admin_payload_returns_positions_and_balance(self):
        user = Mock()
        user.id = 1
        user.full_name = "Ada Lovelace"
        user.username = "ada"
        user.phone_number = "+254700000001"
        user.eth_address = "0xabc123"

        adapter = Mock()
        adapter.get_positions.return_value = [
            {
                "id": "pos-1",
                "market": "market-1",
                "size": 1.25,
                "token_id": "token-1",
            }
        ]
        adapter.get_balance.return_value = 42.75

        payload = build_polymarket_admin_payload([user], adapter=adapter)

        self.assertEqual(payload["balance"], 42.75)
        self.assertEqual(payload["total_positions"], 1)
        self.assertEqual(payload["user_count"], 1)
        self.assertEqual(payload["positions"][0]["user"]["name"], "Ada Lovelace")
        self.assertEqual(payload["positions"][0]["positions"][0]["size"], 1.25)
