# Polymarket WebSocket Streaming Integration

## Overview

This implementation adds **real-time WebSocket streaming** from Polymarket for:
- ✅ **Market data** (orderbook, trades, price updates)
- ✅ **Order fills** (immediate position updates)
- ✅ **Market resolutions** (triggering settlement)

All updates are broadcast to connected clients via Django Channels and integrated with your settlement system.

---

## Architecture

### Components

```
┌─────────────────────────────────────────────────────┐
│                 Polymarket WebSocket                │
│         (Real-time market data & order updates)     │
└──────────────────┬──────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────┐
│        PolymarketWebSocketStreamer                  │
│   (brokerage/services/polymarket/websocket_streamer)│
│  - Connects to Polymarket WS                        │
│  - Handles fills, trades, orderbook updates         │
│  - Processes settlement triggers                    │
└──────────────────┬──────────────────────────────────┘
                   │
┌──────────────────▼──────────────────────────────────┐
│      Django Channels Layer (Redis)                  │
│  - Broadcasts market events to consumers             │
│  - Routes order updates to users                     │
└──────────────────┬──────────────────────────────────┘
                   │
        ┌──────────┴──────────┬──────────────┐
        │                     │              │
┌───────▼────────┐  ┌────────▼────────┐  ┌──▼─────────────┐
│  MarketConsumer│  │  User Consumer  │  │Settlement Tasks│
│  (Web clients) │  │  (Order updates)│  │ (Celery Tasks) │
└────────────────┘  └─────────────────┘  └────────────────┘
```

### Key Files

| File | Purpose |
|------|---------|
| `websocket_streamer.py` | Core WebSocket client that connects to Polymarket |
| `consumers.py` | Django Channels consumer for broadcasting updates to web clients |
| `stream_polymarket.py` | Management command to run streamer as background process |
| `tasks.py` | Celery task to start WebSocket in worker process |

---

## Setup & Configuration

### 1. Ensure Dependencies Are Installed

```bash
pip install -r requirements.txt
# Key packages: channels>=4.1.0, websockets>=11.0.0, channels-redis>=4.0.0
```

### 2. Redis Configuration

WebSocket relies on Redis for Channels:

```bash
# Start Redis
redis-server
```

Verify in `settings.py`:
```python
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [('127.0.0.1', 6379)],  # or from env
        },
    }
}
```

### 3. ASGI Configuration

Ensure `asgi.py` is configured for Channels:

```python
# api/asgi.py
import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from brokerage.routing import websocket_urlpatterns

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'api.settings')

application = ProtocolTypeRouter({
    'http': get_asgi_application(),
    'websocket': AuthMiddlewareStack(
        URLRouter(websocket_urlpatterns)
    ),
})
```

---

## Usage

### Option 1: Management Command (Recommended for Development)

```bash
# Start WebSocket streamer
python manage.py stream_polymarket --network mainnet

# Subscribe to specific markets
python manage.py stream_polymarket \
    --network mainnet \
    --market-ids market-id-1 market-id-2 \
    --account 0x1234...  # Your wallet address
```

### Option 2: Celery Task (Recommended for Production)

```python
# In Django shell or views
from brokerage.tasks import start_polymarket_websocket_stream

# Start streaming in background worker
start_polymarket_websocket_stream.delay(network='mainnet')
```

Or configure in Celery Beat schedule:

```python
# api/settings.py
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    'start-polymarket-websocket': {
        'task': 'brokerage.tasks.start_polymarket_websocket_stream',
        'schedule': crontab(minute=0, hour=0),  # Start daily at midnight
        'kwargs': {'network': 'mainnet'},
    },
}
```

### Option 3: Run with Daphne (Django Channels ASGI Server)

```bash
# Install daphne
pip install daphne

# Run ASGI server with auto-reload
daphne -b 0.0.0.0 -p 8000 api.asgi:application

# In another terminal, start streamer
python manage.py stream_polymarket --network mainnet
```

---

## Client-Side Integration

### Connect to Market Stream

```javascript
// Connect to real-time market updates
const ws = new WebSocket('ws://localhost:8000/ws/markets/market-id/');

ws.onopen = () => {
    console.log('Connected to market stream');
    
    // Request current market snapshot
    ws.send(JSON.stringify({
        type: 'get_market_data'
    }));
    
    // Subscribe to specific tokens
    ws.send(JSON.stringify({
        type: 'subscribe_tokens',
        token_ids: ['token-id-1', 'token-id-2']
    }));
};

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    
    switch(data.type) {
        case 'market_snapshot':
            console.log('Current market data:', data.data);
            break;
            
        case 'orderbook_update':
            // Update orderbook in UI
            console.log('Bids:', data.bids);
            console.log('Asks:', data.asks);
            break;
            
        case 'trade':
            // New trade occurred
            console.log(`${data.side} ${data.amount} @ ${data.price}`);
            break;
            
        case 'fill':
            // Your order was filled
            console.log('Order filled:', data);
            break;
    }
};

// Keep connection alive
setInterval(() => {
    ws.send(JSON.stringify({ type: 'ping' }));
}, 30000);
```

### Real-Time Price Feed

```javascript
// Display live price from latest trade
let lastPrice = null;

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    
    if (data.type === 'trade') {
        lastPrice = data.price;
        document.getElementById('price').innerText = 
            (lastPrice * 100).toFixed(2) + ' KES';
    }
};
```

---

## How It Works

### Flow: Order Placement → Fill → Settlement

```
1. User places market order
   ↓
2. Order sent to Polymarket API
   ↓
3. Polymarket WebSocket sends FILL event
   ↓
4. PolymarketWebSocketStreamer receives fill
   ↓
5. Creates Fill record + updates Position
   ↓
6. Broadcasts to user via Channels
   ↓
7. User sees filled position in real-time
```

### Fill Processing (Idempotent)

```python
# When fill webhook is received:
async def _handle_fill_update(data):
    external_order_id = data['order_id']
    external_fill_id = data['fill_id']
    
    # Check if already processed (idempotent)
    if Fill.objects.filter(external_fill_id=external_fill_id).exists():
        logger.info(f"Fill {external_fill_id} already processed")
        return
    
    # Create Fill record
    fill = Fill.objects.create(
        order=order,
        external_fill_id=external_fill_id,
        filled_size=data['amount'],
        fill_price=data['price'],
    )
    
    # Update Position
    trading_service._update_position_from_fills(order)
    
    # Broadcast to user
    await channel_layer.group_send(
        f'user_orders_{order.user.id}',
        {'type': 'order_event', 'event': {...}}
    )
```

### Market Resolution

```
1. Market resolves on Polymarket
   ↓
2. WebSocket sends resolution event
   ↓
3. PolymarketWebSocketStreamer updates market
   ↓
4. Triggers settle_polymarket_market.delay()
   ↓
5. Settlement task calculates payouts
   ↓
6. Payouts queued for M-Pesa distribution
   ↓
7. Users receive winnings
```

---

## Monitoring & Debugging

### Check Streamer Status

```bash
# Check if WebSocket is running
ps aux | grep stream_polymarket

# View logs
tail -f logs/django.log | grep WebSocket
```

### Test WebSocket Connection

```bash
# Using websocket-client library
pip install websocket-client

python -c "
from websocket import create_connection
import json

ws = create_connection('wss://ws-subscriptions-clob.polymarket.com/ws')
print('Connected to Polymarket!')

# Subscribe to sample market
msg = {
    'type': 'subscribe',
    'channel': 'trades',
    'market_id': 'sample-market-id'
}
ws.send(json.dumps(msg))

# Receive updates
for _ in range(5):
    print(ws.recv())

ws.close()
"
```

### Monitor Redis Channels

```bash
# Watch channel messages
redis-cli
> SUBSCRIBE market_*

# Or use management command
python manage.py shell
>>> from channels.layers import get_channel_layer
>>> channel_layer = get_channel_layer()
>>> # Check active channels
```

---

## Performance & Scalability

### Connection Limits

- **Per server**: Theoretically unlimited (tested up to 1000s of concurrent)
- **Per Polymarket API**: Rate limits apply (check documentation)
- **Redis**: Ensure sufficient memory for channel messages

### Optimization Tips

1. **Use connection pooling**: Redis already configured
2. **Filter subscriptions**: Only subscribe to active markets
3. **Batch market updates**: Group similar updates
4. **Monitor memory**: Check Redis memory usage
   ```bash
   redis-cli INFO memory
   ```

### Scaling Horizontally

For multiple servers:

```python
# All servers share Redis for Channels
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': ['redis://shared-redis-server:6379/'],
        },
    }
}

# Run streamer on dedicated worker machine
python manage.py stream_polymarket --network mainnet
```

---

## Troubleshooting

### Issue: WebSocket Connection Refused

```
Error: Cannot connect to Polymarket WebSocket
```

**Solution:**
- Check network connectivity: `ping ws-subscriptions-clob.polymarket.com`
- Verify firewall allows outbound WebSocket connections
- Check if Polymarket service is online

### Issue: Fills Not Appearing in Real-Time

```
Orders show on Polymarket but not updating locally
```

**Solution:**
1. Verify streamer is running: `ps aux | grep stream_polymarket`
2. Check Redis connection: `redis-cli ping` (should return PONG)
3. Check logs for errors: `tail -f logs/django.log`
4. Verify fill webhook also works as backup

### Issue: Memory Leak in Streamer

```
Process grows unbounded over time
```

**Solution:**
- Restart streamer periodically
- Monitor subscriptions: `len(streamer.subscriptions)`
- Check for unhandled exceptions in event handlers
- Update websockets library: `pip install --upgrade websockets`

---

## Integration with Settlement System

The WebSocket streamer **automatically integrates** with your settlement system:

### 1. Fill Processing → Position Update
```python
# Fills are processed immediately when received
await _handle_fill_update(data)
→ Create Fill record
→ Update Position with weighted average price
→ Broadcast to user
```

### 2. Resolution → Settlement Trigger
```python
# Market resolution immediately triggers settlement
market.polymarket_status = 'RESOLVED'
market.resolution_outcome = data['outcome']
market.save()
→ settle_polymarket_market.delay(market_id)
```

### 3. Settlement → Payout Distribution
```python
# Settlement creates ledger transactions
PolymarketSettlementService.settle_market(market)
→ Calculate P&L for each order
→ Create payout transactions
→ Queue M-Pesa B2C calls
```

---

## API Reference

### PolymarketWebSocketStreamer

#### `connect()`
Establish connection to Polymarket WebSocket.

```python
streamer = PolymarketWebSocketStreamer(network='mainnet')
await streamer.connect()
```

#### `subscribe_to_market(market_id, token_ids)`
Subscribe to market updates.

```python
await streamer.subscribe_to_market(
    market_id='market-123',
    token_ids=['token-abc', 'token-xyz']
)
```

#### `subscribe_to_orders(account_id)`
Subscribe to order updates for a user.

```python
await streamer.subscribe_to_orders(
    account_id='0x1234567890abcdef...'
)
```

#### `disconnect()`
Close connection.

```python
await streamer.disconnect()
```

### Django Channels Messages

#### `market_event`
Broadcast to market group.

```python
await channel_layer.group_send(
    f'market_{market_id}',
    {
        'type': 'market_event',
        'event': {
            'type': 'orderbook_update',
            'bids': [...],
            'asks': [...]
        }
    }
)
```

#### `order_event`
Broadcast to user's orders.

```python
await channel_layer.group_send(
    f'user_orders_{user_id}',
    {
        'type': 'order_event',
        'event': {
            'type': 'fill',
            'order_id': order_id,
            'filled_size': '100',
            'fill_price': '0.75'
        }
    }
)
```

---

## Next Steps

1. **Test with sample market**: Place order → confirm fills appear in real-time
2. **Monitor settlement**: Verify resolved markets trigger settlement automatically
3. **Scale to production**: Configure for multiple markets and high volume
4. **Add UI features**:
   - Live price charts
   - Real-time order book
   - Position updates
   - Trade history

---

## References

- [Polymarket CLOB API Docs](https://clob.polymarket.com/docs)
- [Django Channels](https://channels.readthedocs.io/)
- [websockets Library](https://websockets.readthedocs.io/)
- [py-clob-client-v2](https://github.com/polymarket/py-clob-client-v2)
