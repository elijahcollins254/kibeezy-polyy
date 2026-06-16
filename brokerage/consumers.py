import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async

logger = logging.getLogger(__name__)


class MarketConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for real-time market data updates.
    
    Clients connect to: ws://domain/ws/markets/{market_id}/
    
    Receives:
    - Orderbook updates (bids/asks)
    - Trade updates (price, volume)
    - Market status changes
    
    Broadcasts market events from Polymarket WebSocket streamer.
    """
    
    async def connect(self):
        self.market_id = self.scope['url_route']['kwargs'].get('market_id')
        self.user = self.scope.get('user')
        self.group_name = f'market_{self.market_id}'
        
        # Validate market exists (optional, for security)
        if self.market_id:
            market_exists = await self._check_market_exists()
            if not market_exists:
                await self.close(code=4004)  # Custom close code: market not found
                return
        
        # Add to market group for broadcasting
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        
        # Also add to price updates group (for all market price changes)
        await self.channel_layer.group_add('market_price_updates', self.channel_name)
        
        # Accept connection
        await self.accept()
        
        logger.info(f"MarketConsumer connected to market {self.market_id}")
    
    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        await self.channel_layer.group_discard('market_price_updates', self.channel_name)
        logger.info(f"MarketConsumer disconnected from market {self.market_id}")
    
    async def receive(self, text_data=None, bytes_data=None):
        """Handle client->server messages (subscriptions, pings, etc)."""
        if text_data:
            try:
                payload = json.loads(text_data)
            except json.JSONDecodeError:
                return
            
            msg_type = payload.get('type')
            
            if msg_type == 'ping':
                # Echo pong
                await self.send_json({'type': 'pong'})
            
            elif msg_type == 'subscribe_tokens':
                # Client requests subscription to specific tokens
                token_ids = payload.get('token_ids', [])
                for token_id in token_ids:
                    await self.channel_layer.group_add(
                        f'market_updates_{token_id}',
                        self.channel_name
                    )
                await self.send_json({
                    'type': 'subscribed',
                    'token_ids': token_ids
                })
            
            elif msg_type == 'get_market_data':
                # Client requests current market snapshot
                data = await self._get_market_snapshot()
                await self.send_json({
                    'type': 'market_snapshot',
                    'data': data
                })
    
    async def market_event(self, event):
        """Broadcast market events from streamer."""
        # event structure: {'type': 'market_event', 'event': {...}}
        market_data = event.get('event', {})
        
        # Enrich with market metadata if needed
        await self.send(text_data=json.dumps(market_data))
    
    async def order_event(self, event):
        """Broadcast order updates (if subscribed)."""
        # Only send to authenticated users
        if self.user and self.user.is_authenticated:
            await self.send(text_data=json.dumps(event.get('event', {})))
    
    async def market_status_update(self, event):
        """Broadcast market status changes (resolution, settlement, etc)."""
        await self.send(text_data=json.dumps(event.get('event', {})))
    
    @sync_to_async
    def _check_market_exists(self) -> bool:
        """Check if market exists in database."""
        from brokerage.models import Market
        try:
            Market.objects.get(id=self.market_id)
            return True
        except Market.DoesNotExist:
            return False
    
    @sync_to_async
    def _get_market_snapshot(self) -> dict:
        """Return current market snapshot with recent trades."""
        from brokerage.models import Market, Trade
        from django.core.serializers import serialize
        
        try:
            market = Market.objects.get(id=self.market_id)
            
            # Get recent trades
            recent_trades = Trade.objects.filter(
                market=market
            ).order_by('-created_at')[:50]
            
            return {
                'market_id': market.id,
                'title': market.title,
                'status': market.polymarket_status or 'OPEN',
                'yes_token_id': market.yes_token_id,
                'no_token_id': market.no_token_id,
                'resolution_price': str(market.resolution_price) if market.resolution_price else None,
                'recent_trades': [
                    {
                        'price': str(t.price),
                        'size': str(t.size),
                        'side': t.side,
                        'timestamp': t.created_at.isoformat(),
                    }
                    for t in recent_trades
                ]
            }
        except Market.DoesNotExist:
            return {}
