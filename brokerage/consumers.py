import json
from channels.generic.websocket import AsyncWebsocketConsumer


class MarketConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.market_id = self.scope['url_route']['kwargs'].get('market_id')
        self.group_name = f'market_{self.market_id}'

        # Allow connection - production: validate JWT or user permissions here
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        # Client->server messages can be handled here (e.g., subscribe/unsubscribe)
        # For now, ignore or echo
        if text_data:
            try:
                payload = json.loads(text_data)
            except json.JSONDecodeError:
                return
            # Echo back pings
            if payload.get('type') == 'ping':
                await self.send_json({'type': 'pong'})

    async def market_event(self, event):
        # Event structure: {'type': 'market_event', 'event': {...}}
        await self.send(text_data=json.dumps(event.get('event', {})))
