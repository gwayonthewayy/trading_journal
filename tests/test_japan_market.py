import unittest
import json
from unittest.mock import patch
from urllib.request import Request


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

    def test_yahoo_chart_quote_uses_browser_user_agent(self):
        from app.services import _fetch_latest_quote_from_yfinance_symbol

        payload = {
            "chart": {
                "result": [{"meta": {"regularMarketPrice": 18_390}}],
                "error": None,
            }
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(payload).encode("utf-8")

        with patch("app.services.urlopen", return_value=FakeResponse()) as mocked:
            price = _fetch_latest_quote_from_yfinance_symbol("4004.T")

        request = mocked.call_args.args[0]
        self.assertIsInstance(request, Request)
        self.assertIn("Mozilla", request.get_header("User-agent"))
        self.assertEqual(price, 18_390)


if __name__ == "__main__":
    unittest.main()
