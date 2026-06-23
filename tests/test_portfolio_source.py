import unittest
from pathlib import Path

class TestPortfolioSource(unittest.TestCase):
    def setUp(self):
        self.portfolio_html = Path("app/templates/portfolio.html").read_text(encoding="utf-8")
        self.style_css = Path("app/static/style.css").read_text(encoding="utf-8")

    def test_mobile_ux_classes(self):
        # 4. 모바일에서 쓸모없는 Columns 버튼과 데스크톱 double-click 안내를 숨겨라.
        self.assertRegex(self.portfolio_html, r'id="portfolio-col-btn"[^>]*class="[^"]*\bpc-only\b[^"]*"')
        self.assertRegex(self.portfolio_html, r'<p[^>]*class="[^"]*\bpc-only\b[^"]*"[^>]*>Tip: In lot details, double-click')

    def test_market_status_logic(self):
        # 3. market status 분리, localStorage/sessionStorage 성공 상태 유지
        self.assertIn('sessionStorage.setItem("portfolioMarketRefreshSuccess"', self.portfolio_html)
        self.assertIn('sessionStorage.removeItem("portfolioMarketRefreshSuccess"', self.portfolio_html)
        self.assertIn('sessionStorage.getItem("portfolioMarketRefreshSuccess"', self.portfolio_html)

        # 상태 분기 확인 (한국어 통일, stale, error)
        self.assertIn('데이터 갱신 중...', self.portfolio_html)
        self.assertIn('업데이트 완료', self.portfolio_html)
        self.assertIn('데이터 지연', self.portfolio_html)
        self.assertIn('데이터를 불러올 수 없습니다', self.portfolio_html)

        # null validation for quoteAge/fxAge
        self.assertIn('quoteAge === null', self.portfolio_html)
        self.assertIn('fxAge === null', self.portfolio_html)

        # unhandled rejection 방지를 위한 void 처리
        self.assertIn('void loadPortfolioMarketStatus();', self.portfolio_html)

        # entries 없거나 <= 0 검증 분기
        self.assertRegex(self.portfolio_html, r'status\.quote_entries\s*<=\s*0')
        self.assertRegex(self.portfolio_html, r'status\.fx_entries\s*<=\s*0')

    def test_mobile_lot_editing_connection(self):
        # 2. 공통 editLotField 함수로 편집 로직 추출
        self.assertIn('function editLotField(', self.portfolio_html)

        # 데스크톱 기존 double-click 유지
        self.assertIn('portfolioTable?.addEventListener("dblclick"', self.portfolio_html)

        # 모바일 단일 탭 리스너 (클릭)
        self.assertIn('portfolioMobileCardsContainer?.addEventListener("click"', self.portfolio_html)

        # 모바일 div를 tr.portfolio-lot-row로 가정하면 안됨
        self.assertNotIn('const lotRow = cell.closest("tr.portfolio-lot-row");', self.portfolio_html)

    def test_css_overflow_prevention(self):
        # 4. 모바일 UX overflow 방어
        self.assertIn('minmax(0, 1fr)', self.style_css)
        self.assertIn('min-width: 0', self.style_css)
        self.assertIn('overflow-wrap: anywhere', self.style_css)

        # overflow-wrap로 대체하고 word-break: break-all 사용 지양
        mobile_css = self.style_css.split('#portfolio-mobile-cards')[-1] if '#portfolio-mobile-cards' in self.style_css else self.style_css
        self.assertNotIn('word-break: break-all', mobile_css)
