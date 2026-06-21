import unittest
from datetime import datetime


class MiraeAssetCashflowParsingTests(unittest.TestCase):
    def test_current_statement_external_transfer_is_parsed(self):
        from scripts.import_miraeasset_cashflow_xlsx import _parse_cashflow_pair

        row = {
            1: "2026/04/13",
            2: "이체입금",
            6: 10_000_000,
            13: "신한은행",
            14: "경민규",
        }

        item = _parse_cashflow_pair(row, {}, 653, "general", False, False)

        self.assertEqual(item.signed_krw, 10_000_000)
        self.assertEqual(item.institution, "신한은행")
        self.assertIn("이체입금", item.note)

    def test_current_statement_withdrawal_is_negative(self):
        from scripts.import_miraeasset_cashflow_xlsx import _parse_cashflow_pair

        row = {1: "2026/06/19", 2: "이체출금", 6: 1_500_000, 13: "하나은행"}

        item = _parse_cashflow_pair(row, {}, 10, "general", False, False)

        self.assertEqual(item.signed_krw, -1_500_000)

    def test_internal_transfer_and_stock_settlement_are_excluded(self):
        from scripts.import_miraeasset_cashflow_xlsx import _parse_cashflow_pair

        internal = {1: "2026/04/30", 2: "계좌대체입금", 6: 4_475_504}
        stock = {1: "2026/06/19", 2: "주식매도입금", 6: 6_387_027}

        self.assertIsNone(_parse_cashflow_pair(internal, {}, 1, "general", False, False))
        self.assertIsNone(_parse_cashflow_pair(stock, {}, 2, "general", False, False))


class NaverTickerFallbackTests(unittest.TestCase):
    def test_exact_autocomplete_match_accepts_alphanumeric_ticker(self):
        from scripts.import_miraeasset_kr_xlsx import _ticker_from_autocomplete_payload

        payload = {
            "items": [
                {"code": "0193T0", "name": "KODEX SK하이닉스단일종목레버리지", "nationCode": "KOR"}
            ]
        }

        ticker = _ticker_from_autocomplete_payload("KODEX SK하이닉스단일종목레버리지", payload)

        self.assertEqual(ticker, "0193T0")

    def test_non_exact_name_is_rejected(self):
        from scripts.import_miraeasset_kr_xlsx import _ticker_from_autocomplete_payload

        payload = {"items": [{"code": "123456", "name": "액스비스우", "nationCode": "KOR"}]}

        self.assertIsNone(_ticker_from_autocomplete_payload("액스비스", payload))


class OverseasImporterAggregationTests(unittest.TestCase):
    def test_non_numeric_diagnostics_are_not_aggregated(self):
        from scripts.import_miraeasset_overseas_xlsx import _merge_numeric_result

        aggregated = {"created_buy_events": 0}
        result = {
            "created_buy_events": 3,
            "skipped_sell_events_missing_lot_samples": [{"ticker": "TEST"}],
        }

        _merge_numeric_result(aggregated, result)

        self.assertEqual(aggregated, {"created_buy_events": 3})


class CorporateActionManifestTests(unittest.TestCase):
    def test_manifest_resolves_target_buy_row(self):
        from scripts.import_miraeasset_kr_xlsx import (
            CorporateActionSpec,
            ImportPlan,
            PlannedBuy,
            _target_buy_key,
        )

        plan = ImportPlan(
            events=[
                PlannedBuy(
                    buy_key="buy-57",
                    row_no=57,
                    ts=datetime(2026, 5, 20, 9, 1, 54),
                    ticker="183300",
                    name="코미코",
                    qty=52,
                    price=144_300,
                    fee=0,
                )
            ],
            skipped_sells=[],
            unmapped_names=[],
        )
        action = CorporateActionSpec(
            source_tag="komico_bonus_20260527",
            action_type="BONUS_ISSUE",
            ticker="183300",
            target_buy_row=57,
            effective_ts=datetime(2026, 6, 15, 0, 0),
            additional_qty=52,
            note="1:1 bonus issue",
        )

        self.assertEqual(_target_buy_key(plan, action), "buy-57")


if __name__ == "__main__":
    unittest.main()
