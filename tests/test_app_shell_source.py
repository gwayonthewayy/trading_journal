import unittest
from pathlib import Path
import re

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

        # Theme toggle duplicate structure check
        toggle_count = self.base_html.count('id="theme-toggle-btn"')
        self.assertEqual(toggle_count, 2, "Should have 2 theme toggles conditionally rendered")

    def test_style_css_responsiveness(self):
        self.assertIn('@media (max-width: 768px)', self.style_css)
        self.assertIn('@media (min-width: 769px) and (max-width: 980px)', self.style_css)

        # Safe area height
        self.assertIn('height: calc(56px + env(safe-area-inset-bottom));', self.style_css)

        # Check Z-Index
        self.assertIn('z-index: 9999;', self.style_css)

        # Ensure generic `.drawer-` selectors are not defined inside the custom user menu media queries
        mobile_query_part = self.style_css.split('@media (max-width: 768px)')[1]
        self.assertNotIn('.drawer-overlay {', mobile_query_part)
        self.assertIn('.user-menu-overlay', self.style_css)
        self.assertIn('.user-menu-panel', self.style_css)
