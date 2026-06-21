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
        
        # User Menu
        self.assertIn('id="user-menu-drawer"', self.base_html)
        self.assertIn('aria-expanded', self.base_html)
        self.assertIn('aria-controls="user-menu-drawer"', self.base_html)
        self.assertIn('id="username-slot"', self.base_html)
        self.assertIn('<span id="username-slot" hidden>', self.base_html)
        self.assertIn('{{ role', self.base_html)
        self.assertNotIn('user_role', self.base_html)

        # JS logic check
        self.assertIn('Escape', self.base_html)
        self.assertIn('.focus()', self.base_html)
        
        # Title hiding
        self.assertIn('hidden-mobile', self.base_html) # Assuming we use a class for this

    def test_style_css_responsiveness(self):
        self.assertIn('@media (max-width: 768px)', self.style_css)
        self.assertIn('height: 64px', self.style_css)
        self.assertIn('env(safe-area-inset-bottom)', self.style_css)
        self.assertIn('padding-bottom', self.style_css)
        self.assertIn('.quick-attach-fab', self.style_css)
