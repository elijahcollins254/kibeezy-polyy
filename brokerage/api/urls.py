from django.urls import include, path

from .category_views import CategoryListView
from .market_views import (
    AllMarketsView,
    DebugMarketsView,
    LegacyBetView,
    LegacyMarketChatView,
    LegacyMarketDetailsView,
    LiquidityCompatibilityView,
    MarketAvailabilityView,
    MarketDetailView,
    MarketLatestPriceView,
    MarketListView,
)
from .views import PlaceOrderView, PolymarketFillWebhookView, PolymarketResolutionWebhookView

urlpatterns = [
    path('orders/place/', PlaceOrderView.as_view(), name='place-order'),
    path('categories/', CategoryListView.as_view(), name='category-list'),
    path('webhooks/polymarket-fills/', PolymarketFillWebhookView.as_view(), name='polymarket-fill-webhook'),
    path('webhooks/polymarket-resolution/', PolymarketResolutionWebhookView.as_view(), name='polymarket-resolution-webhook'),
    path('markets/', MarketListView.as_view(), name='market-list'),
    path('markets/all/', AllMarketsView.as_view(), name='all-markets'),
    path('markets/debug/', DebugMarketsView.as_view(), name='debug-markets'),
    path('markets/<str:external_id>/latest/', MarketLatestPriceView.as_view(), name='market-latest-price'),
    path('markets/<str:external_id>/', MarketDetailView.as_view(), name='market-detail'),
    path('markets/<str:external_id>/trades/', MarketDetailView.as_view(), name='market-trades'),
    path('markets/<str:external_id>/price-history/', MarketDetailView.as_view(), name='market-price-history'),
    path('markets/<str:external_id>/positions/', MarketDetailView.as_view(), name='market-positions'),
    path('markets/search/', MarketListView.as_view(), name='market-search'),
    path('<int:market_id>/chat/', LegacyMarketChatView.as_view(), name='market-chat'),
    path('<int:market_id>/details/', LegacyMarketDetailsView.as_view(), name='market-details'),
    path('<int:market_id>/available-shares/', MarketAvailabilityView.as_view(), name='market-available-shares'),
    path('<int:market_id>/add-liquidity/', LiquidityCompatibilityView.as_view(), name='market-add-liquidity'),
    path('liquidity/positions/', LiquidityCompatibilityView.as_view(), name='liquidity-positions'),
    path('liquidity/analytics/', LiquidityCompatibilityView.as_view(), name='liquidity-analytics'),
    path('liquidity/fee-analytics/', LiquidityCompatibilityView.as_view(), name='liquidity-fee-analytics'),
    path('liquidity/pool-stats/', LiquidityCompatibilityView.as_view(), name='liquidity-pool-stats'),
    path('liquidity/risk-score/', LiquidityCompatibilityView.as_view(), name='liquidity-risk-score'),
    path('liquidity/deposit/', LiquidityCompatibilityView.as_view(), name='liquidity-deposit'),
    path('liquidity/withdraw/', LiquidityCompatibilityView.as_view(), name='liquidity-withdraw'),
    path('liquidity/claim-fees/', LiquidityCompatibilityView.as_view(), name='liquidity-claim-fees'),
    path('<int:market_id>/bet/', LegacyBetView.as_view(), name='market-bet'),
    path('legacy/', include('brokerage.api.legacy_urls')),
]
