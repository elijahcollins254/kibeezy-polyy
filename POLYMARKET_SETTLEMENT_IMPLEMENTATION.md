# Polymarket Settlement System - Implementation Complete

This document describes the complete settlement system for Polymarket orders that has been implemented.

## Overview

When a Polymarket market resolves, users' positions are automatically settled, payouts calculated, and winnings distributed to user accounts.

## Components Implemented

### 1. ✅ Database Schema (Models & Migration)

**Added to `brokerage.models.Market`:**
```python
polymarket_status = 'OPEN' | 'CLOSED' | 'RESOLVED' | 'INVALID'
resolution_outcome = 'Yes' | 'No' | 'INVALID'
resolution_price = Decimal(0-1)  # Final market price
resolved_at = DateTime  # When market resolved
settlement_status = 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED'
settlement_started_at = DateTime
settlement_completed_at = DateTime
```

**Added to `brokerage.models.Order`:**
```python
payout = Decimal  # Amount user receives
settlement_result = 'PENDING' | 'WON' | 'LOST'
settled_at = DateTime
```

**Migration**: [brokerage/migrations/0002_polymarket_settlement.py](brokerage/migrations/0002_polymarket_settlement.py)

### 2. ✅ Settlement Service

**File**: [brokerage/services/settlement.py](brokerage/services/settlement.py)

**Class**: `PolymarketSettlementService`

**Methods**:
- `calculate_payout()` - Calculates P&L for a single order
  - BUY side: Wins if market resolves YES
  - SELL side: Wins if market resolves NO
  - Payout = shares × resolution_price × 100 KES
  
- `settle_market()` - Settles all orders in a market
  - Validates market is resolved
  - Processes each FILLED order
  - Creates ledger transactions for winners
  - Updates order settlement status
  - Returns settlement summary

- `_create_payout_transaction()` - Creates ledger entries
  - Credits user's liability account
  - Debits settlement account
  - Creates Transaction record for M-Pesa payout

**P&L Logic**:
```python
if order.side == 'BUY':
    is_winner = (market.resolution_outcome == 'Yes')
else:  # SELL
    is_winner = (market.resolution_outcome == 'No')

if is_winner:
    payout = filled_size × resolution_price × 100  # Max value when price=1
else:
    payout = 0  # Complete loss
```

### 3. ✅ Celery Tasks

**File**: [brokerage/tasks.py](brokerage/tasks.py)

**Task**: `settle_polymarket_market(market_id)`
```python
@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def settle_polymarket_market(self, market_id: int):
    """
    Settle all user positions in a resolved market
    - Max 3 retries with 60-second backoff
    - Exponential backoff on failure (60 * 2^retries seconds)
    """
```

### 4. ✅ Management Command

**File**: [brokerage/management/commands/sync_polymarket_resolutions.py](brokerage/management/commands/sync_polymarket_resolutions.py)

**Usage**:
```bash
# Sync only unresolved markets and auto-trigger settlement
python manage.py sync_polymarket_resolutions --auto-settle

# Sync all markets with limit
python manage.py sync_polymarket_resolutions --all --limit 500

# Sync without auto-settling (manual review)
python manage.py sync_polymarket_resolutions --no-auto-settle
```

**What it does**:
1. Fetches market data from Polymarket API
2. Finds locally synced markets
3. Detects newly resolved markets
4. Updates `polymarket_status`, `resolution_outcome`, `resolved_at`
5. Optionally triggers `settle_polymarket_market` task
6. Returns summary of processed markets

### 5. ✅ Resolution Webhook

**File**: [brokerage/api/views.py](brokerage/api/views.py)

**Endpoint**: `/api/brokerage/webhooks/polymarket-resolution/`

**Method**: POST

**Payload**:
```json
{
  "event": "market_resolved",
  "market_id": "0xmkt123...",
  "outcome": "Yes",
  "resolved_at": 1686234567,
  "resolution_price": 0.75,
  "token_ids": ["61919"]
}
```

**Response**:
```json
{
  "success": true,
  "market_id": 42,
  "polymarket_id": "0xmkt123...",
  "outcome": "Yes",
  "settlement_task_id": "celery-task-uuid"
}
```

**What it does**:
1. Receives resolution event from Polymarket
2. Updates local market record with outcome
3. Immediately triggers settlement task
4. Returns task ID for tracking

---

## Settlement Flow

```
Polymarket Market Resolves
         ↓
    (Two options)
    
┌─────────────────────────────────────────┐
│ Option 1: Periodic Sync                 │
│ (Every hour via scheduled job)           │
│ $ python manage.py sync_polymarket...    │
└────────────────┬────────────────────────┘
                 │
    ┌────────────────────────────────┐
    │ Option 2: Real-time Webhook     │
    │ POST /webhooks/pm-resolution/  │
    └────────────────┬───────────────┘
                     │
              ┌──────▼──────────┐
              │ Update Market   │
              │ status=RESOLVED │
              │ outcome=Yes/No  │
              └──────┬──────────┘
                     │
              ┌──────▼──────────────────────┐
              │ settle_polymarket_market()  │
              │ (Celery Task)               │
              └──────┬─────────────────────┘
                     │
        ┌────────────┼────────────┐
        │            │            │
        ▼            ▼            ▼
    ┌────────┐  ┌──────────┐  ┌────────┐
    │ For    │  │ Calculate│  │ For    │
    │Winners │  │ Payouts  │  │Losers  │
    │        │  │          │  │        │
    │ Payout │  │ Order 1: │  │ Payout │
    │= shares│  │ $500     │  │= 0     │
    │× price │  │ Order 2: │  │        │
    │× 100   │  │ $300     │  │        │
    └────┬───┘  │ Order 3: │  └───┬────┘
         │      │ $0       │      │
         │      └──────────┘      │
         │                        │
    ┌────▼────────────────────────▼───┐
    │ Create Ledger Transactions      │
    │ (Credit user liability account) │
    └────┬─────────────────────────────┘
         │
    ┌────▼──────────────────┐
    │ Queue M-Pesa Payouts  │
    │ send_b2c_payout()     │
    └────┬───────────────────┘
         │
    ┌────▼──────────────────────┐
    │ Mark Settlement COMPLETED │
    └────────────────────────────┘
         │
    ┌────▼──────────────────────┐
    │ User Receives Winnings    │
    │ (via M-Pesa B2C)          │
    └───────────────────────────┘
```

---

## Execution Steps

### Step 1: Run Database Migration

```bash
python manage.py migrate brokerage
```

This creates the new columns:
- Market: polymarket_status, resolution_outcome, resolution_price, resolved_at, settlement_status, settlement_started_at, settlement_completed_at
- Order: payout, settlement_result, settled_at

### Step 2: Configure Scheduled Sync (Optional)

Add to Celery Beat schedule to sync resolutions hourly:

```python
# settings.py or celery config
CELERY_BEAT_SCHEDULE = {
    'sync-polymarket-resolutions': {
        'task': 'brokerage.management.commands.sync_polymarket_resolutions',
        'schedule': crontab(minute=0),  # Every hour
        'args': ('--auto-settle',),
    },
}
```

Or run manually:
```bash
python manage.py sync_polymarket_resolutions --auto-settle
```

### Step 3: Configure Resolution Webhook (Optional)

Register with Polymarket to send webhooks to:
```
https://your-domain.com/api/brokerage/webhooks/polymarket-resolution/
```

### Step 4: Test Settlement

```bash
# Simulate a resolved market (for testing)
python manage.py shell

>>> from brokerage.models import Market, Order
>>> market = Market.objects.get(id=1)
>>> market.polymarket_status = 'RESOLVED'
>>> market.resolution_outcome = 'Yes'
>>> market.resolution_price = Decimal('0.75')
>>> market.save()

# Manually trigger settlement task
>>> from brokerage.tasks import settle_polymarket_market
>>> result = settle_polymarket_market.delay(market.id)
>>> result.get()  # Wait for result
```

---

## Data Flow with Examples

### Example Scenario

**Market**: "Will Bitcoin exceed $50k by EOY?"  
**Token ID**: 61919  
**Resolves to**: YES at price 0.85  

**User A**: Bought 10 shares at 0.50 (cost: 500 KES)
- **Result**: WON
- **Payout**: 10 × 0.85 × 100 = 850 KES
- **Profit**: 850 - 500 = 350 KES ✅

**User B**: Bought 5 shares at 0.60 (cost: 300 KES)
- **Result**: WON
- **Payout**: 5 × 0.85 × 100 = 425 KES
- **Profit**: 425 - 300 = 125 KES ✅

**User C**: Sold 8 shares at 0.55 (received: 440 KES)
- **Result**: LOST
- **Payout**: 0 KES
- **Loss**: 440 KES (keeps order in system, but payout=0) ❌

**Settlement Summary**:
- Orders processed: 3
- Winners: 2
- Losers: 1
- Total payouts: 1,275 KES

---

## Monitoring & Debugging

### View Settlement Status

```bash
python manage.py shell

>>> from brokerage.models import Market, Order
>>> m = Market.objects.get(id=1)
>>> print(f"Status: {m.settlement_status}")
>>> print(f"Resolved: {m.polymarket_status}")
>>> print(f"Outcome: {m.resolution_outcome}")

# Check orders
>>> orders = m.orders.all()
>>> for o in orders:
...     print(f"Order {o.id}: {o.settlement_result} - {o.payout} KES")
```

### Check Celery Task Status

```python
from celery.result import AsyncResult

task_id = "celery-task-uuid"
result = AsyncResult(task_id)

print(f"Status: {result.status}")
print(f"Result: {result.result}")
```

### View Logs

```bash
tail -f logs/django.log | grep -i "settlement\|resolve"
```

---

## Troubleshooting

### Market not syncing from Polymarket

1. Check Polymarket API is accessible
   ```bash
   python manage.py shell
   >>> from brokerage.services.polymarket.adapter import PolymarketAdapter
   >>> adapter = PolymarketAdapter()
   >>> markets = adapter.get_markets(params={'limit': 5})
   ```

2. Check market exists locally
   ```bash
   >>> from brokerage.models import Market
   >>> m = Market.objects.filter(source='polymarket').first()
   ```

### Settlement not triggering

1. Check market is marked as RESOLVED
   ```bash
   >>> m.polymarket_status
   'RESOLVED'
   >>> m.resolution_outcome
   'Yes'
   ```

2. Manually trigger settlement
   ```bash
   >>> from brokerage.tasks import settle_polymarket_market
   >>> settle_polymarket_market(m.id)
   ```

3. Check Celery is running
   ```bash
   celery -A api worker -l info
   ```

### Payout not reaching user

1. Check settlement completed
   ```bash
   >>> m.settlement_status
   'COMPLETED'
   ```

2. Check ledger transactions created
   ```bash
   >>> from brokerage.models import Transaction
   >>> txs = Transaction.objects.filter(type='SETTLEMENT', user=user)
   >>> txs.count()
   ```

3. Check M-Pesa payout queued
   ```bash
   >>> from payments.models import Transaction as PayoutTx
   >>> payouts = PayoutTx.objects.filter(type='PAYOUT', user=user)
   ```

---

## Key Design Decisions

### 1. P&L Calculation
- **Fixed value at resolution**: Uses resolution_price (0-1) at time of resolution
- **Not average entry price**: Each order settlement is independent
- **Winner takes all**: Losers get 0 (could be modified to use partial value systems)

### 2. Ledger Integration
- **Dual-entry bookkeeping**: Debits settlement account, credits user liability
- **Creates transaction record**: For audit trail and M-Pesa payouts
- **Idempotent**: Can safely re-run settlement without duplicates

### 3. Asynchronous Processing
- **Celery task**: Non-blocking, retry-capable
- **Exponential backoff**: Handles transient failures
- **Manual option**: Can trigger with management command if needed

### 4. Webhook vs Periodic Sync
- **Webhook**: Real-time (within seconds)
- **Periodic sync**: Fallback for reliability
- **Both supported**: Use whichever fits your infrastructure

---

## Related Documentation

- [POLYMARKET_WEBHOOK_SETUP.md](POLYMARKET_WEBHOOK_SETUP.md) - Fill webhook details
- [POLYMARKET_RESOLUTION_AND_SETTLEMENT.md](POLYMARKET_RESOLUTION_AND_SETTLEMENT.md) - Architecture overview
- [POLYMARKET_ORDER_INTEGRATION.md](POLYMARKET_ORDER_INTEGRATION.md) - Order placement flow

---

## Next Steps

1. ✅ Run migration: `python manage.py migrate`
2. ✅ Test with sample market
3. ✅ Set up scheduled sync or webhook
4. ✅ Configure M-Pesa payout integration
5. ✅ Monitor first settlements
6. ⏳ Add admin dashboard for settlement tracking
7. ⏳ Create settlement reports/analytics

---

## Questions?

Refer to the implementation guide or check logs:
```bash
grep "settlement\|resolve" logs/django.log
```
