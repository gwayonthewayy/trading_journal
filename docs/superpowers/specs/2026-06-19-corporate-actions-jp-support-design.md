# Corporate Actions and Japan Market Support Design

## Scope

This change adds auditable bonus-issue handling and first-class Japanese equity support. It also repairs the June 2026 Mirae Asset import by applying Komico's bonus issue before subsequent sells and importing the previously skipped JPY trade.

KIS Japan execution synchronization remains out of scope. The KIS worker continues to support only the exchanges currently verified against its API.

## Corporate Action Model

Add `CORPORATE_ACTION` to `EventType`. A bonus issue event uses:

- `reason=BONUS_ISSUE`
- `lot_id` and `ticker` to identify the affected lot
- `qty` for the additional shares
- `price` for the adjusted per-share cost
- `note` for source, ratio, effective date, and audit details

The bonus issue service accepts an existing lot, additional quantity, and effective timestamp. It preserves total lot cost:

```text
old_total_cost = old_total_quantity * old_entry_price
new_total_quantity = old_total_quantity + additional_quantity
new_entry_price = old_total_cost / new_total_quantity
```

It increases the lot quantity by the additional shares and updates the entry price. Corporate actions are excluded from BUY/SELL counts, win rates, monthly closed-trade statistics, and cash flow.

For historical corrections where sells already exist after the effective date, the safest data workflow is to restore the pre-import database backup and replay imports in chronological order with the corporate action inserted before affected sells. This avoids mutating existing sell allocations and realized PnL in place.

## Komico Correction

Komico's announced terms are one new share per existing share, record date `2026-05-27`, and listing date `2026-06-15`.

The eligible lot is the `2026-05-20` purchase of 52 shares at KRW 144,300. The importer inserts a bonus issue immediately before the first `2026-06-15` sell:

- quantity: 52 -> 104
- entry price: KRW 144,300 -> KRW 72,150
- total cost: unchanged at KRW 7,503,600

Later purchases are not adjusted because they occurred after the record date. The replayed FIFO sequence must support the full `2026-06-19` sell of 136 shares and leave Komico with zero open shares.

The correction is explicit rather than inferred from every sell shortfall. Future corporate actions require an explicit manifest entry so missing historical buys are never silently invented.

## Japan Market Support

Use the following canonical values:

- market: `JP`
- currency: `JPY`
- exchange: `TSE`
- stored ticker: the broker code without suffix, such as `4004`
- Yahoo symbol: `<ticker>.T`, such as `4004.T`

Add JP and JPY to journal input/edit controls and filters. Add the yen symbol `¥` to currency formatting.

The Mirae Asset overseas importer maps JPY rows to `JP/JPY` and assigns the normal overseas default time when the source has no time. The existing Yahoo chart endpoint supplies current price, currency, exchange, and name for `.T` symbols. The Yahoo Japan quote page may be used as a human-facing reference or fallback, but HTML scraping is not the primary price path because it is more fragile than the chart response.

FX conversion uses the existing provider chain for JPY to the configured base currency. Portfolio valuation, realized PnL, charts, and dual-currency summaries continue to operate through the existing generic FX layer.

## Data Replay

1. Back up the current database and uploads.
2. Restore `data/backups/pre_miraeasset_import_20260619_165506.sqlite` into a simulation copy.
3. Replay the domestic import with the explicit Komico corporate-action manifest.
4. Replay the overseas import with JPY enabled.
5. Replay the general-account external cash flows; ISA remains zero external flows.
6. Verify idempotency by replaying all files again.
7. Verify Komico closes at zero, Resonac Holdings opens at 100 shares, and database integrity is `ok`.
8. Only then repeat the replay on the real database after taking a fresh backup.

## Error Handling

- Reject a bonus issue if the target lot does not exist, the additional quantity is not positive, or the action timestamp precedes the lot opening.
- Reject duplicate corporate actions using a stable source tag in the event note.
- Do not infer bonus issues from quantity shortfalls.
- If JPY FX lookup fails, preserve the same explicit provider error behavior used by other currencies.
- If a Japanese quote is unavailable, retain the imported name and show current-price data as unavailable rather than blocking event creation.

## Tests

- Bonus issue preserves total cost and adjusts quantity and entry price.
- Duplicate bonus issue is idempotent.
- Corporate action does not appear in trade counts.
- Komico replay allocates all sells and ends with zero quantity.
- JPY maps to `JP/JPY`; ticker `4004` produces Yahoo candidate `4004.T`.
- Japanese current-price metadata is normalized without changing the stored ticker.
- Journal controls include JP and JPY.
- Replaying the same source files creates no new events.

