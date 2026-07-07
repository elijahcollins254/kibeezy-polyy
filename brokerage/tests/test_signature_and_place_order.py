from django.test import TestCase
from rest_framework.test import APIClient
from django.urls import reverse
from django.contrib.auth import get_user_model
from unittest.mock import patch
import time

from brokerage.models import Market, Order


class SignatureAndPlaceOrderTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        User = get_user_model()
        self.user = User.objects.create_user(
            phone_number='254700000000',
            full_name='Test User',
            username='tester',
            password='pass'
        )
        # Create a market record that will be referenced by orders
        self.market = Market.objects.create(external_id='POLY:TEST', title='Test Market')

    def test_place_order_with_valid_signature_calls_service(self):
        url = '/api/brokerage/orders/place/'
        payload = {
            'market_id': self.market.external_id,
            'side': 'BUY',
            'size': '1.0',
            'price': '0.5',
            'token_id': '12345',
            'signature': '0xdeadbeef',
            'signer_address': '0xabc',
            'timestamp': int(time.time()),
        }

        with patch('brokerage.api.views.verify_signature', return_value=True):
            def fake_place(self_obj, user, market_id, token_id, side, size, price, order_type='market'):
                return {
                    'success': True,
                    'market_id': market_id,
                    'token_id': token_id,
                    'side': side,
                    'size': size,
                    'price': price,
                    'order_type': order_type,
                }

            with patch('brokerage.api.views.TradingService.place_polymarket_order', new=fake_place):
                self.client.force_authenticate(user=self.user)
                resp = self.client.post(url, payload, format='json')

        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.data['success'])

    def test_place_order_signature_timestamp_out_of_window(self):
        url = '/api/brokerage/orders/place/'
        payload = {
            'market_id': self.market.external_id,
            'side': 'BUY',
            'size': '1.0',
            'price': '0.5',
            'token_id': '12345',
            'signature': '0xdeadbeef',
            'signer_address': '0xabc',
            'timestamp': int(time.time()) - 10000,  # far in the past
        }

        self.client.force_authenticate(user=self.user)
        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('signature timestamp out of window', str(resp.data))

    def test_place_order_requires_polymarket_token_id(self):
        url = '/api/brokerage/orders/place/'
        payload = {
            'market_id': self.market.external_id,
            'side': 'BUY',
            'size': '1.0',
            'price': '0.5',
            'signature': '0xdeadbeef',
            'signer_address': '0xabc',
            'timestamp': int(time.time()),
        }

        self.client.force_authenticate(user=self.user)
        resp = self.client.post(url, payload, format='json')

        self.assertEqual(resp.status_code, 400)
        self.assertIn('token_id', str(resp.data).lower())

    def test_market_list_filters_out_local_markets(self):
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
        self.assertTrue(any(m['external_id'] == 'POLY:APPROVED' for m in resp.data),
                        'Expected approved Polymarket market to be returned in market list')
        self.assertFalse(any(m['external_id'] == 'LOCAL:APPROVED' for m in resp.data),
                         'Expected local market to be excluded from market list')
