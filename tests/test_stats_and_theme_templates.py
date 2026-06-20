import re
import unittest
from pathlib import Path


class StatsTemplateAndThemeTests(unittest.TestCase):
    def setUp(self):
        self.stats_template = Path("app/templates/stats.html").read_text(encoding="utf-8")
        self.style_css = Path("app/static/style.css").read_text(encoding="utf-8")

    def test_stats_template_has_no_temporary_debug_console(self):
        self.assertNotIn("Antigravity Debug", self.stats_template)
        self.assertNotIn("window.addEventListener('error'", self.stats_template)

    def test_stats_template_uses_a_single_render_helper_pattern(self):
        self.assertIn("async function renderApexChartWithLifecycle", self.stats_template)
        self.assertEqual(self.stats_template.count("chart.render();"), 1)
        self.assertNotIn("chart.render();\n    activeCharts", self.stats_template)

    def test_filter_and_image_styles_use_theme_tokens(self):
        selectors = {
            ".th-filter-menu-title": ["color: var(--text);"],
            ".th-filter-option:hover": [
                "background: var(--surface-soft);",
                "border-color: var(--table-border-strong);",
            ],
            ".th-filter-menu-foot": [
                "background: var(--table-th-bg);",
                "border-top: 1px solid var(--table-border);",
            ],
            "#journal-table .event-image-delete": [
                "background: var(--el-bg);",
            ],
        }

        for selector, expected in selectors.items():
            with self.subTest(selector=selector):
                pattern = rf"{re.escape(selector)}\s*\{{(.*?)\n\}}"
                match = re.search(pattern, self.style_css, re.S)
                self.assertIsNotNone(match, f"Missing block for {selector}")
                block = match.group(1)
                for token in expected:
                    self.assertIn(token, block)


if __name__ == "__main__":
    unittest.main()
