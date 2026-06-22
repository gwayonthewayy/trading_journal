import unittest
from pathlib import Path

class TestPortfolioSource(unittest.TestCase):
    def setUp(self):
        self.portfolio_html = Path("app/templates/portfolio.html").read_text(encoding="utf-8")

    def test_portfolio_status_and_cards(self):
        self.assertIn('class="portfolio-ticker-card"', self.portfolio_html)
        self.assertIn('document.getElementById("portfolio-market-status")', self.portfolio_html)
        self.assertIn('데이터 갱신 중...', self.portfolio_html)
        self.assertIn('업데이트 완료', self.portfolio_html)
