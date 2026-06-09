from django.urls import re_path
from .consumers import MarketConsumer

websocket_urlpatterns = [
    re_path(r'ws/markets/(?P<market_id>[^/]+)/$', MarketConsumer.as_asgi()),
]
