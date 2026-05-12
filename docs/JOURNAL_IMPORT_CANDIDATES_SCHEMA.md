# journal_import_candidates.json Schema

This is the intermediate format between the VCS Minervini screener overlay and
`trading_journal`.

## Candidate ID

Rule:

```text
YYYYMMDD_MARKET_TICKER_SETUPTYPE
```

Example:

```text
20260513_KR_038500_VCP_PROXY
```

The importer upserts by `candidate_id`, so importing the same scan date, market,
ticker, and setup type again updates the existing TradeGroup candidate instead
of creating a duplicate.

## Top-Level Payload

```json
{
  "schema_version": "1.0",
  "generated_at": "2026-05-13T09:30:00",
  "source_file": "results/0513_CODEX/candidates.csv",
  "candidate_id_rule": "YYYYMMDD_MARKET_TICKER_SETUPTYPE",
  "base_quality_method": "csv_proxy",
  "trade_status_values": ["candidate", "planned", "active", "closed", "archived"],
  "journal_trade_stances": ["actionable", "excluded", "pilot_only", "watchlist_only"],
  "mandatory_actionable_fields": [
    "planned_entry",
    "planned_stop",
    "planned_risk_pct",
    "sell_plan",
    "leadership_gate",
    "trend_template_pass"
  ],
  "max_planned_risk_pct": 8.0,
  "candidates": []
}
```

## Required Candidate Fields

Every candidate object must include these keys. Values may be `null` when the
screener cannot compute them yet.

- `candidate_id`
- `scan_date`
- `market`
- `ticker`
- `name`
- `close`
- `source_file`
- `setup_type`
- `trade_stance`
- `leadership_gate`
- `trend_template_pass`
- `entry_zone_label`
- `base_quality_label`
- `base_quality_proxy_label`
- `base_quality_method`
- `risk_first_status`
- `rr_status`
- `planned_entry`
- `planned_stop`
- `planned_risk_pct`
- `pivot_price`
- `buy_zone_low`
- `buy_zone_high`
- `invalidation_price`
- `sell_plan`
- `minervini_summary`
- `overlay_snapshot`

## Conservative RS Rule

If `leadership_gate` is `RS미확인`, `RS약세`, or `RS약함`, the journal import stance
must not be `actionable`.

The VCS exporter downgrades these to `watchlist_only`. The journal importer also
defensively downgrades malformed incoming `actionable` rows with weak or missing
RS to `watchlist_only`.

## Promotion Rules

A candidate can only be considered actionable when all of these are true:

- `planned_entry` exists.
- `planned_stop` exists.
- `planned_risk_pct` can be calculated.
- `planned_risk_pct` is greater than 0 and no more than `max_planned_risk_pct`.
- `sell_plan` exists.
- `leadership_gate` is not `RS미확인`, `RS약세`, or `RS약함`.
- `trend_template_pass` is `true`.

## TradeGroup Storage

The importer maps candidates to `TradeGroup` rows:

- `candidate_id`
- `scan_date`
- `trade_status`
- `setup_type`
- `planned_entry`
- `planned_stop`
- `planned_risk_pct`
- `pivot_price`
- `buy_zone_low`
- `buy_zone_high`
- `invalidation_price`
- `overlay_snapshot_json`

Initial `trade_status` values:

- `candidate`
- `planned`
- `active`
- `closed`
- `archived`

The first import path is CLI-only:

```powershell
python import_screener_candidates.py --input journal_import_candidates.json
python import_screener_candidates.py --input journal_import_candidates.json --apply
```
