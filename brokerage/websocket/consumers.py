import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.core.cache import cache

logger = logging.getLogger(__name__)


class MarketConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time market price updates.
    
    Usage:
        ws://localhost/ws/market/558943/
        
    Broadcasts price updates to connected clients for a market.
    """

    async def connect(self):
        self.market_id = self.scope['url_route']['kwargs']['market_id']
        self.market_group_name = f'market_{self.market_id}'

        # Join market group
        await self.channel_layer.group_add(self.market_group_name, self.channel_name)
        await self.accept()
        
        logger.info(f"[WebSocket] Client connected to market {self.market_id}")

    async def disconnect(self, close_code):
        # Leave market group
        await self.channel_layer.group_discard(self.market_group_name, self.channel_name)
        logger.info(f"[WebSocket] Client disconnected from market {self.market_id}, code: {close_code}")

    async def receive(self, text_data):
        """Handle incoming messages (e.g., subscribe to specific token)."""
        try:
            data = json.loads(text_data)
            message_type = data.get('type')

            if message_type == 'subscribe':
                token_id = data.get('token_id')
                outcome = data.get('outcome', 'Yes')
                logger.info(f"[WebSocket] Client subscribed to token {token_id} ({outcome})")
                
                await self.send(json.dumps({
                    'type': 'connection',
                    'status': 'subscribed',
                    'token_id': token_id,
                    'outcome': outcome,
                }))
        except json.JSONDecodeError:
            await self.send(json.dumps({
                'type': 'error',
                'error': 'Invalid JSON',
            }))

    async def price_update(self, event):
        """
        Receive price update from group and send to WebSocket.
        Called by broadcast_price_update().
        """
        await self.send(json.dumps({
            'type': 'price_update',
            'data': event['price_update'],
        }))

    async def market_update(self, event):
        """
        Receive market update (yes_probability, volume, etc).
        Called by broadcast_market_update().
        """
        await self.send(json.dumps({
            'type': 'market_update',
            'data': event['market_update'],
        }))


async def broadcast_price_update(market_id, token_id, outcome, price, timestamp):
    """
    Broadcast a price update to all connected clients for a market.
    
    Usage in views:
        from asgiref.sync import async_to_sync
        async_to_sync(broadcast_price_update)(market_id, token_id, 'Yes', 0.45, time.time())
    """
    from channels.layers import get_channel_layer
    
    channel_layer = get_channel_layer()
    market_group_name = f'market_{market_id}'
    
    await channel_layer.group_send(
        market_group_name,
        {
            'type': 'price_update',
            'price_update': {
                'market_id': str(market_id),
                'token_id': token_id,
                'outcome': outcome,
                'price': price,
                'timestamp': int(timestamp * 1000),  # Convert to milliseconds
            },
        },
    )


async def broadcast_market_update(market_id, market_data):
    """
    Broadcast market-wide update (yes_probability, volume, etc).
    
    Usage in views:
        from asgiref.sync import async_to_sync
        async_to_sync(broadcast_market_update)(market_id, {
            'yes_probability': 55,
            'volume': '150,000 KES',
        })
    """
    from channels.layers import get_channel_layer
    
    channel_layer = get_channel_layer()
    market_group_name = f'market_{market_id}'
    
    await channel_layer.group_send(
        market_group_name,
        {
            'type': 'market_update',
            'market_update': {
                'market_id': str(market_id),
                **market_data,
            },
        },
    )
