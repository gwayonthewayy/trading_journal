import re
import unittest
from pathlib import Path


class StatsTemplateAndThemeTests(unittest.TestCase):
    def setUp(self):
        self.stats_template = Path("app/templates/stats.html").read_text(encoding="utf-8")
        self.base_template = Path("app/templates/base.html").read_text(encoding="utf-8")
        self.journal_template = Path("app/templates/journal.html").read_text(encoding="utf-8")
        self.style_css = Path("app/static/style.css").read_text(encoding="utf-8")

    def test_stats_template_has_no_temporary_debug_console(self):
        self.assertNotIn("Antigravity Debug", self.stats_template)
        self.assertNotIn("window.addEventListener('error'", self.stats_template)

    def test_stats_template_uses_a_single_render_helper_pattern(self):
        self.assertIn("async function renderApexChartWithLifecycle", self.stats_template)
        self.assertEqual(self.stats_template.count("chart.render();"), 1)
        self.assertNotIn("chart.render();\n    activeCharts", self.stats_template)

    def test_stats_template_keeps_korean_copy_and_chart_labels_intact(self):
        expected_copy = [
            # A3: page header now uses M2-first description
            "Method 2(시간가중 수익률)를 기본으로 표시합니다",
            "기간과 벤치마크를 바꿔 수익률 곡선을 비교합니다.",
            # A3: M2 is now primary, M1 secondary
            'name: mode === "cumulative" ? "시간가중 누적 M2" : "시간가중 M2",',
            'name: mode === "cumulative" ? "단순 누적 M1" : "단순 M1",',
        ]

        for text in expected_copy:
            with self.subTest(text=text):
                self.assertIn(text, self.stats_template)

        mojibake_markers = ("?⑥", "?쒖", "?섏", "?먯", "湲곌", "媛", "紐⑤")
        for marker in mojibake_markers:
            with self.subTest(marker=marker):
                self.assertNotIn(marker, self.stats_template)

    def test_stats_chart_colors_come_from_theme_tokens(self):
        self.assertIn("function getChartThemeColors()", self.stats_template)
        self.assertIn("function getChartSeriesColors(holderId, chartTheme)", self.stats_template)
        self.assertIn("colors: getChartSeriesColors(key, chartTheme)", self.stats_template)
        self.assertNotRegex(self.stats_template, r"#[0-9a-fA-F]{3,8}")

    def test_stats_charts_disable_overlapping_data_labels(self):
        self.assertEqual(self.stats_template.count("dataLabels: { enabled: false }"), 4)

    def test_stats_charts_mobile_readability_options(self):
        # A3 Requirement: tick limit, overlap hiding, no rotation
        self.assertIn("hideOverlappingLabels: true,", self.stats_template)
        self.assertIn("tickAmount: 5,", self.stats_template)
        # Verify rotate: 0 is in the responsive options
        self.assertTrue(re.search(r"responsive: \[.*?tickAmount: 5.*?rotate: 0", self.stats_template, re.DOTALL))

    def test_filter_and_image_styles_use_theme_tokens(self):
        selectors = {
            ".th-filter-menu-title": ["color: var(--text);"],
            ".th-filter-menu": ["border: 1px solid var(--table-border-strong);"],
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

    def test_install_banner_uses_theme_tokens(self):
        pattern = r"\.install-banner-inner\s*\{(.*?)\n\}"
        match = re.search(pattern, self.style_css, re.S)
        self.assertIsNotNone(match, "Missing block for .install-banner-inner")
        block = match.group(1)
        self.assertIn("border: 1px solid var(--line-strong);", block)
        self.assertIn("var(--surface-opaque)", block)
        self.assertIn("var(--surface-soft)", block)
        self.assertNotRegex(block, r"#[0-9a-fA-F]{3,8}")

    def test_chart_svg_sizing_does_not_stretch_nested_legend_markers(self):
        self.assertNotIn(".chart-wrap svg {", self.style_css)
        self.assertIn(".chart-wrap > svg {", self.style_css)
        self.assertIn(".chart-wrap > .apexcharts-canvas {", self.style_css)
        self.assertIn("overflow-y: hidden;", self.style_css)
        self.assertIn("width: 100% !important;", self.style_css)

    def test_templates_do_not_hardcode_theme_colors(self):
        self.assertNotRegex(self.base_template, r"#[0-9a-fA-F]{3,8}")
        self.assertNotRegex(self.journal_template, r"#[0-9a-fA-F]{3,8}")


if __name__ == "__main__":
    unittest.main()
