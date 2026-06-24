from django.urls import re_path
from .websocket.consumers import MarketConsumer

websocket_urlpatterns = [
    re_path(r'ws/market/(?P<market_id>[^/]+)/$', MarketConsumer.as_asgi()),
]
