Polymarket API Overview

Polymarket exposes three separate public APIs and a Bridge service:

- Gamma API (public)
  - Host: https://gamma-api.polymarket.com
  - Use: Markets, events, tags, series, comments, sports, search, public profiles
  - No authentication required

- Data API (public)
  - Host: https://data-api.polymarket.com
  - Use: Positions, trades, activity, holder data, open interest, leaderboards, analytics
  - No authentication required

- CLOB API (orderbook & trading)
  - Host: https://clob.polymarket.com
  - Use: Orderbook data, pricing, midpoints, spreads, price history (public); order placement, cancellation, balances (authenticated)
  - Trading endpoints require L2 authentication headers (see below)

- Bridge API
  - Host: https://bridge.polymarket.com
  - Use: Deposits & withdrawals (proxy of fun.xyz)

Authentication summary

- Gamma & Data APIs: public (no auth)
- CLOB API: public read endpoints; authenticated trading endpoints using L2 headers

Two-level model (L1 / L2)

- L1: Private key (EIP-712) used to create/derive API credentials (apiKey, secret, passphrase). Typically done via the official SDK (recommended).
- L2: HMAC-SHA256 signed requests using API credentials. Trading endpoints require these headers:
  - POLY_ADDRESS
  - POLY_SIGNATURE
  - POLY_TIMESTAMP
  - POLY_API_KEY
  - POLY_PASSPHRASE

What this repo implements

- `brokerage/services/polymarket/client.py` — CLOB client. Defaults to `POLY_CLOB_BASE_URL` or the official `https://clob.polymarket.com`. It now automatically attaches L2 headers when `POLY_API_KEY`, `POLY_API_SECRET`, `POLY_API_PASSPHRASE`, and `POLY_ADDRESS` are set in settings/env.

- `brokerage/services/polymarket/client.py` — split client: Data/Gamma client (market metadata) and CLOB client (orderbook/trading). Defaults:
  - Data: `POLY_DATA_BASE_URL` or `POLY_GAMMA_BASE_URL` (defaults to `https://data-api.polymarket.com`)
  - CLOB: `POLY_CLOB_BASE_URL` or `POLYMARKET_BASE_URL` (defaults to `https://clob.polymarket.com`)
  The client composes both implementations and routes calls appropriately.

- `brokerage/services/polymarket/auth.py` — helpers to derive API credentials (L1) using `py_clob_client_v2` and to build L2 headers (HMAC-SHA256).

- `brokerage/management/commands/create_poly_api_creds.py` — management command to derive/create API credentials using L1 private key.

Config keys (add to `.env`)

- POLY_CLOB_BASE_URL (optional, defaults to https://clob.polymarket.com)
- POLYMARKET_BASE_URL (legacy; used if POLY_CLOB_BASE_URL not set)
- POLY_PRIVATE_KEY (for L1 derivation via SDK)
- POLY_API_KEY (L2 apiKey)
- POLY_API_SECRET (L2 secret, base64)
- POLY_API_PASSPHRASE (L2 passphrase)
- POLY_ADDRESS (signer address used in L2 headers)
Additional environment variables supported by this repo:

- `POLY_DATA_BASE_URL` or `POLY_GAMMA_BASE_URL` — overrides Data/Gamma API base URL (market metadata and analytics).
- `POLY_CLOB_BASE_URL` — explicit CLOB API URL.
- `POLY_PRIVATE_KEY` — L1 private key (used only to derive L2 creds via SDK; keep offline/secure).
- `POLYMARKET_API_KEY` / `POLY_API_SECRET` / `POLY_API_PASSPHRASE` / `POLY_ADDRESS` — L2 credentials used for authenticated trading.

Quick steps

1. Derive API credentials (L1):

```bash
export POLY_PRIVATE_KEY="<your_private_key>"
python manage.py create_poly_api_creds
```

2. Store `apiKey`, `secret`, and `passphrase` securely (e.g., in `.env` or secrets manager):

```
POLY_API_KEY=...
POLY_API_SECRET=...  # base64 secret
POLY_API_PASSPHRASE=...
POLY_ADDRESS=0x....
```

3. Test an authenticated request via the client (trading endpoints):

```python
from brokerage.services.polymarket.client import PolymarketClient
c = PolymarketClient()
print(c.get_positions(account_id='your_account'))
```

Notes & security

- Never commit private keys or API secrets to version control.
- Prefer the official SDK (`py_clob_client_v2`) for L1 operations.
- Signing order payloads still requires the user's EIP-712 signature; server-side signing is only for deriving API credentials or admin flows where appropriate.
