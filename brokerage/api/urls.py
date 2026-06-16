from django.urls import path
from .views import PlaceOrderView, PolymarketFillWebhookView, PolymarketResolutionWebhookView
from .market_views import MarketListView, MarketDetailView

urlpatterns = [
    path('orders/place/', PlaceOrderView.as_view(), name='place-order'),
    path('webhooks/polymarket-fills/', PolymarketFillWebhookView.as_view(), name='polymarket-fill-webhook'),
    path('webhooks/polymarket-resolution/', PolymarketResolutionWebhookView.as_view(), name='polymarket-resolution-webhook'),
    path('markets/', MarketListView.as_view(), name='market-list'),
    path('markets/<str:external_id>/', MarketDetailView.as_view(), name='market-detail'),
    path('markets/<str:external_id>/trades/', MarketDetailView.as_view(), name='market-trades'),
    path('markets/<str:external_id>/positions/', MarketDetailView.as_view(), name='market-positions'),
    path('markets/search/', MarketListView.as_view(), name='market-search'),
]
