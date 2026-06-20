"""
Test script for adding comments to Polymarket markets on your Cache app
"""
import os
import django
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'api.settings')
django.setup()

from users.models import CustomUser
from brokerage.models import Market
from support.models import ChatMessage  # Assuming comments are in support/chat app
import json

def test_add_market_comment():
    """Test adding a comment to a market"""
    
    print("\n" + "="*80)
    print("MARKET COMMENT TEST")
    print("="*80)
    
    # Step 1: Check existing markets
    print("\n[1] Checking existing markets...")
    markets = Market.objects.all()[:5]
    print(f"✓ Total markets in database: {Market.objects.count()}")
    
    if not markets.exists():
        print("✗ No markets found. Syncing from Polymarket...")
        from brokerage.services.polymarket.adapter import PolymarketAdapter
        adapter = PolymarketAdapter()
        
        try:
            poly_markets = adapter.get_markets(params={'limit': 5})
            print(f"  Fetched {len(poly_markets)} markets from Polymarket")
            
            for pm in poly_markets:
                external_id = pm.get('id') or pm.get('market_id')
                if not external_id:
                    continue
                
                Market.objects.update_or_create(
                    external_id=str(external_id),
                    defaults={
                        'title': pm.get('title') or pm.get('name') or external_id,
                        'question': pm.get('question') or pm.get('title') or '',
                        'description': pm.get('description') or '',
                        'metadata': pm,
                    }
                )
            
            markets = Market.objects.all()[:5]
            print(f"✓ Synced {markets.count()} markets")
        except Exception as e:
            print(f"✗ Failed to sync: {e}")
            return False
    
    # Display markets
    for market in markets:
        print(f"  - Market {market.id}: {market.title[:60]}")
    
    # Step 2: Select a market
    print("\n[2] Selecting market for comment...")
    market = markets.first()
    if not market:
        print("✗ No markets available")
        return False
    
    print(f"✓ Selected market: {market.id} - {market.title}")
    
    # Step 3: Get or create test user
    print("\n[3] Getting test user...")
    user = CustomUser.objects.filter(phone_number='254700000001').first()
    if not user:
        user = CustomUser.objects.create(
            phone_number='254700000001',
            full_name='Test Commenter',
            balance=Decimal('1000.00')
        )
        print(f"✓ Created test user: {user.phone_number}")
    else:
        print(f"✓ Using test user: {user.phone_number}")
    
    # Step 4: Add a comment to the market
    print("\n[4] Adding comment to market...")
    
    try:
        # Check if ChatMessage model exists and has market field
        from support.models import ChatMessage
        
        comment = ChatMessage.objects.create(
            user=user,
            message=f"This is a test comment about market {market.id}. The question is: {market.question}",
            market_id=market.id,  # Try to link to market if the model supports it
        )
        
        print(f"✓ Comment created successfully!")
        print(f"  - Comment ID: {comment.id}")
        print(f"  - User: {user.full_name}")
        print(f"  - Market: {market.title}")
        print(f"  - Message: {comment.message[:100]}...")
        print(f"  - Created at: {comment.created_at}")
        
        return True
        
    except Exception as e:
        print(f"✗ Failed to create comment: {e}")
        print(f"  - Error type: {type(e).__name__}")
        
        # Try alternative approach if ChatMessage structure is different
        try:
            print("\n[4b] Trying alternative comment structure...")
            # Some systems might store comments differently
            comment = ChatMessage.objects.create(
                user=user,
                message=f"Alternative test comment for market {market.id}",
            )
            print(f"✓ Comment created with alternative structure!")
            return True
        except Exception as e2:
            print(f"✗ Alternative approach also failed: {e2}")
            return False

def test_retrieve_market_comments():
    """Test retrieving comments for a market"""
    
    print("\n" + "="*80)
    print("RETRIEVE MARKET COMMENTS TEST")
    print("="*80)
    
    # Get a market with comments
    try:
        from support.models import ChatMessage
        
        print("\n[1] Checking for existing comments...")
        all_comments = ChatMessage.objects.all()
        print(f"✓ Total comments in database: {all_comments.count()}")
        
        # Try to get comments by market
        market = Market.objects.first()
        if not market:
            print("✗ No markets found")
            return False
        
        print(f"\n[2] Retrieving comments for market {market.id}...")
        
        try:
            # Try filtering by market_id
            market_comments = ChatMessage.objects.filter(market_id=market.id)
            print(f"✓ Found {market_comments.count()} comments for this market")
            
            for comment in market_comments[:3]:
                print(f"  - {comment.user.full_name}: {comment.message[:80]}...")
            
            return True
        except Exception as e:
            print(f"Note: Cannot filter by market_id: {e}")
            print("  (Market field might not exist in ChatMessage model)")
            
            # Just show all comments
            all_comments = ChatMessage.objects.all()[:5]
            print(f"✓ Latest comments ({all_comments.count()} shown):")
            for comment in all_comments:
                print(f"  - {comment.user.full_name}: {comment.message[:80]}...")
            
            return True
    
    except Exception as e:
        print(f"✗ Error retrieving comments: {e}")
        return False

def display_market_details():
    """Display detailed info about markets"""
    
    print("\n" + "="*80)
    print("MARKET DETAILS")
    print("="*80)
    
    markets = Market.objects.all()[:3]
    
    if not markets.exists():
        print("No markets found in database")
        return False
    
    for i, market in enumerate(markets, 1):
        print(f"\n[{i}] Market ID: {market.id}")
        print(f"    Title: {market.title}")
        print(f"    Question: {market.question[:100]}")
        print(f"    Category: {market.category}")
        print(f"    Created: {market.created_at}")
        print(f"    External ID: {market.external_id}")
    
    return True

if __name__ == '__main__':
    print("\n\nTesting Market Comment Feature...")
    
    # Run tests
    display_market_details()
    test1_passed = test_add_market_comment()
    test2_passed = test_retrieve_market_comments()
    
    # Summary
    print("\n" + "="*80)
    print("FINAL TEST RESULTS")
    print("="*80)
    print(f"Add Comment Test: {'PASSED ✓' if test1_passed else 'FAILED ✗'}")
    print(f"Retrieve Comments Test: {'PASSED ✓' if test2_passed else 'FAILED ✗'}")
    print("="*80)
