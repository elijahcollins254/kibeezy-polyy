from django.test import SimpleTestCase
from django.urls import resolve

from brokerage.api.market_views import LegacyMarketChatView, MarketListView
from users.views import dashboard_data_view, history_data_view


class LegacyMarketUrlRoutingTests(SimpleTestCase):
    def test_legacy_markets_root_routes_to_market_list_view(self):
        match = resolve('/api/markets/')
        self.assertEqual(match.func.view_class, MarketListView)

    def test_dashboard_alias_routes_to_user_dashboard_view(self):
        match = resolve('/api/markets/dashboard/')
        self.assertEqual(match.func, dashboard_data_view)

    def test_history_alias_routes_to_user_history_view(self):
        match = resolve('/api/markets/history/')
        self.assertEqual(match.func, history_data_view)

    def test_brokerage_market_chat_route_is_available(self):
        match = resolve('/api/brokerage/123/chat/')
        self.assertEqual(match.func.view_class, LegacyMarketChatView)
