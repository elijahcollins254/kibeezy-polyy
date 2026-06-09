"""Helpers for verifying Ethereum-style signatures for user-signed payloads.

This uses `eth_account` to recover the signing address from a message signature.
The canonical message format used here is the compact JSON serialization with
sorted keys to ensure deterministic signing on client and server.
"""
import json
from typing import Dict, Any

try:
    from eth_account import Account
    from eth_account.messages import encode_defunct
except Exception:  # pragma: no cover - optional dependency
    Account = None
    encode_defunct = None


def _canonical_message(payload: Dict[str, Any]) -> str:
    # deterministic JSON serialization used for signing
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def verify_signature(payload: Dict[str, Any], signature_hex: str, expected_address: str) -> bool:
    """Return True if the provided signature recovers `expected_address`.

    - `payload` should be the dictionary that was signed.
    - `signature_hex` is the hex string (with or without 0x) of the signature.
    - `expected_address` is the hex address (case-insensitive) to compare against.

    Raises ValueError if `eth-account` is not installed.
    """
    if Account is None or encode_defunct is None:
        raise ValueError('eth-account is required to verify signatures')

    if signature_hex.startswith('0x'):
        signature_hex = signature_hex[2:]

    try:
        sig_bytes = bytes.fromhex(signature_hex)
    except Exception as e:
        raise ValueError(f'invalid signature hex: {e}')

    message_text = _canonical_message(payload)
    message = encode_defunct(text=message_text)

    try:
        recovered = Account.recover_message(message, signature=sig_bytes)
    except Exception as e:
        raise ValueError(f'signature recovery failed: {e}')

    # Normalize addresses for comparison (case-insensitive)
    return (recovered or '').lower() == (expected_address or '').lower()
