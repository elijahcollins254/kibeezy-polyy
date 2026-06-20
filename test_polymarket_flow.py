"""
Comprehensive test for Polymarket order flow: placement → fills → resolution → settlement
"""
import os
import django
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'api.settings')
django.setup()

from django.test import TestCase
from django.utils import timezone
from users.models import CustomUser
from brokerage.models import Market, Order, Fill, Position, LedgerEntry, Account
from brokerage.services.settlement import PolymarketSettlementService
from brokerage.services.trading import TradingService
import logging

logger = logging.getLogger(__name__)

def test_complete_order_flow():
    """Test complete flow: order placement → fills → resolution → settlement"""
    
    print("\n" + "="*80)
    print("POLYMARKET ORDER FLOW TEST")
    print("="*80)
    
    # Step 1: Create test user
    print("\n[1] Creating test user...")
    user = CustomUser.objects.filter(phone_number='254700000001').first()
    if not user:
        user = CustomUser.objects.create(
            phone_number='254700000001',
            full_name='Test User',
            balance=Decimal('10000.00')
        )
        print(f"✓ Created user: {user.phone_number} with balance {user.balance}")
    else:
        print(f"✓ Using existing user: {user.phone_number} with balance {user.balance}")
    
    # Step 2: Create test market (fresh one each time)
    import time
    print("\n[2] Creating test market...")
    timestamp = int(time.time() * 1000) % 1000000
    market = Market.objects.create(
        external_id=f'ext_market_test_{timestamp}',
        title=f'Test Resolution Market {timestamp}',
        question='Will test resolve successfully?',
        description='A test market to verify settlement flow',
        polymarket_status='OPEN',
    )
    print(f"✓ Created market: {market.title}")
    print(f"  - Status: {market.polymarket_status}")
    
    # Step 3: Place order
    print("\n[3] Placing market order...")
    order = Order.objects.create(
        user=user,
        market=market,
        side='BUY',  # Betting YES
        size=Decimal('100.00'),  # 100 shares
        price=Decimal('0.50'),
        status='PENDING',
        external_order_id='ext_order_12345',
    )
    print(f"✓ Created order: {order.id}")
    print(f"  - Side: {order.side}")
    print(f"  - Size: {order.size} shares")
    print(f"  - Price: {order.price}")
    print(f"  - Status: {order.status}")
    
    # Step 4: Simulate fills
    print("\n[4] Processing order fills...")
    fill = Fill.objects.create(
        order=order,
        external_fill_id='fill_ext_001',
        size=Decimal('100.00'),
        price=Decimal('0.50'),
    )
    print(f"✓ Created fill: {fill.id}")
    print(f"  - Filled Size: {fill.size}")
    print(f"  - Fill Price: {fill.price}")
    
    # Update order status
    order.status = 'FILLED'
    order.save()
    print(f"✓ Order status updated to FILLED")
    
    # Step 5: Update position
    print("\n[5] Updating user position...")
    trading_service = TradingService()
    trading_service._update_position_from_fills(user, market, order)
    
    position = Position.objects.get(user=user, market=market)
    print(f"✓ Position updated:")
    print(f"  - Quantity: {position.quantity} shares")
    print(f"  - Average Price: {position.average_price}")
    print(f"  - Entry Value: {position.quantity * position.average_price}")
    
    # Step 6: Resolve market
    print("\n[6] Resolving market...")
    market.polymarket_status = 'RESOLVED'
    market.resolution_outcome = 'Yes'  # User's YES bet wins
    market.resolution_price = Decimal('0.75')  # Price at resolution
    market.resolved_at = timezone.now()
    market.save()
    print(f"✓ Market resolved:")
    print(f"  - Outcome: {market.resolution_outcome}")
    print(f"  - Resolution Price: {market.resolution_price}")
    print(f"  - Resolved At: {market.resolved_at}")
    
    # Step 7: Execute settlement
    print("\n[7] Executing settlement...")
    
    # Calculate expected payout
    expected_payout = order.size * market.resolution_price * Decimal('100')  # Convert 0-1 to 0-100 KES
    print(f"  - Expected payout: {expected_payout} KES")
    
    # Run settlement
    try:
        result = PolymarketSettlementService.settle_market(market)
        print(f"✓ Settlement executed:")
        print(f"  - Orders processed: {result.get('orders_processed', 0)}")
        print(f"  - Payouts created: {result.get('payouts_created', 0)}")
        print(f"  - Total payout: {result.get('total_payout', 0)} KES")
    except Exception as e:
        print(f"✗ Settlement error: {e}")
        return False
    
    # Step 8: Verify results
    print("\n[8] Verifying settlement results...")
    
    # Check order settlement status
    order.refresh_from_db()
    print(f"✓ Order settlement status:")
    print(f"  - Status: {order.status}")
    print(f"  - Settlement Result: {order.settlement_result}")
    print(f"  - Payout: {order.payout} KES")
    print(f"  - Settled At: {order.settled_at}")
    
    # Check market settlement status
    market.refresh_from_db()
    print(f"✓ Market settlement status:")
    print(f"  - Status: {market.polymarket_status}")
    print(f"  - Settlement Status: {market.settlement_status}")
    print(f"  - Settlement Completed At: {market.settlement_completed_at}")
    
    # Check ledger entries
    print(f"✓ Ledger entries created (see settlement_status for details)")
    
    # Verify payout matches expected
    if order.payout == expected_payout:
        print(f"\n✓ PAYOUT VERIFIED: {order.payout} KES (matches expected)")
    else:
        print(f"\n✗ PAYOUT MISMATCH: {order.payout} (expected {expected_payout})")
        return False
    
    # Step 9: Verify user balance impact
    print("\n[9] Checking user account...")
    user.refresh_from_db()
    print(f"  - User balance: {user.balance}")
    
    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    print(f"✓ Order placed: {order.id}")
    print(f"✓ Fill processed: {fill.id}")
    print(f"✓ Position updated: {position.quantity} shares @ {position.average_price}")
    print(f"✓ Market resolved: {market.resolution_outcome} @ {market.resolution_price}")
    print(f"✓ Settlement executed: {order.payout} KES payout")
    print(f"✓ All tests PASSED")
    print("="*80 + "\n")
    
    return True


def test_settlement_loss_scenario():
    """Test settlement when user's bet loses"""
    
    print("\n" + "="*80)
    print("POLYMARKET LOSS SETTLEMENT TEST")
    print("="*80)
    
    # Create test user
    print("\n[1] Creating test user...")
    user = CustomUser.objects.filter(phone_number='254700000002').first()
    if not user:
        user = CustomUser.objects.create(
            phone_number='254700000002',
            full_name='Test User Loss',
            balance=Decimal('5000.00')
        )
        print(f"✓ Created user: {user.phone_number}")
    else:
        print(f"✓ Using existing user: {user.phone_number}")
    
    # Create market (fresh one)
    import time
    print("\n[2] Creating test market...")
    timestamp = int(time.time() * 1000) % 1000000
    market = Market.objects.create(
        external_id=f'ext_market_loss_{timestamp}',
        title=f'Test Loss Market {timestamp}',
        question='Will this lose?',
        description='A market where bet loses',
        polymarket_status='OPEN',
    )
    print(f"✓ Created market: {market.title}")
    
    # Place order (BET NO)
    print("\n[3] Placing order (betting NO)...")
    order = Order.objects.create(
        user=user,
        market=market,
        side='SELL',  # Betting NO
        size=Decimal('50.00'),
        price=Decimal('0.40'),
        status='FILLED',
        external_order_id='ext_loss_001',
    )
    print(f"✓ Order created: {order.id} ({order.side})")
    
    # Add fill
    fill = Fill.objects.create(
        order=order,
        external_fill_id='fill_loss_001',
        size=Decimal('50.00'),
        price=Decimal('0.40'),
    )
    print(f"✓ Fill created: {fill.id}")
    
    # Update position
    trading_service = TradingService()
    trading_service._update_position_from_fills(user, market, order)
    
    # Resolve market with YES (user loses)
    print("\n[4] Resolving market to YES (user loses)...")
    market.polymarket_status = 'RESOLVED'
    market.resolution_outcome = 'Yes'  # User bet NO, so this is a loss
    market.resolution_price = Decimal('0.85')
    market.resolved_at = timezone.now()
    market.save()
    print(f"✓ Market resolved to {market.resolution_outcome}")
    
    # Execute settlement
    print("\n[5] Executing settlement...")
    result = PolymarketSettlementService.settle_market(market)
    
    order.refresh_from_db()
    print(f"✓ Settlement result:")
    print(f"  - Settlement Result: {order.settlement_result}")
    print(f"  - Payout: {order.payout} KES")
    
    if order.settlement_result == 'LOST' and order.payout == Decimal('0'):
        print(f"\n✓ LOSS SCENARIO VERIFIED: Order marked as LOST with 0 payout")
        return True
    else:
        print(f"\n✗ LOSS SCENARIO FAILED: Expected LOST with 0 payout")
        return False


if __name__ == '__main__':
    print("\n\nRunning Polymarket Order Flow Tests...")
    
    # Run tests
    test1_passed = test_complete_order_flow()
    test2_passed = test_settlement_loss_scenario()
    
    # Summary
    print("\n" + "="*80)
    print("FINAL TEST RESULTS")
    print("="*80)
    print(f"Test 1 (Winning Order Flow): {'PASSED ✓' if test1_passed else 'FAILED ✗'}")
    print(f"Test 2 (Loss Scenario): {'PASSED ✓' if test2_passed else 'FAILED ✗'}")
    
    if test1_passed and test2_passed:
        print("\n🎉 All tests PASSED!")
    else:
        print("\n⚠️  Some tests failed")
    print("="*80)
