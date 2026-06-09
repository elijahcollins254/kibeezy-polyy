import base64
from unittest.mock import patch

from django.test import TestCase

from brokerage.services.polymarket.auth import build_l2_headers


class PolymarketAuthTests(TestCase):
    def test_build_l2_headers_signature_matches_expected(self):
        api_key = 'test_key'
        secret = b'supersecret'
        secret_b64 = base64.b64encode(secret).decode()
        passphrase = 'pass'
        address = '0xabc'
        method = 'POST'
        path = '/orders'
        body = '{"foo":"bar"}'

        # Freeze time so signature is deterministic
        with patch('brokerage.services.polymarket.auth.time.time', return_value=1650000000):
            headers = build_l2_headers(api_key, secret_b64, passphrase, address, method, path, body)

        # Validate header keys
        assert headers['POLY_API_KEY'] == api_key
        assert headers['POLY_PASSPHRASE'] == passphrase
        assert headers['POLY_ADDRESS'] == address

        # Recompute signature locally to ensure it matches
        timestamp = headers['POLY_TIMESTAMP']
        message = f"{method}|{path}|{timestamp}|{body}"
        import hmac, hashlib
        sig = hmac.new(secret, message.encode('utf-8'), hashlib.sha256).digest()
        expected_sig_b64 = base64.b64encode(sig).decode()

        assert headers['POLY_SIGNATURE'] == expected_sig_b64
