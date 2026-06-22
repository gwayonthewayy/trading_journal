import unittest
from pathlib import Path

class TestAppShellSource(unittest.TestCase):
    def setUp(self):
        self.base_html = Path("app/templates/base.html").read_text(encoding="utf-8")
        self.style_css = Path("app/static/style.css").read_text(encoding="utf-8")

    def test_base_html_structure(self):
        self.assertIn('bottom-nav', self.base_html)
        self.assertIn('매매일지', self.base_html)
        self.assertIn('포트폴리오', self.base_html)
        self.assertIn('분석', self.base_html)
        self.assertIn('aria-current="page"', self.base_html)

        # Cache busting test
        self.assertIn('?v=20260622-a1-4', self.base_html)

        # User Menu CSS isolation
        self.assertIn('id="user-menu-drawer"', self.base_html)
        self.assertIn('user-menu-overlay', self.base_html)
        self.assertIn('user-menu-panel', self.base_html)
        self.assertIn('user-menu-header', self.base_html)
        self.assertIn('user-menu-body', self.base_html)

        # Accessibility and JS
        self.assertIn('aria-hidden="true"', self.base_html)
        self.assertIn(".setAttribute('aria-hidden'", self.base_html)
        self.assertIn("document.body.style.overflow = 'hidden'", self.base_html)
        self.assertIn("e.key === 'Tab'", self.base_html)

        # Inert Focus block, Hidden attr, and Original Body Overflow logic
        self.assertIn(' inert hidden>', self.base_html)
        self.assertIn('drawer.hidden = false', self.base_html)
        self.assertIn('drawer.hidden = true', self.base_html)
        self.assertIn('drawer.inert = false', self.base_html)
        self.assertIn('drawer.inert = true', self.base_html)
        self.assertIn('originalBodyOverflow = document.body.style.overflow', self.base_html)
        self.assertIn('document.body.style.overflow = originalBodyOverflow', self.base_html)

        # Close listeners clearing check
        self.assertIn('clearCloseListeners()', self.base_html)

        # Theme toggle duplicate structure check
        toggle_count = self.base_html.count('id="theme-toggle-btn"')
        self.assertEqual(toggle_count, 2, "Should have 2 theme toggles conditionally rendered")

    def test_style_css_responsiveness(self):
        self.assertIn('@media (max-width: 768px)', self.style_css)
        self.assertIn('@media (min-width: 769px) and (max-width: 980px)', self.style_css)

        # User menu CSS
        self.assertIn('.user-menu-drawer[hidden] {\n  display: none !important;\n}', self.style_css)
        self.assertIn('inset: 0;', self.style_css)
        self.assertIn('max-width: 100%;', self.style_css)

        # Mobile layout fixes
        self.assertIn('grid-template-columns: minmax(0, 1fr) auto;', self.style_css)
        self.assertIn('.brand {\n    min-width: 0;', self.style_css)
        self.assertIn('text-overflow: ellipsis;', self.style_css)
        self.assertIn('width: 44px !important;', self.style_css)
        self.assertIn('height: 44px;', self.style_css)

        # Container/Table containment
        self.assertIn('.topbar, .topbar-inner, .container, .card, .card-head, .table-tool-row, .table-wrap, .chart-wrap', self.style_css)
        self.assertIn('overflow-x: auto;\n    width: 100%;', self.style_css)

        # Safe area height and paddings
        self.assertIn('height: calc(56px + env(safe-area-inset-bottom));', self.style_css)
        self.assertIn('padding-top: env(safe-area-inset-top);', self.style_css)
        self.assertIn('padding-right: env(safe-area-inset-right);', self.style_css)
        self.assertIn('padding-bottom: env(safe-area-inset-bottom);', self.style_css)

        # 100dvh fallback check
        self.assertIn('height: 100dvh;', self.style_css)

        # Check Z-Index
        self.assertIn('z-index: 9999;', self.style_css)

        # Ensure generic `.drawer-` selectors are not defined inside the custom user menu media queries
        mobile_query_part = self.style_css.split('@media (max-width: 768px)')[1]
        self.assertNotIn('.drawer-overlay {', mobile_query_part)
        self.assertIn('.user-menu-overlay', self.style_css)
        self.assertIn('.user-menu-panel', self.style_css)

    def test_portfolio_mobile_columns(self):
        portfolio_html = Path("app/templates/portfolio.html").read_text(encoding="utf-8")
        self.assertIn('[1, 2, 5, 6].includes(index)', portfolio_html)
        self.assertIn('window.innerWidth <= 768', portfolio_html)

    def test_mobile_image_delete_and_quick_attach(self):
        journal_html = Path("app/templates/journal.html").read_text(encoding="utf-8")

        # 1. Quick Image Attach 기본 false
        self.assertIn("{% set ENABLE_QUICK_IMAGE_ATTACH = false %}", journal_html)

        # 2. false일 때 패널/FAB/리스너 비활성화
        self.assertIn("{% if can_write and ENABLE_QUICK_IMAGE_ATTACH %}", journal_html)
        self.assertIn("if (ENABLE_QUICK_IMAGE_ATTACH) {", journal_html)

        # 3. 모바일 table hidden, desktop 유지
        self.assertIn('<div class="table-tool-row hidden-mobile">', journal_html)
        self.assertIn('<div class="table-wrap hidden-mobile">', journal_html)
        self.assertIn('.hidden-mobile {', self.style_css)
        self.assertIn('display: none !important;', self.style_css)

        # 4. long-press 600ms
        self.assertIn("setTimeout(async () => {", journal_html)
        self.assertIn(", 600);", journal_html)

        # 5. 10px 이동 취소
        self.assertIn("Math.sqrt(dx * dx + dy * dy) > 10", journal_html)

        # 6. ADMIN에서만 활성화 (canWrite is true)
        self.assertIn("if (canWrite) {", journal_html)

        # 7. 현재 사진 목록 확인 실패 시 PATCH 금지
        self.assertIn("if (!currentUrls || currentUrls.length === 0) {", journal_html)
        self.assertIn('throw new Error("이벤트 이미지 목록을 가져오지 못했습니다.");', journal_html)

        # 8. contextmenu preventDefault
        self.assertIn('journalMobileCards?.addEventListener("contextmenu", (e) => {', journal_html)
        self.assertIn('e.preventDefault();', journal_html)

        # 9. image_url만 PATCH
        self.assertIn('image_url: nextUrls.length > 0 ? serializeEventImageUrls(nextUrls) : null', journal_html)
