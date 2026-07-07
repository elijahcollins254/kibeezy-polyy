#!/usr/bin/env python
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'api.settings')
django.setup()

from brokerage.models import Market
from datetime import datetime
from decimal import Decimal

# Create test markets
markets_data = [
    {
        'external_id': 'test-market-001',
        'title': 'Will Bitcoin reach $100k by end of 2024?',
        'question': 'Will Bitcoin reach $100k by end of 2024?',
        'description': 'Test market for BTC price prediction',
        'category': 'Crypto',
        'source': 'polymarket',
        'is_approved': True,
    },
    {
        'external_id': 'test-market-002',
        'title': 'Will the US election happen in 2024?',
        'question': 'Will the US presidential election take place on November 5, 2024?',
        'description': 'Test market for election prediction',
        'category': 'Politics',
        'source': 'polymarket',
        'is_approved': True,
    }
]

created = 0
for data in markets_data:
    market, created_new = Market.objects.get_or_create(
        external_id=data['external_id'],
        defaults={
            'title': data['title'],
            'question': data['question'],
            'description': data['description'],
            'category': data['category'],
            'source': data['source'],
            'is_approved': data['is_approved'],
            'approved_at': datetime.now() if data['is_approved'] else None,
        }
    )
    if created_new:
        print(f"✓ Created market: {market.title}")
        created += 1
    else:
        # Update if exists
        market.is_approved = True
        market.approved_at = datetime.now()
        market.save()
        print(f"✓ Updated market: {market.title}")
        created += 1

print(f"\n{created} markets added/updated successfully")

# Verify
approved = Market.objects.filter(is_approved=True, source='polymarket').count()
print(f"Total approved polymarket markets: {approved}")
