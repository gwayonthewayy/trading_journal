import os
import unittest
from unittest.mock import patch


class KisSettingsTests(unittest.TestCase):
    def test_defaults_are_disabled_and_paper_only(self):
        from app.kis_config import load_kis_settings

        with patch.dict(os.environ, {}, clear=True):
            settings = load_kis_settings(load_file=False)

        self.assertEqual(settings.environment, "paper")
        self.assertFalse(settings.sync_enabled)
        self.assertFalse(settings.write_events)
        self.assertFalse(settings.order_enabled)

    def test_order_enable_is_rejected(self):
        from app.kis_config import load_kis_settings

        with patch.dict(os.environ, {"KIS_ORDER_ENABLED": "true"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "must remain false"):
                load_kis_settings(load_file=False)

    def test_enabled_sync_requires_selected_credentials(self):
        from app.kis_config import load_kis_settings

        with patch.dict(os.environ, {"KIS_SYNC_ENABLED": "true"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "KIS_PAPER_APP_KEY"):
                load_kis_settings(load_file=False)


if __name__ == "__main__":
    unittest.main()
