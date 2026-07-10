"""
Helpers for Polymarket L1/L2 authentication.

- `create_or_derive_api_key()` uses the py_clob_client_v2 SDK (L1 private key) to create or derive API credentials (apiKey, secret, passphrase).
- `build_l2_headers(...)` builds the required L2 headers for authenticated CLOB requests using HMAC-SHA256.

Notes:
- This module prefers the official SDK; fallback operations rely on simple HMAC signing and may need adjustment to match Polymarket server expectations.
- Never commit private keys or secrets. Use environment variables or secret manager.
"""
import os
import time
import base64
import hmac
import hashlib
import logging
from pathlib import Path
from typing import Dict, Optional

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

if load_dotenv is not None:
    env_path = Path(__file__).resolve().parents[2] / '.env'
    if env_path.exists():
        load_dotenv(env_path, override=False)

logger = logging.getLogger(__name__)

try:
    from py_clob_client_v2 import ClobClient
    HAS_SDK = True
except Exception:
    HAS_SDK = False


def create_or_derive_api_key(private_key: Optional[str] = None, host: Optional[str] = None):
    """
    Create or derive API credentials (apiKey, secret, passphrase) using L1 signing.
    Requires `py_clob_client_v2` to be installed and a valid private key.

    Returns:
        dict with keys: apiKey, secret, passphrase
    """
    private_key = private_key or os.getenv('POLY_PRIVATE_KEY')
    host = host or os.getenv('POLYMARKET_BASE_URL', 'https://clob.polymarket.com')

    if not private_key:
        raise RuntimeError('POLY_PRIVATE_KEY not provided (set POLY_PRIVATE_KEY in env)')

    if not HAS_SDK:
        raise RuntimeError('py_clob_client_v2 is not installed. Install it to derive api keys.')

    client = ClobClient(host=host, key=private_key)
    creds = client.create_or_derive_api_key()
    # creds: {apiKey, secret (base64), passphrase}
    logger.info('Polymarket API credentials created/derived')
    return creds


def build_l2_headers(api_key: str, secret_b64: str, passphrase: str, address: str, method: str, path: str, body: Optional[str] = None) -> Dict[str, str]:
    """
    Build L2 headers required by Polymarket CLOB trading endpoints.

    The POLY_SIGNATURE is an HMAC-SHA256 over a message using the API secret.
    The exact message format should match the server's expectations; this implementation
    uses: message = METHOD + "|" + PATH + "|" + TIMESTAMP + "|" + (body or "").

    Args:
        api_key: apiKey value
        secret_b64: base64-encoded secret (from create_or_derive_api_key)
        passphrase: api passphrase
        address: polygon signer address (POLY_ADDRESS)
        method: HTTP method (GET/POST/...)
        path: Request path (e.g., '/orders')
        body: Raw request body string (if any)

    Returns:
        dict of headers to include on HTTP request
    """
    if not all([api_key, secret_b64, passphrase, address]):
        raise RuntimeError('api_key, secret_b64, passphrase and address are required to build L2 headers')

    timestamp = str(int(time.time()))
    body_str = body or ''
    message = f"{method.upper()}|{path}|{timestamp}|{body_str}"

    try:
        secret = base64.b64decode(secret_b64)
    except Exception:
        # If secret isn't base64, try raw bytes
        secret = secret_b64.encode()

    sig = hmac.new(secret, message.encode('utf-8'), hashlib.sha256).digest()
    signature_b64 = base64.b64encode(sig).decode()

    headers = {
        'POLY_ADDRESS': address,
        'POLY_SIGNATURE': signature_b64,
        'POLY_TIMESTAMP': timestamp,
        'POLY_API_KEY': api_key,
        'POLY_PASSPHRASE': passphrase,
    }

    return headers
