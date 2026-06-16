# Polymarket Resolution & Settlement Guide

## Current State: A Critical Gap

Currently, **there is NO automatic settlement mechanism for Polymarket orders**. When a Polymarket market resolves, the system does not:
- Sync the resolution status from Polymarket
- Calculate winnings/losses for user positions
- Transfer funds back to user wallets
- Create payout transactions

This is a significant issue that needs to be addressed.

---

## How Local Markets Work (Reference)

For local markets created within Cache, there's a complete settlement pipeline:

### 1. Market Creation
- Admin creates market in `markets.models.Market`
- Sets question, category, end date, initial probabilities

### 2. User Places Bets
- Users place MARKET orders (fills immediately)
- Creates `markets.models.Bet` records
- Funds reserved via ledger

### 3. Market Resolution (Manual)
- Admin calls `/api/markets/admin/resolve/` endpoint
- Sets `market.resolved_outcome = "Yes"` or `"No"`
- Sets `market.status = "CLOSED"`

### 4. Settlement (Automatic via Celery)
- `settle_market.delay(market_id)` is triggered
- For each **winning bet** (outcome matches resolution):
  - Payout = shares × 100 KES (LMSR-based)
  - Creates `payments.models.Transaction` (PAYOUT type)
  - Sets `bet.result = 'WON'`, `bet.payout = amount`
  
- For each **losing bet**:
  - Sets `bet.result = 'LOST'`, `bet.payout = 0`

### 5. Payout to User (M-Pesa)
- `send_b2c_payout.delay(transaction_id)` queued
- Calls M-Pesa B2C API to transfer funds to user's phone

```
LOCAL MARKET FLOW:
┌──────────────┐     ┌──────────────┐     ┌─────────────────┐
│ Admin        │     │ User Places  │     │ Admin Resolves  │
│ Creates      │────▶│ MARKET Bets  │────▶│ Market Outcome  │
│ Market       │     │ (Immediate)  │     │                 │
└──────────────┘     └──────────────┘     └────────┬────────┘
                                                    │
                         ┌──────────────────────────┘
                         │
                         ▼
                    ┌────────────────────────┐
                    │ settle_market() Task   │
                    │ (Automatic via Celery) │
                    │ - Calculate payouts    │
                    │ - Update bet.result    │
                    │ - Create Transactions  │
                    └────────────┬───────────┘
                                 │
                         ┌───────┴────────┐
                         │                │
                    ┌────▼──────┐    ┌───▼────────┐
                    │ Winners   │    │ Losers     │
                    │ - Payout  │    │ - Payout=0 │
                    │ - M-Pesa  │    │            │
                    └───────────┘    └────────────┘
```

---

## Polymarket Orders: The Current Gap

When users trade Polymarket orders via your system:

```
USER PLACES POLYMARKET LIMIT ORDER:
┌──────────────────────┐
│ POST /orders/place/  │
│ (token_id, market_id)│
└──────────┬───────────┘
           │
           ▼
    ┌─────────────────┐
    │ Create Order    │
    │ (PENDING)       │
    │ + Fill record   │
    │ + Position      │
    │   updated       │
    └────────┬────────┘
             │
             ▼
    ┌──────────────────────────┐
    │ Place on Polymarket API  │
    │ (py-clob-client)         │
    └────────┬─────────────────┘
             │
      ┌──────┴──────┐
      │             │
   FILLED?       PENDING?
   (market order) (limit order)
      │             │
      ▼             ▼
   ┌──────────┐  ┌──────────────────┐
   │ Create   │  │ Webhook waits    │
   │ Fill     │  │ for fills from   │
   │ record   │  │ Polymarket...    │
   │ Update   │  │                  │
   │ Position │  │ [CURRENTLY BLOCKED]
   └──────────┘  │ No resolution    │
                 │ sync happening   │
                 └──────────────────┘


Polymarket Market Resolves:
┌──────────────────────────┐
│ Polymarket resolves      │ 
│ (YES/NO determined)      │
└──────────┬───────────────┘
           │
           ▼
    ❌ NO SYNC ❌
    
[MISSING: Webhook or periodic sync to fetch
resolution status from Polymarket and settle
user positions]

    ❌ NO SETTLEMENT ❌
    
[MISSING: Settlement logic to:
- Calculate P&L for user positions
- Determine winner/loser
- Create payout transactions
- Handle distribution to users]
```

---

## The Problem: Three Missing Pieces

### 1. ❌ No Resolution Sync from Polymarket
- Polymarket resolves markets regularly
- Your system does NOT fetch this resolution status
- Markets stay in `brokerage.models.Market` with outdated data
- User positions remain "open" indefinitely

**Solution Needed**: Periodic task or webhook to fetch resolved market data from Polymarket

### 2. ❌ No Settlement Logic for Polymarket Positions  
- Even if we synced the resolution, there's no code to calculate payouts
- The local `settle_market()` logic is tightly coupled to `markets.models.Market`
- Polymarket positions live in `brokerage.models.Position` (different model)
- Order/Fill data is in `brokerage.models` (different app)

**Solution Needed**: Separate settlement logic for Polymarket positions

### 3. ❌ No Payout Distribution
- No ledger entries created for settlement
- No M-Pesa payouts triggered
- User wallets not updated with winnings

**Solution Needed**: Settlement task that updates user ledger accounts and triggers payouts

---

## Architecture: Local vs Polymarket

The system has TWO separate market systems:

### Local Markets (`markets` app):
```
markets.models.Market
├─ question
├─ status (OPEN, CLOSED, RESOLVED)
├─ resolved_outcome (Yes/No)
├─ resolved_at
└─ bets → markets.models.Bet
   ├─ outcome
   ├─ result (PENDING, WON, LOST)
   ├─ payout
   └─ Settlement is fully implemented
```

### Polymarket Orders (`brokerage` app):
```
brokerage.models.Market
├─ external_id (Polymarket ID)
├─ source = 'polymarket'
├─ resolution (field exists, unused!)
├─ metadata (contains Polymarket JSON)
└─ orders → brokerage.models.Order
   ├─ external_order_id (Polymarket order ID)
   ├─ status
   └─ fills → brokerage.models.Fill
      └─ Position (updated immediately on fill)
         └─ ❌ NO settlement logic
```

**Problem**: They use different models, so settlement logic can't be shared.

---

## Recommended Implementation

### Phase 1: Sync Polymarket Market Resolution

Create a management command to periodically fetch resolved markets from Polymarket:

```python
# brokerage/management/commands/sync_polymarket_resolutions.py

class Command(BaseCommand):
    """
    Sync resolution status from Polymarket for all traded markets
    
    Usage:
        python manage.py sync_polymarket_resolutions
        
    This will:
    1. Find all brokerage.Market records with source='polymarket'
    2. Fetch market details from Polymarket API
    3. If market.status == 'RESOLVED', store outcome and trigger settlement
    """
```

**Key fields to sync**:
- `market.status` → OPEN/CLOSED/RESOLVED
- `market.resolution` → "Yes"/"No" (outcome)
- `market.metadata['resolved_at']` → timestamp

### Phase 2: Settle Polymarket Positions

Create settlement task specifically for Polymarket orders:

```python
# brokerage/services/settlement.py

def settle_polymarket_market(market_id: str):
    """
    Settle all user positions in a resolved Polymarket market
    
    For each user with positions in this market:
    1. Calculate P&L based on position:
       - If user bought YES and market resolved YES: WON
       - If user bought YES and market resolved NO: LOST
       - If user sold YES and market resolved YES: LOST
       - If user sold YES and market resolved NO: WON
    
    2. Calculate payout:
       - Winners: position.quantity × current_market_price_at_resolution
       - Losers: 0 (or minimal value in some AMM systems)
    
    3. Create ledger entries:
       - Credit user's liability account with payout
       - Debit settlement account
    
    4. Enqueue payout to user via M-Pesa
    """
```

**P&L Calculation**:
```python
# Polymarket uses continuous AMM pricing, not fixed 100 KES per share
# Price ranges 0-1 (representing probability)

if position.side == 'BUY':
    # Bought shares - win if market resolves YES
    if market.resolution == 'Yes':
        payout = position.quantity * 1.0  # Max value
    else:
        payout = 0  # Min value
else:  # SELL
    # Sold shares - win if market resolves NO
    if market.resolution == 'No':
        payout = position.quantity * 1.0
    else:
        payout = 0
```

### Phase 3: Create Resolution Webhook from Polymarket

Alternatively (or additionally), accept webhooks from Polymarket when markets resolve:

```python
# brokerage/api/views.py

class PolymarketResolutionWebhookView(APIView):
    """
    Webhook endpoint for Polymarket market resolutions
    
    POST /api/brokerage/webhooks/polymarket-resolution/
    
    Payload:
    {
        "event": "market_resolved",
        "market_id": "0xmkt123...",
        "token_ids": ["61919"],
        "outcome": "Yes",
        "resolved_at": 1234567890
    }
    """
    
    def post(self, request):
        # Find market by Polymarket ID
        market = brokerage.models.Market.objects.get(external_id=...)
        market.resolution = outcome
        market.metadata['resolved_at'] = resolved_at
        market.save()
        
        # Trigger settlement
        settle_polymarket_market.delay(market.id)
        
        return Response({'status': 'resolved'})
```

---

## Current Data Gaps

Before implementing settlement, you need to check:

### 1. Do we have Polymarket prices at resolution?
- Polymarket markets resolve to exactly 0 or 1 (or fractional)
- Need to record the FINAL price when resolution happens
- This determines payout: `payout = quantity × final_price`

**Need to add**: `resolution_price` field to `brokerage.models.Market`

### 2. Are we tracking entry prices for Polymarket orders?
- For P&L calculation: `(exit_price - entry_price) × quantity`
- Currently stored in `brokerage.models.Order.price`
- **Good**: Already captured when order is placed

### 3. Do we have enough user data for M-Pesa payouts?
- Users need phone numbers linked to accounts
- `users.models.CustomUser.phone_number` → Should exist

---

## Data Model Changes Needed

### 1. Add to `brokerage.models.Market`:
```python
class Market(models.Model):
    # ... existing fields ...
    
    # Add these fields for Polymarket resolution tracking
    polymarket_status = models.CharField(
        max_length=32,
        choices=[('OPEN', 'Open'), ('CLOSED', 'Closed'), ('RESOLVED', 'Resolved')],
        null=True,
        blank=True
    )
    resolution_outcome = models.CharField(
        max_length=10,
        choices=[('Yes', 'Yes'), ('No', 'No'), ('INVALID', 'Invalid')],
        null=True,
        blank=True
    )
    resolution_price = models.DecimalField(
        max_digits=5,
        decimal_places=8,
        null=True,
        blank=True,
        help_text="Final market price at resolution (0-1)"
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    settlement_status = models.CharField(
        max_length=32,
        choices=[('PENDING', 'Pending'), ('PROCESSING', 'Processing'), ('COMPLETED', 'Completed'), ('FAILED', 'Failed')],
        default='PENDING'
    )
```

### 2. Add to `brokerage.models.Order`:
```python
class Order(models.Model):
    # ... existing fields ...
    
    # Add these for settlement tracking
    payout = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    settlement_result = models.CharField(
        max_length=32,
        choices=[('PENDING', 'Pending'), ('WON', 'Won'), ('LOST', 'Lost')],
        default='PENDING'
    )
    settled_at = models.DateTimeField(null=True, blank=True)
```

---

## Implementation Checklist

- [ ] Add resolution fields to `brokerage.models.Market`
- [ ] Add payout fields to `brokerage.models.Order`
- [ ] Create `sync_polymarket_resolutions` management command
- [ ] Create `settle_polymarket_market()` Celery task
- [ ] Create settlement ledger logic (create transaction entries)
- [ ] Test settlement with sample Polymarket market
- [ ] Create `PolymarketResolutionWebhookView` (optional, for real-time sync)
- [ ] Document resolution webhooks with Polymarket
- [ ] Monitor first few settlements for accuracy
- [ ] Create admin dashboard to track settlement status

---

## Timeline for User Payouts

```
Market Resolves on Polymarket
    ↓ (immediately)
Resolution Webhook / Scheduled Sync
    ↓ (within 5 minutes via periodic job)
Settlement Task Processes Orders
    ├─ Calculate P&L
    ├─ Create Transactions
    ├─ Update Order status
    └─ Enqueue M-Pesa calls
    ↓ (within 10 minutes)
M-Pesa B2C API Called
    ├─ Transfer to user
    └─ Retry on failure
    ↓ (within 1-5 minutes per Safaricom)
User Receives Payout
```

---

## Related Files

- Settlement for local markets: [payments/settlement_tasks.py](payments/settlement_tasks.py)
- Admin market resolution: [markets/admin_settlement_views.py](markets/admin_settlement_views.py)
- Polymarket adapter: [brokerage/services/polymarket/adapter.py](brokerage/services/polymarket/adapter.py)
- Order models: [brokerage/models.py](brokerage/models.py)
- Webhook view we added: [brokerage/api/views.py](brokerage/api/views.py) - `PolymarketFillWebhookView`

---

## Questions to Consider

1. **How should Polymarket payouts work?**
   - Fixed 100 KES per share (like local markets)?
   - Or variable based on market odds at time of placement?
   - Or variable based on market price at resolution?

2. **What about invalid/ambiguous market resolutions?**
   - Polymarket can mark markets as INVALID
   - Should we refund users or apply special rules?

3. **Should users be able to close positions before market resolves?**
   - Currently: NO - positions held until resolution
   - To enable: Need exit order logic (sell position back)

4. **What about partial position exits?**
   - Users may want to take profits early
   - Would need to track cost basis per exit

5. **Multi-leg positions?**
   - User places multiple bets in same market
   - Should we track cumulative position or per-order?

---

## Next Steps

Would you like me to implement:
1. ✅ **Phase 1**: Sync Polymarket resolutions (management command)
2. ✅ **Phase 2**: Settlement task for Polymarket positions
3. ✅ **Phase 3**: Database migrations for new fields
4. ✅ **Phase 4**: Payout distribution logic
5. ✅ **All of the above**
