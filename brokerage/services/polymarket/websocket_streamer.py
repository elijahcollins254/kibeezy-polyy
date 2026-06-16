"""Real-time WebSocket streaming for Polymarket market data and order updates."""

import asyncio
import json
import logging
from typing import Optional, Dict, Any, Callable
from decimal import Decimal
import websockets
from django.conf import settings
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


class PolymarketWebSocketStreamer:
    """Connects to Polymarket WebSocket for real-time market and order updates.
    
    Supports:
    - Real-time market data (price, orderbook updates)
    - Order fill notifications
    - Position updates
    - Broadcasts updates to Django Channels consumers
    """
    
    # Polymarket WebSocket endpoints
    WS_ENDPOINTS = {
        'mainnet': 'wss://ws-subscriptions-clob.polymarket.com/ws',
        'testnet': 'wss://ws-subscriptions-clob-uat.polymarket.com/ws',
    }
    
    def __init__(
        self,
        private_key: Optional[str] = None,
        network: str = 'mainnet',
        auto_connect: bool = False,
    ):
        self.private_key = private_key or getattr(settings, 'POLY_PRIVATE_KEY', None)
        self.network = network
        self.ws_url = self.WS_ENDPOINTS.get(network, self.WS_ENDPOINTS['mainnet'])
        self.websocket = None
        self.running = False
        self.subscriptions = {}  # {subscription_id: callback}
        self.channel_layer = get_channel_layer()
        
        if auto_connect:
            asyncio.create_task(self.connect())
    
    async def connect(self):
        """Establish WebSocket connection to Polymarket."""
        try:
            self.websocket = await websockets.connect(
                self.ws_url,
                ping_interval=30,
                ping_timeout=10,
            )
            self.running = True
            logger.info(f"Connected to Polymarket WebSocket on {self.network}")
            
            # Start listening for messages
            await self._listen()
        except Exception as e:
            logger.error(f"Failed to connect to Polymarket WebSocket: {e}")
            self.running = False
            # Retry after delay
            await asyncio.sleep(5)
            await self.connect()
    
    async def disconnect(self):
        """Close WebSocket connection."""
        if self.websocket:
            await self.websocket.close()
        self.running = False
        logger.info("Disconnected from Polymarket WebSocket")
    
    async def subscribe_to_market(self, market_id: str, token_ids: list[str]):
        """Subscribe to real-time updates for a market.
        
        Args:
            market_id: Market ID to subscribe to
            token_ids: List of CLOB token IDs for the market
        """
        if not self.websocket:
            raise RuntimeError("WebSocket not connected. Call connect() first.")
        
        subscription_id = f"market_{market_id}"
        
        # Subscribe to order book updates
        for token_id in token_ids:
            msg = {
                "type": "subscribe",
                "channel": "orderbook",
                "token_id": token_id,
            }
            await self.websocket.send(json.dumps(msg))
            logger.info(f"Subscribed to orderbook for token {token_id}")
        
        # Subscribe to trade updates
        msg = {
            "type": "subscribe",
            "channel": "trades",
            "market_id": market_id,
        }
        await self.websocket.send(json.dumps(msg))
        logger.info(f"Subscribed to trades for market {market_id}")
        
        self.subscriptions[subscription_id] = {
            'market_id': market_id,
            'token_ids': token_ids,
            'callbacks': []
        }
    
    async def subscribe_to_orders(self, account_id: str):
        """Subscribe to order updates for an account.
        
        Args:
            account_id: User's Polymarket account address
        """
        if not self.websocket:
            raise RuntimeError("WebSocket not connected. Call connect() first.")
        
        subscription_id = f"orders_{account_id}"
        
        msg = {
            "type": "subscribe",
            "channel": "orders",
            "account": account_id,
        }
        await self.websocket.send(json.dumps(msg))
        logger.info(f"Subscribed to order updates for account {account_id}")
        
        self.subscriptions[subscription_id] = {
            'account_id': account_id,
            'callbacks': []
        }
    
    async def on_message(self, callback: Callable):
        """Register a callback for WebSocket messages.
        
        Callback will be called with: callback(message_type, data)
        """
        # Store callback for later use
        pass
    
    async def _listen(self):
        """Listen for WebSocket messages and dispatch to handlers."""
        try:
            async for message in self.websocket:
                try:
                    data = json.loads(message)
                    await self._handle_message(data)
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON received: {message}")
                except Exception as e:
                    logger.error(f"Error handling WebSocket message: {e}")
        except Exception as e:
            logger.error(f"WebSocket listener error: {e}")
            self.running = False
            if not self._should_exit:
                await asyncio.sleep(5)
                await self.connect()
    
    async def _handle_message(self, data: Dict[str, Any]):
        """Process WebSocket messages from Polymarket."""
        msg_type = data.get('type')
        
        if msg_type == 'orderbook':
            await self._handle_orderbook_update(data)
        elif msg_type == 'trade':
            await self._handle_trade_update(data)
        elif msg_type == 'order':
            await self._handle_order_update(data)
        elif msg_type == 'fill':
            await self._handle_fill_update(data)
        elif msg_type == 'subscription_confirmed':
            logger.info(f"Subscription confirmed: {data.get('channel')}")
        else:
            logger.debug(f"Unhandled message type: {msg_type}")
    
    async def _handle_orderbook_update(self, data: Dict[str, Any]):
        """Handle orderbook updates and broadcast to market consumers."""
        token_id = data.get('token_id')
        
        if not token_id:
            return
        
        # Broadcast to market consumer via Channels
        await self.channel_layer.group_send(
            f'market_updates_{token_id}',
            {
                'type': 'market_event',
                'event': {
                    'type': 'orderbook_update',
                    'token_id': token_id,
                    'bids': data.get('bids', []),
                    'asks': data.get('asks', []),
                    'timestamp': data.get('timestamp'),
                }
            }
        )
        logger.debug(f"Broadcasted orderbook update for token {token_id}")
    
    async def _handle_trade_update(self, data: Dict[str, Any]):
        """Handle trade updates and broadcast to market consumers."""
        market_id = data.get('market_id')
        token_id = data.get('token_id')
        
        if not market_id or not token_id:
            return
        
        # Broadcast trade to market consumers
        await self.channel_layer.group_send(
            f'market_{market_id}',
            {
                'type': 'market_event',
                'event': {
                    'type': 'trade',
                    'market_id': market_id,
                    'token_id': token_id,
                    'price': data.get('price'),
                    'amount': data.get('amount'),
                    'side': data.get('side'),
                    'timestamp': data.get('timestamp'),
                }
            }
        )
        logger.debug(f"Broadcasted trade for market {market_id}")
    
    async def _handle_order_update(self, data: Dict[str, Any]):
        """Handle order status updates."""
        order_id = data.get('order_id')
        status = data.get('status')
        
        logger.info(f"Order {order_id} status: {status}")
        
        # Broadcast to user's order consumer if applicable
        user_id = data.get('user_id')
        if user_id:
            await self.channel_layer.group_send(
                f'user_orders_{user_id}',
                {
                    'type': 'order_event',
                    'event': {
                        'type': 'order_status',
                        'order_id': order_id,
                        'status': status,
                        'timestamp': data.get('timestamp'),
                    }
                }
            )
    
    async def _handle_fill_update(self, data: Dict[str, Any]):
        """Handle order fill updates and trigger settlement logic.
        
        This is critical for position tracking and settlement.
        """
        from brokerage.models import Order, Fill
        from brokerage.services.trading import TradingService
        from django.db import transaction
        
        external_order_id = data.get('order_id')
        external_fill_id = data.get('fill_id')
        filled_amount = Decimal(str(data.get('amount', 0)))
        fill_price = Decimal(str(data.get('price', 0)))
        
        if not external_order_id:
            logger.warning("Fill update missing order_id")
            return
        
        try:
            with transaction.atomic():
                # Find local order
                order = Order.objects.filter(
                    external_order_id=external_order_id
                ).first()
                
                if not order:
                    logger.warning(f"Order {external_order_id} not found in database")
                    return
                
                # Check if fill already exists (idempotent)
                if external_fill_id and Fill.objects.filter(
                    external_fill_id=external_fill_id
                ).exists():
                    logger.info(f"Fill {external_fill_id} already processed")
                    return
                
                # Create Fill record
                fill = Fill.objects.create(
                    order=order,
                    external_fill_id=external_fill_id or f"{external_order_id}_fill",
                    filled_size=filled_amount,
                    fill_price=fill_price,
                    status='FILLED',
                )
                
                # Update position via TradingService
                trading_service = TradingService()
                trading_service._update_position_from_fills(order)
                
                # Update order status if fully filled
                order.status = 'FILLED' if filled_amount >= order.size else 'PARTIALLY_FILLED'
                order.save()
                
                logger.info(f"Processed fill {fill.id} for order {order.id}")
                
                # Broadcast fill event
                await self.channel_layer.group_send(
                    f'user_orders_{order.user.id}',
                    {
                        'type': 'order_event',
                        'event': {
                            'type': 'fill',
                            'order_id': order.id,
                            'external_order_id': external_order_id,
                            'filled_size': str(filled_amount),
                            'fill_price': str(fill_price),
                            'timestamp': data.get('timestamp'),
                        }
                    }
                )
        
        except Exception as e:
            logger.error(f"Error processing fill {external_fill_id}: {e}")
    
    async def run(self):
        """Run the WebSocket streamer (blocking)."""
        self._should_exit = False
        try:
            await self.connect()
        finally:
            await self.disconnect()


# Global instance for background streaming
_streamer_instance: Optional[PolymarketWebSocketStreamer] = None


async def get_streamer() -> PolymarketWebSocketStreamer:
    """Get or create the global WebSocket streamer instance."""
    global _streamer_instance
    if _streamer_instance is None:
        _streamer_instance = PolymarketWebSocketStreamer()
    return _streamer_instance


async def start_streaming(network: str = 'mainnet'):
    """Start the WebSocket streamer as a background task."""
    global _streamer_instance
    _streamer_instance = PolymarketWebSocketStreamer(network=network)
    asyncio.create_task(_streamer_instance.run())
    return _streamer_instance
