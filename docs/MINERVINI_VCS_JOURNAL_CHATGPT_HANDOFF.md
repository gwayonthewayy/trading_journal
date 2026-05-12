# Minervini VCS / Trading Journal Design Handoff

This document is the public, self-contained handoff for ChatGPT design review.

The VCS screener repository may be private or unavailable to the ChatGPT GitHub
connector, so the important implementation context is summarized here inside the
public `trading_journal` repository.

## Current Access Issue

The local VCS screener repository is configured as:

- Local path: `D:\workspace\vcs_screener`
- Remote: `https://github.com/gwayonthewayy/vcs-screener.git`
- Branch: `main`
- Latest pushed commit: `959dab7 feat: add minervini overlay workflow`

If the GitHub web link returns `404 Not Found`, the likely cause is one of:

- The `vcs-screener` repository is private.
- The ChatGPT GitHub app or connector does not have access to that repository.
- The user is logged into a GitHub account that cannot view the repository.

The trading journal repository is available here:

- Repo: https://github.com/gwayonthewayy/trading_journal
- Latest relevant commit: https://github.com/gwayonthewayy/trading_journal/commit/6735bd0

## Goal

Turn the Mark Minervini study work into a practical operating loop:

1. The VCS screener finds KR/US candidates.
2. A Minervini overlay classifies each candidate by trend, leadership, setup,
   entry zone, risk, and sell plan.
3. The daily briefing exposes the classification in a compact decision format.
4. The trading journal records execution quality, R multiple, rule compliance,
   mistake tags, and post-trade review.
5. The loop separates good losses from rule-breaking losses.

This is for personal analysis and process discipline, not automated investment
advice.

## Copyright Boundary

The Minervini ebook material was not copied into the repository.

The local notes are transformed operating rules, checklists, and implementation
guidance. They should remain paraphrased and should not reproduce long source
passages from the books.

## Minervini Study Files

Created under the VCS screener repository:

- `docs/minervini/README.md`
- `docs/minervini/playbook.md`
- `docs/minervini/champion_rules.md`
- `docs/minervini/daily_checklist.md`
- `docs/minervini/source_map.md`
- `docs/minervini/automation_backlog.md`
- `docs/minervini/CHATGPT_DESIGN_HANDOFF.md`

High-level content:

- `playbook.md`: canonical candidate selection, entry, risk, sell, and review
  rules.
- `champion_rules.md`: practical trade-management rules from the second book.
- `daily_checklist.md`: yes/no checklist for market condition, trend, relative
  strength, setup quality, entry, stop, sizing, and review.
- `automation_backlog.md`: implementation plan for screener columns, briefing
  fields, journal fields, VCP/time-series scoring, and later calibration.

Core operating principles extracted into the local rule set:

- Buy only when the market, trend, leadership, setup, and risk are aligned.
- Prefer stocks near highs with strong relative strength and institutional
  sponsorship signals.
- Treat VCP/base quality as a risk filter, not just a pattern label.
- Define invalidation before entry.
- Avoid averaging down.
- Reduce size after repeated failed breakouts or repeated rule violations.
- Review trades by process quality, not only profit/loss.

## VCS Screener Work

Main local files changed in `D:\workspace\vcs_screener`:

- `minervini_overlay.py`
- `build_deep_minervini_briefing.py`
- `docs/minervini/*`

Commit:

- `959dab7 feat: add minervini overlay workflow`

Commit stat:

- `build_deep_minervini_briefing.py`: integrated overlay into briefing exports.
- `minervini_overlay.py`: added standalone overlay engine and CLI.
- `docs/minervini/*`: added study notes, checklist, source map, backlog, and
  design handoff.

The overlay adds these fields to existing VCS result CSVs:

- `trend_template_pass`
- `trend_template_fail_reasons`
- `leadership_gate`
- `entry_zone_label`
- `base_quality_label`
- `risk_first_status`
- `rr_status`
- `sizing_note`
- `plan_status`
- `sell_plan`
- `trade_stance`
- `minervini_summary`

Standalone usage:

```powershell
python minervini_overlay.py `
  --input-csv results\<MMDD>_CODEX\<candidate_file>.csv `
  --output-csv results\<MMDD>_CODEX\<candidate_file>_minervini_overlay.csv `
  --output-md results\<MMDD>_CODEX\<candidate_file>_minervini_overlay.md
```

Verified locally:

```powershell
python -m py_compile minervini_overlay.py build_deep_minervini_briefing.py
python minervini_overlay.py --input-csv results\0512_CODEX\0512_CODEX_KR_filter_candidates_with_rs.csv --output-csv results\0512_CODEX\0512_CODEX_KR_filter_candidates_with_rs_minervini_overlay.csv --output-md results\0512_CODEX\0512_CODEX_KR_filter_candidates_with_rs_minervini_overlay.md
```

## Overlay Logic Summary

`minervini_overlay.py` is designed as a post-processing layer over existing VCS
candidate CSV files.

It does not replace the original screener. It adds an explicit decision layer so
the briefing can say whether a candidate is actionable, watchlist-only, extended,
weak, or excluded.

Important behavior:

- It normalizes likely column names across KR/US outputs.
- It computes a price-trend template using available moving averages, high/low
  proximity, and price position.
- It treats relative strength as a leadership gate when RS data exists.
- It labels entry quality using pivot/proximity/extension fields when available.
- It labels base quality using CSV-level proxies such as setup text, contraction
  hints, distance from pivot, and extension.
- It creates risk-first outputs: stop logic, risk/reward status, sizing note,
  and sell-plan text.
- It sorts candidates by stance, VCS score, RS score, and final score when those
  fields are available.

Current limitation:

- `base_quality_label` is still a cheap proxy because the overlay only sees the
  exported CSV. True VCP quality should eventually use historical price/volume
  time series: contraction count, contraction depth, volume dry-up, pivot
  tightness, failed breakout history, and breakout volume.

## Briefing Integration

`build_deep_minervini_briefing.py` now imports:

```python
from minervini_overlay import add_minervini_overlay
```

The candidate flow applies:

```python
kr = add_minervini_overlay(add_ranking(add_classification(kr, "KR")))
us = add_minervini_overlay(add_ranking(add_classification(us, "US")))
```

The briefing text now includes:

- `trade_stance`
- `leadership_gate`
- `base_quality_label`
- `risk_first_status`
- `rr_status`
- `sell_plan`

The goal is to make the daily briefing less like a raw score list and more like
a trade-readiness review.

## Trading Journal Work

Repository:

- `D:\주식\trading_journal`
- https://github.com/gwayonthewayy/trading_journal

Commit:

- https://github.com/gwayonthewayy/trading_journal/commit/6735bd0
- `6735bd0 feat: add minervini trade review fields`

Files changed:

- `app/models.py`
- `app/schemas.py`
- `app/database.py`
- `app/services.py`
- `app/templates/trade_detail.html`
- `app/static/style.css`

Added `TradeGroup` review fields:

- `setup_type`
- `planned_entry`
- `planned_stop`
- `planned_risk_pct`
- `realized_r`
- `rule_compliance`
- `mistake_tag`
- `minervini_checklist`

The app adds these SQLite columns at startup through the compatibility schema
migration in `app/database.py`.

The trade detail page now allows the user to record:

- setup type such as VCP, breakout, pullback, failed breakout, or other custom
  text
- planned entry
- planned stop
- planned risk percent
- realized R
- rule compliance
- mistake tag
- Minervini checklist or VCS overlay snapshot

Verified locally:

```powershell
python -m py_compile app\models.py app\schemas.py app\database.py app\services.py app\main.py
```

Template loading was also checked with Jinja for:

- `trade_detail.html`
- `journal.html`

## Sensitive Data Boundary

Do not commit or request these files:

- `.env.runtime`
- `data/db.sqlite`
- `data/uploads`
- `runtime_bundle*.zip`
- `trading_data.zip`

The real trading data exists outside Git and is restored separately from:

- `D:\workspace\runtime_bundle_latest.zip`

## Design Questions For ChatGPT

Please review the following design choices.

1. Should `minervini_overlay.py` remain a separate post-processing layer, or
   should the logic be folded into the main screener / full-market scan pipeline?

2. Is it better to keep `base_quality_label` as a simple CSV-based proxy for
   now, or should the next step be a true time-series VCP module?

3. Should candidates with missing RS data be treated as watchlist-only instead
   of allowing them to pass as uncertain?

4. Should the trading journal store screener overlay snapshots as structured
   columns, a JSON blob, or plain checklist text?

5. What is the best import path from VCS screener CSV to trading journal trade
   group?

6. Which fields should be mandatory before a trade can be marked as planned or
   actionable?

7. How should the system score process quality separately from trade outcome?

8. How should the journal detect repeated rule violations and trigger automatic
   size reduction or trading pause warnings?

## Proposed Next Architecture

A practical next version could use this flow:

1. VCS screener exports candidate CSV.
2. Minervini overlay enriches the CSV.
3. Daily briefing selects only the top actionable/watchlist candidates.
4. User chooses candidates to import into the journal as planned trade groups.
5. Journal stores the overlay snapshot at plan time.
6. After execution, journal calculates realized R and compares outcome against
   planned entry/stop.
7. Review dashboard separates:
   - profitable and rule-compliant trades
   - losing but rule-compliant trades
   - profitable but rule-breaking trades
   - losing and rule-breaking trades

This should make the system useful for training discipline, not just finding
tickers.

## What To Ask ChatGPT

Paste this file link into ChatGPT and ask:

```text
이 문서를 읽고 Minervini식 VCS screener + trading_journal 통합 설계를 검토해줘.
특히 overlay를 별도 계층으로 둘지, VCP/time-series 모듈을 어떻게 붙일지,
그리고 screener CSV에서 journal trade group으로 가져오는 데이터 모델을 어떻게
설계하는 게 좋은지 봐줘.
```
