import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'api.settings')
django.setup()

from markets.models import Market, ChatMessage
from users.models import CustomUser
from decimal import Decimal

print("\n" + "="*80)
print("TESTING MARKET COMMENTS")
print("="*80)

# Step 1: Check markets
print("\n[1] Checking markets...")
market_count = Market.objects.count()
print(f"✓ Total markets: {market_count}")

markets = Market.objects.all()[:3]
for m in markets:
    print(f"  - {m.id}: {m.question[:50]}")

if not markets.exists():
    print("✗ No markets found - need to create one first")
    # Create test market
    print("   Creating test market...")
    market = Market.objects.create(
        question="Will Bitcoin reach $100,000?",
        category="Crypto",
        description="Testing comment functionality on this market",
        end_date="2026-12-31",
        yes_probability=65
    )
    markets = Market.objects.filter(id=market.id)
    print(f"   ✓ Created market: {market.id}")

# Step 2: Get or create user
print("\n[2] Creating test user...")
user, created = CustomUser.objects.get_or_create(
    phone_number='254700000099',
    defaults={
        'full_name': 'Comment Tester',
        'balance': Decimal('5000.00')
    }
)
status = "Created" if created else "Existing"
print(f"✓ {status} user: {user.full_name} ({user.phone_number})")

# Step 3: Add comment
print("\n[3] Adding comment to market...")
market = markets.first()
print(f"   Market: {market.question}")

try:
    comment = ChatMessage.objects.create(
        user=user,
        market=market,
        message="This market looks interesting! When do we expect resolution?"
    )
    print(f"✓ Comment created successfully!")
    print(f"  - Comment ID: {comment.id}")
    print(f"  - User: {comment.user.full_name}")
    print(f"  - Market: {comment.market.title}")
    print(f"  - Message: {comment.message}")
    print(f"  - Created: {comment.created_at}")
except Exception as e:
    print(f"✗ Error creating comment: {e}")
    print(f"  Error type: {type(e).__name__}")
    import traceback
    traceback.print_exc()

# Step 4: Add reply to comment
print("\n[4] Adding reply to comment...")
try:
    user2, _ = CustomUser.objects.get_or_create(
        phone_number='254700000100',
        defaults={'full_name': 'Reply Tester', 'balance': Decimal('3000.00')}
    )
    
    reply = ChatMessage.objects.create(
        user=user2,
        market=market,
        parent=comment,
        message="Great question! I think it will resolve by end of month."
    )
    print(f"✓ Reply created successfully!")
    print(f"  - Reply ID: {reply.id}")
    print(f"  - User: {reply.user.full_name}")
    print(f"  - Reply to: {reply.parent.user.full_name}'s comment")
    print(f"  - Message: {reply.message}")
except Exception as e:
    print(f"✗ Error creating reply: {e}")

# Step 5: Retrieve comments
print("\n[5] Retrieving comments for market...")
comments = ChatMessage.objects.filter(market=market, parent__isnull=True).order_by('-created_at')
print(f"✓ Found {comments.count()} comments:")
for c in comments:
    replies = ChatMessage.objects.filter(parent=c)
    print(f"  - {c.user.full_name}: {c.message[:60]}... ({replies.count()} replies)")
    for r in replies:
        print(f"    ↳ {r.user.full_name}: {r.message[:50]}...")

print("\n" + "="*80)
print("✓ TEST COMPLETE")
print("="*80 + "\n")
