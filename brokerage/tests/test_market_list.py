from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from brokerage.models import Market


class MarketListViewTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_market_list_includes_approved_local_and_polymarket_markets(self):
        Market.objects.create(
            external_id='LOCAL:APPROVED',
            title='Local Approved Market',
            is_approved=True,
            source='local'
        )
        Market.objects.create(
            external_id='POLY:APPROVED',
            title='Polymarket Approved Market',
            is_approved=True,
            source='polymarket'
        )

        resp = self.client.get('/api/brokerage/markets/')

        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.data, list)
        external_ids = [market['external_id'] for market in resp.data]
        self.assertIn('LOCAL:APPROVED', external_ids)
        self.assertIn('POLY:APPROVED', external_ids)

    def test_market_list_excludes_resolved_or_closed_polymarket_markets(self):
        Market.objects.create(
            external_id='POLY:ACTIVE',
            title='Active Polymarket Market',
            is_approved=True,
            source='polymarket',
            polymarket_status='OPEN'
        )
        Market.objects.create(
            external_id='POLY:RESOLVED',
            title='Resolved Polymarket Market',
            is_approved=True,
            source='polymarket',
            polymarket_status='RESOLVED',
            resolved_at=timezone.now()
        )
        Market.objects.create(
            external_id='POLY:CLOSED',
            title='Closed Polymarket Market',
            is_approved=True,
            source='polymarket',
            polymarket_status='CLOSED'
        )

        resp = self.client.get('/api/brokerage/markets/')

        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.data, list)
        external_ids = [market['external_id'] for market in resp.data]
        self.assertIn('POLY:ACTIVE', external_ids)
        self.assertNotIn('POLY:RESOLVED', external_ids)
        self.assertNotIn('POLY:CLOSED', external_ids)
