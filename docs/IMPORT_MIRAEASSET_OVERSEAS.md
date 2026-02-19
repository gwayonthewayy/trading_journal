# Mirae Asset Overseas XLSX Import

This importer loads overseas trade history (`USD`, `HKD`) from Mirae Asset xlsx into the local Trade Journal DB.

## Rules Applied

- `USD` -> `market=US`, `currency=USD`
- `HKD` -> `market=HK`, `currency=HKD`
- If SELL appears before in-file BUY history:
  - available qty = 0: skip that SELL row
  - available qty > 0 but less than sell qty: apply partial sell and ignore extra
- Dedupe against existing DB events is enabled by default.

## Commands (PowerShell)

Dry-run:

```powershell
cd D:\주식\trading_journal
python scripts\import_miraeasset_overseas_xlsx.py --input "D:\주식\25.02.19-26.02.19 해외주식 매매일지.xlsx"
```

Apply:

```powershell
cd D:\주식\trading_journal
python scripts\import_miraeasset_overseas_xlsx.py --input "D:\주식\25.02.19-26.02.19 해외주식 매매일지.xlsx" --apply --allow-nonempty-db
```
