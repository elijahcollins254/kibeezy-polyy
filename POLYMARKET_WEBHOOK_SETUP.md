# Polymarket Webhook Setup Guide

This guide explains how to configure Polymarket webhooks to synchronize fill notifications with your local Position model.

## Overview

When users place **limit orders** on Polymarket, the orders may not fill immediately. This system uses webhooks to receive fill notifications from Polymarket and automatically update the user's local portfolio positions.

### What Happens

1. **User places limit order** → Local Order created (status: PENDING)
2. **Polymarket fills the order** → Sends webhook notification
3. **Webhook endpoint receives fill** → Creates Fill records
4. **Position updated** → User sees fill reflected in portfolio immediately

## Webhook Endpoint

**URL:** `https://your-domain.com/api/brokerage/webhooks/polymarket-fills/`

**Method:** POST

**Authentication:** None required (Webhook are typically unauthenticated)

## Payload Format

Polymarket sends JSON with this structure:

```json
{
  "event_type": "FILL",
  "order_id": "0x1234...abcd",
  "market_id": "0xmkt123...",
  "token_id": "61919",
  "fills": [
    {
      "id": "0xfill123...",
      "size": 10.5,
      "price": 0.65,
      "timestamp": 1686234567
    }
  ],
  "user_address": "0x7890...def0"
}
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| `event_type` | string | Event type: `FILL`, `ORDER_FILLED`, etc. |
| `order_id` | string | **Required.** Polymarket order ID (matches our `external_order_id`) |
| `fills` | array | **Required.** Array of fill objects |
| `fills[].id` | string | Unique fill ID for idempotency |
| `fills[].size` | number | Number of shares filled |
| `fills[].price` | number | Fill price (0-1 for YES/NO shares) |
| `fills[].timestamp` | integer | Unix timestamp of fill |
| `market_id` | string | Polymarket market ID (optional) |
| `token_id` | string | Polymarket token ID (optional) |
| `user_address` | string | User's Polymarket wallet address (optional) |

## Setup Steps

### 1. Configure Webhook in Polymarket CLOB

Contact Polymarket support or access your CLOB settings to register the webhook URL:

```
https://your-domain.com/api/brokerage/webhooks/polymarket-fills/
```

### 2. Test Webhook Locally (Development)

Use a webhook tunnel service like **ngrok**:

```bash
# Terminal 1: Start ngrok
ngrok http 8000

# This creates a public URL like: https://abc123.ngrok.io

# Terminal 2: Update your hosts or settings to point to ngrok URL
# Then register in Polymarket settings:
# https://abc123.ngrok.io/api/brokerage/webhooks/polymarket-fills/
```

### 3. Test with Sample Payload

```bash
curl -X POST https://your-domain.com/api/brokerage/webhooks/polymarket-fills/ \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "FILL",
    "order_id": "0x1234567890abcdef",
    "fills": [
      {
        "id": "0xfill001",
        "size": 5.0,
        "price": 0.65
      }
    ]
  }'
```

Expected response:
```json
{
  "success": true,
  "order_id": 123,
  "status": "FILLED",
  "fills_processed": 1,
  "total_filled": 5.0
}
```

## How the System Works

### Idempotent Processing

The webhook handler checks if a Fill already exists using the `external_fill_id` before creating duplicates. This prevents duplicate positions if the webhook is delivered multiple times.

```python
# Check if fill already exists
fill_exists = Fill.objects.filter(
    order=order,
    external_fill_id=fill_id
).exists()

if not fill_exists:
    # Create new Fill record
    fill = Fill.objects.create(...)
```

### Position Updates

After processing fills, the system:

1. **Calculates total filled**: Sums all Fill amounts
2. **Updates Order status**:
   - `FILLED` if total_filled ≥ order.size
   - `OPEN` if 0 < total_filled < order.size
3. **Updates Position** with weighted average:
   ```
   new_qty = old_qty + filled_size
   new_avg_price = (old_qty × old_avg_price + filled_size × fill_price) / new_qty
   ```

### Data Flow

```
┌─────────────────────┐
│  Polymarket CLOB    │
│  Order Fills        │
└──────────┬──────────┘
           │
           │ POST webhook
           ▼
┌─────────────────────┐
│  Webhook Endpoint   │
│ (/api/brokerage/    │
│  webhooks/pm-fill/) │
└──────────┬──────────┘
           │
           │ Find Order by external_id
           │ Create Fill records
           ▼
┌──────────────────────┐
│  brokerage.Fill     │
│  (execution data)    │
└──────────┬───────────┘
           │
           │ Calculate position update
           ▼
┌──────────────────────┐
│ brokerage.Position   │
│ (user's holdings)    │
└──────────────────────┘
```

## Logging

All webhook processing is logged with:
- Webhook receipt and validation
- Order lookup results
- Fill creation (or duplicate detection)
- Position updates
- Any errors

Check logs with:
```bash
tail -f logs/django.log | grep "Webhook\|Polymarket\|Fill"
```

## Troubleshooting

### Webhook Not Received

1. **Check DNS/URL**: Verify the endpoint is publicly accessible
   ```bash
   curl -v https://your-domain.com/api/brokerage/webhooks/polymarket-fills/
   ```

2. **Check firewall**: Ensure Polymarket's IP ranges are allowed (get from Polymarket docs)

3. **Check logs**: Look for incoming POST requests
   ```bash
   grep "PolymarketFillWebhookView" logs/django.log
   ```

### Order Not Found

If webhook returns `404 Order not found`:

1. Verify the `order_id` in webhook matches our `Order.external_order_id`
2. Check if the Order record was created when the user placed the order
3. Look at Order creation logs:
   ```bash
   grep "Created local Order record" logs/django.log
   ```

### Fills Not Created

1. Check if Fill already exists (idempotent - this is normal on retry):
   ```bash
   python manage.py shell
   >>> from brokerage.models import Fill, Order
   >>> o = Order.objects.get(id=123)
   >>> o.fills.all()
   ```

2. Verify fill size and price are valid numbers

## API Response Examples

### Success (All Filled)

```json
{
  "success": true,
  "order_id": 42,
  "status": "FILLED",
  "fills_processed": 1,
  "total_filled": 10.0
}
```

### Success (Partial Fill)

```json
{
  "success": true,
  "order_id": 42,
  "status": "OPEN",
  "fills_processed": 1,
  "total_filled": 5.0
}
```

### Error - Order Not Found

```json
{
  "error": "Order 0x1234... not found"
}
```
Status: 404

### Error - Invalid Payload

```json
{
  "error": "Missing order_id or fills"
}
```
Status: 400

## Production Checklist

- [ ] Webhook URL registered with Polymarket
- [ ] Endpoint is publicly accessible (test with curl)
- [ ] SSL certificate valid (HTTPS required)
- [ ] Monitoring/alerting set up for failed webhooks
- [ ] Logs are being collected and retained
- [ ] Database has backup strategy (fills are critical data)
- [ ] Load testing completed (webhook scalability)

## Future Enhancements

1. **Webhook signature verification**: Add HMAC-SHA256 signing
2. **Retry logic**: Implement exponential backoff for failed deliveries
3. **Batch processing**: Handle multiple order fills in single webhook
4. **Audit trail**: Log all webhook events for compliance
5. **Metrics**: Track fill latency, success rates, webhook delays

## Related Files

- Webhook view: [brokerage/api/views.py](brokerage/api/views.py) - `PolymarketFillWebhookView`
- URL config: [brokerage/api/urls.py](brokerage/api/urls.py)
- Position update logic: [brokerage/services/trading.py](brokerage/services/trading.py) - `_update_position_from_fills()`
- Models: [brokerage/models.py](brokerage/models.py) - Order, Fill, Position
