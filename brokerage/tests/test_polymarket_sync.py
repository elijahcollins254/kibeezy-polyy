from django.test import TestCase

from brokerage.models import Market
from brokerage.services.polymarket.sync import fetch_polymarket_market_candidates, sync_polymarket_markets


class PolymarketSyncServiceTests(TestCase):
    def test_fetch_polymarket_market_candidates_filters_by_category(self):
        markets = [
            {"id": "1", "title": "Will the Chiefs win the Super Bowl?", "category": "Sports"},
            {"id": "2", "title": "Will Trump win the election?", "category": "Politics"},
            {"id": "3", "title": "Will Bitcoin hit $100k?", "category": "Crypto"},
        ]

        filtered = fetch_polymarket_market_candidates(markets, limit=10, category="Sports")

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["id"], "1")
        self.assertEqual(filtered[0]["category"], "Sports")

    def test_sync_polymarket_markets_creates_and_approves_selected_markets(self):
        markets = [
            {"id": "10", "title": "Will Arsenal win the Premier League?", "category": "Sports"},
            {"id": "11", "title": "Will the Fed cut rates?", "category": "Economy"},
        ]

        created = sync_polymarket_markets(markets, limit=2, category="Sports", approve=True, selected_external_ids=["10"])

        self.assertEqual(created, 1)
        market = Market.objects.get(external_id="10")
        self.assertTrue(market.is_approved)
        self.assertEqual(market.category, "Sports")
