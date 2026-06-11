# Polymarket Order Integration Guide

This document describes the frontend-to-backend-to-Polymarket order flow integration.

## Architecture Overview

```
Frontend (Next.js)
    ↓ POST /api/brokerage/orders/place/
Backend (Django)
    ↓ py-clob-client-v2 SDK
Polymarket CLOB API
```

### Flow

1. **Frontend** collects user input (market, side, amount, order type)
2. **Frontend** sends to `/api/brokerage/orders/place/` with:
   - `market_id`: Polymarket external ID
   - `token_id`: Token ID from market.clobTokenIds
   - `side`: 'BUY' or 'SELL'
   - `size`: Amount (USD for market orders, shares for limit orders)
   - `price`: Price (0-1 for limit orders)
   - `order_type`: 'market' or 'limit'

3. **Backend** (`PlaceOrderView`):
   - Validates request via `PlaceOrderSerializer`
   - Calls `TradingService.place_polymarket_order()`
   - Returns order confirmation

4. **TradingService** calls appropriate adapter method:
   - Market orders: `adapter.place_market_order()`
   - Limit orders: `adapter.place_limit_order()`

5. **PolymarketAdapter** delegates to `PolymarketClobClient`

6. **PolymarketClobClient** uses `py-clob-client-v2` to:
   - Sign orders using private key
   - Derive API credentials
   - Post to Polymarket CLOB endpoint

7. **Response** returned to frontend with order confirmation

---

## Setup Instructions

### 1. Environment Variables

Add these to your `.env` file or settings:

```bash
# Polymarket Authentication
POLY_PRIVATE_KEY=0x...                          # Your Polygon private key
POLY_ADDRESS=0x...                              # Your Polygon address (funder)
POLY_SIGNATURE_TYPE=0                           # 0=EOA, 1=Email, 2=Proxy

# Polymarket Endpoints (optional, defaults provided)
POLY_CLOB_BASE_URL=https://clob.polymarket.com
POLY_DATA_BASE_URL=https://data-api.polymarket.com
POLY_GAMMA_BASE_URL=https://gamma-api.polymarket.com
```

### 2. Django Settings Configuration

Add to `settings.py`:

```python
# Polymarket Integration
POLY_PRIVATE_KEY = os.getenv('POLY_PRIVATE_KEY')
POLY_ADDRESS = os.getenv('POLY_ADDRESS')
POLY_SIGNATURE_TYPE = int(os.getenv('POLY_SIGNATURE_TYPE', 0))
POLY_CLOB_BASE_URL = os.getenv('POLY_CLOB_BASE_URL', 'https://clob.polymarket.com')
POLY_DATA_BASE_URL = os.getenv('POLY_DATA_BASE_URL', 'https://data-api.polymarket.com')
```

### 3. Install Dependencies

Already in `requirements.txt`:
```
py_clob_client_v2>=0.1.0
```

If not installed:
```bash
pip install py-clob-client-v2
```

---

## Frontend Implementation

### Market Order Example

```typescript
// User selects a market and enters KES amount
const polyPayload = {
    market_id: "0x...",           // Polymarket external_id
    token_id: "0x...",            // Token ID (e.g., YES token)
    side: "BUY",                  // or "SELL"
    size: 7.69,                   // USD amount (KES / 130)
    price: 0.45,                  // Market probability (ignored for market orders)
    order_type: "market"
};

const response = await fetch('/api/brokerage/orders/place/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(polyPayload)
});

const result = await response.json();
// result: { success: true, order_id: "0x...", ... }
```

### Limit Order Example

```typescript
const polyPayload = {
    market_id: "0x...",
    token_id: "0x...",
    side: "BUY",
    size: 10,                     // Number of shares
    price: 0.50,                  // Limit price (50%)
    order_type: "limit"
};

const response = await fetch('/api/brokerage/orders/place/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(polyPayload)
});
```

---

## Backend Implementation

### Modified Files

1. **brokerage/services/polymarket/client.py**
   - `PolymarketClobClient`: Uses `py-clob-client-v2` SDK
   - `place_market_order()`: Places fill-or-kill market orders
   - `place_limit_order()`: Places GTC limit orders
   - `get_balance()`: Fetches account balance

2. **brokerage/services/polymarket/adapter.py**
   - `place_market_order()`: Routes to CLOB client
   - `place_limit_order()`: Routes to CLOB client
   - `get_balance()`: Routes to CLOB client

3. **brokerage/services/trading.py**
   - `place_polymarket_order()`: Main entry point
   - Detects order type and calls appropriate adapter method
   - Returns order response

4. **brokerage/api/views.py** (PlaceOrderView)
   - Detects if request is for Polymarket (checks `token_id`)
   - Calls `place_polymarket_order()` or legacy method
   - Returns JSON response

5. **brokerage/api/serializers.py**
   - Added `token_id` and `order_type` fields

---

## Key Features

### Market Orders (FOK - Fill or Kill)
- Spend specified USD amount to buy shares at market price
- Executes immediately or rejects
- Good for market entries

### Limit Orders (GTC - Good Till Cancelled)
- Buy/sell specific number of shares at limit price
- Remains open until filled or manually cancelled
- Good for precise positioning

### Error Handling
- Client checks if `POLY_PRIVATE_KEY` is set
- Raises RuntimeError if CLOB client unavailable
- Backend returns 400 Bad Request with error message

### Authentication
- Uses py-clob-client-v2 L1 signing (private key)
- Automatically derives API credentials
- Sets up L2 headers for authenticated requests

---

## Testing the Integration

### 1. Check Credentials Setup
```bash
# In Django shell
from brokerage.services.polymarket.client import PolymarketClobClient
client = PolymarketClobClient()
balance = client.get_balance()
print(f"Account balance: ${balance}")
```

### 2. Test Market Order
```bash
# Make API request
curl -X POST http://localhost:8000/api/brokerage/orders/place/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "market_id": "0x...",
    "token_id": "0x...",
    "side": "BUY",
    "size": 10,
    "price": 0.5,
    "order_type": "market"
  }'
```

### 3. Test Limit Order
```bash
curl -X POST http://localhost:8000/api/brokerage/orders/place/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "market_id": "0x...",
    "token_id": "0x...",
    "side": "BUY",
    "size": 10,
    "price": 0.45,
    "order_type": "limit"
  }'
```

---

## Common Issues

### "maker address not allowed, please use the deposit wallet flow"
- Your address hasn't been registered on Polymarket
- Solution: Visit polymarket.com and complete the deposit/setup flow

### "CLOB client not initialized"
- `POLY_PRIVATE_KEY` environment variable not set
- Solution: Set the variable and restart Django

### Order fails silently
- Check Django logs for detailed error messages
- Ensure `py-clob-client-v2` is installed and up to date
- Verify your Polygon address has sufficient balance

---

## Response Format

### Success Response (201 Created)
```json
{
    "success": true,
    "order_id": "0x...",
    "type": "market",
    "side": "BUY",
    "size": 10,
    "price": 0.45,
    "token_id": "0x...",
    "response": { ... }
}
```

### Error Response (400 Bad Request)
```json
{
    "error": "maker address not allowed, please use the deposit wallet flow"
}
```

---

## Future Improvements

1. **Async Order Processing**: Use Celery to process orders asynchronously
2. **Order Tracking**: Store Polymarket orders in database for user history
3. **Position Tracking**: Sync user positions from Polymarket to local database
4. **Webhook Support**: Listen for order fill events from Polymarket
5. **Portfolio Analytics**: Calculate unrealized PnL from market prices

---

## References

- [Polymarket API Docs](https://docs.polymarket.com/)
- [py-clob-client-v2 GitHub](https://github.com/Polymarket/py-clob-client-v2)
- [CLOB API Reference](https://clob-api.polymarket.com/api/docs)
