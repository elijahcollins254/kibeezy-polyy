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
        self.user = User.objects.create_user(username='tester', password='pass')
        # Create a market record that will be referenced by orders
        self.market = Market.objects.create(external_id='POLY:TEST', title='Test Market')

    def test_place_order_with_valid_signature_calls_service(self):
        # Mock signature verification to return True and TradingService to create an Order
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

        # Patch verify_signature to accept
        with patch('brokerage.api.views.verify_signature', return_value=True):
            # Patch TradingService.place_user_order to return an Order instance without performing ledger ops
            def fake_place(user, market_id, side, size, price):
                return Order.objects.create(user=user, market=self.market, side=side, size=size, price=price, status='OPEN')

            with patch('brokerage.api.views.TradingService.place_user_order', new=fake_place):
                self.client.force_authenticate(user=self.user)
                resp = self.client.post(url, payload, format='json')

        self.assertEqual(resp.status_code, 201)
        self.assertIn('id', resp.data)

    def test_place_order_signature_timestamp_out_of_window(self):
        url = '/api/brokerage/orders/place/'
        payload = {
            'market_id': self.market.external_id,
            'side': 'BUY',
            'size': '1.0',
            'price': '0.5',
            'signature': '0xdeadbeef',
            'signer_address': '0xabc',
            'timestamp': int(time.time()) - 10000,  # far in the past
        }

        self.client.force_authenticate(user=self.user)
        resp = self.client.post(url, payload, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('signature timestamp out of window', str(resp.data))
