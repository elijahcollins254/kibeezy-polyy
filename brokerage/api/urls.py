from django.urls import path
from .views import PlaceOrderView, PolymarketFillWebhookView, PolymarketResolutionWebhookView
from .category_views import CategoryListView
from .market_views import (
    MarketListView,
    MarketDetailView,
    MarketLatestPriceView,
    PolymarketSyncPreviewView,
    PolymarketSyncImportView,
    LegacyMarketDetailsView,
    LegacyMarketChatView,
    LegacyBitcoinMarketView,
    LegacyBitcoinPriceView,
    LegacyBetView,
)

urlpatterns = [
    path('orders/place/', PlaceOrderView.as_view(), name='place-order'),
    path('categories/', CategoryListView.as_view(), name='category-list'),
    path('webhooks/polymarket-fills/', PolymarketFillWebhookView.as_view(), name='polymarket-fill-webhook'),
    path('webhooks/polymarket-resolution/', PolymarketResolutionWebhookView.as_view(), name='polymarket-resolution-webhook'),
    path('markets/', MarketListView.as_view(), name='market-list'),
    path('markets/<str:external_id>/latest/', MarketLatestPriceView.as_view(), name='market-latest-price'),
    path('markets/<str:external_id>/', MarketDetailView.as_view(), name='market-detail'),
    path('markets/<str:external_id>/trades/', MarketDetailView.as_view(), name='market-trades'),
    path('markets/<str:external_id>/price-history/', MarketDetailView.as_view(), name='market-price-history'),
    path('markets/<str:external_id>/positions/', MarketDetailView.as_view(), name='market-positions'),
    path('markets/search/', MarketListView.as_view(), name='market-search'),
    path('admin/polymarket/sync-preview/', PolymarketSyncPreviewView.as_view(), name='polymarket-sync-preview'),
    path('admin/polymarket/sync/', PolymarketSyncImportView.as_view(), name='polymarket-sync-import'),
    path('bitcoin/', LegacyBitcoinMarketView.as_view(), name='legacy-bitcoin-market'),
    path('bitcoin/price/', LegacyBitcoinPriceView.as_view(), name='legacy-bitcoin-price'),
    path('<int:market_id>/details/', LegacyMarketDetailsView.as_view(), name='legacy-market-details'),
    path('<int:market_id>/chat/', LegacyMarketChatView.as_view(), name='legacy-market-chat'),
    path('bet/', LegacyBetView.as_view(), name='legacy-bet'),
]
