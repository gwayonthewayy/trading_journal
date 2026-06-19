import unittest


class JapanMarketTests(unittest.TestCase):
    def test_jpy_maps_to_japan(self):
        from scripts.import_miraeasset_overseas_xlsx import (
            _market_currency_from_source_currency,
        )

        self.assertEqual(_market_currency_from_source_currency("JPY"), ("JP", "JPY"))

    def test_japan_quote_symbol_uses_t_suffix(self):
        from app.services import _quote_symbol_candidates

        self.assertEqual(_quote_symbol_candidates("4004", "JP"), ["4004.T"])
        self.assertEqual(_quote_symbol_candidates("4004.T", "JP"), ["4004.T"])

    def test_yen_currency_symbol(self):
        from app.services import _currency_symbol

        self.assertEqual(_currency_symbol("JPY"), "¥")

    def test_japan_exchange_is_tse(self):
        from scripts.import_miraeasset_overseas_xlsx import _exchange_from_market

        self.assertEqual(_exchange_from_market("JP"), "TSE")


if __name__ == "__main__":
    unittest.main()
