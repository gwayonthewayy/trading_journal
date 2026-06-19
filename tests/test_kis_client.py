import unittest


class KisNormalizationTests(unittest.TestCase):
    def test_domestic_fill_is_normalized_and_receipt_is_ignored(self):
        from app.kis_client import normalize_domestic_rows

        rows = [
            {
                "ord_dt": "20260619",
                "odno": "0001234567",
                "pdno": "005930",
                "prdt_name": "삼성전자",
                "sll_buy_dvsn_cd": "02",
                "tot_ccld_qty": "10",
                "avg_prvs": "75000",
                "ccld_tmd": "101530",
                "ccld_yn": "Y",
            },
            {
                "ord_dt": "20260619",
                "odno": "0001234568",
                "pdno": "005930",
                "sll_buy_dvsn_cd": "02",
                "tot_ccld_qty": "0",
                "avg_prvs": "0",
                "ccld_yn": "N",
            },
        ]

        result = normalize_domestic_rows(rows)

        self.assertEqual(len(result), 1)
        fill = result[0]
        self.assertEqual(fill.ticker, "005930")
        self.assertEqual(fill.side, "BUY")
        self.assertEqual(fill.market, "KR")
        self.assertEqual(fill.currency, "KRW")
        self.assertEqual(fill.cumulative_qty, 10.0)
        self.assertEqual(fill.average_price, 75000.0)
        self.assertEqual(fill.executed_at.isoformat(), "2026-06-19T10:15:30")

    def test_overseas_hong_kong_ticker_and_market_are_normalized(self):
        from app.kis_client import normalize_overseas_rows

        rows = [{
            "ord_dt": "20260619",
            "odno": "98765",
            "ovrs_pdno": "09880",
            "ovrs_item_name": "Ubtech Robotics Corp Ltd",
            "sll_buy_dvsn_cd": "01",
            "ft_ccld_qty": "100",
            "ft_ccld_unpr3": "142.5",
            "ovrs_excg_cd": "SEHK",
            "ccld_tmd": "154500",
        }]

        fill = normalize_overseas_rows(rows)[0]

        self.assertEqual(fill.ticker, "9880")
        self.assertEqual(fill.side, "SELL")
        self.assertEqual(fill.market, "HK")
        self.assertEqual(fill.currency, "HKD")
        self.assertEqual(fill.exchange, "HKEX")

    def test_account_hash_never_contains_account_number(self):
        from app.kis_client import account_fingerprint

        digest = account_fingerprint("12345678", "01")

        self.assertEqual(len(digest), 16)
        self.assertNotIn("12345678", digest)


if __name__ == "__main__":
    unittest.main()
