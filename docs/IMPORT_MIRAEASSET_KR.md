# Mirae Asset KR XLSX Import

This importer loads Korean stock trade history from broker xlsx into the local Trade Journal DB.

## What It Handles

- Name -> ticker mapping from Naver Finance (`m.stock.naver.com`)
- BUY/SELL split per source row
- FIFO sell allocation
- Skip SELL rows that have no in-file open quantity
- Skip duplicates that already exist in DB:
  - primary: date + ticker + name + side
  - fallback (when names differ): date + ticker + side + qty + price

This matches the case where pre-2025 BUY history is missing and only SELL is present in the file.

## Commands (PowerShell)

Dry-run (no DB write):

```powershell
cd D:\주식\trading_journal
python scripts\import_miraeasset_kr_xlsx.py --input "D:\주식\25.01.01-26.02.19 국장 매매일지.xlsx"
```

Apply import:

```powershell
cd D:\주식\trading_journal
python scripts\import_miraeasset_kr_xlsx.py --input "D:\주식\25.01.01-26.02.19 국장 매매일지.xlsx" --apply
```

If DB already has events and you still want to append:

```powershell
python scripts\import_miraeasset_kr_xlsx.py --input "D:\주식\25.01.01-26.02.19 국장 매매일지.xlsx" --apply --allow-nonempty-db
```

Disable dedupe (usually not needed):

```powershell
python scripts\import_miraeasset_kr_xlsx.py --input "D:\주식\25.01.01-26.02.19 국장 매매일지.xlsx" --apply --allow-nonempty-db --no-dedupe-existing
```

## Notes

- The script uses `--allow-nonempty-db` as an explicit safety override.
- Dedupe is enabled by default; dry-run output shows estimated duplicate BUY/SELL counts.
- Without `--apply`, it is always dry-run and prints summary only.
- Name map cache is stored at `data/cache/naver_kr_name_map.json`.
