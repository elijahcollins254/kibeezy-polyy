from django.urls import path
from .consumers import MarketConsumer

websocket_urlpatterns = [
    path('ws/market/<str:market_id>/', MarketConsumer.as_asgi()),
]
