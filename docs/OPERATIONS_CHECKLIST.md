# Operations Checklist

## Security

1. `TJ_SIGNING_SECRET` is at least 32 bytes.
2. `TJ_VIEWER_TOKEN` and `TJ_ADMIN_TOKEN` are long random values.
3. `TJ_ADMIN_PASSWORD_HASH` uses Argon2 or PBKDF2 format.
4. App is bound to `127.0.0.1` and exposed through reverse proxy/tunnel only.
5. `.env.runtime` and `.access_info` are not committed.

## Data Integrity

1. Every `SELL` has at least one `SellAllocation`.
2. Allocation total does not exceed open lot quantity.
3. Realized PnL is computed from allocated lot cost basis, not portfolio-wide average.
4. After write APIs, backup file is created under `data/backups/`.

## Multi-Market

1. `Setting.base_currency` is configured (`KRW` recommended for KR/US/HK unified view).
2. Non-base currency orders include `fx_rate_to_base`.
3. Stats and book-asset are interpreted in base currency.
