from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DeployTemplateTests(unittest.TestCase):
    def test_web_service_uses_intended_checkout_and_project_venv(self):
        unit = (ROOT / "deploy" / "trading-journal.service.example").read_text(
            encoding="utf-8"
        )

        self.assertIn("User=gyu123", unit)
        self.assertIn("Group=gyuedit", unit)
        self.assertIn("WorkingDirectory=/opt/gyu/trading_journal", unit)
        self.assertIn(
            "EnvironmentFile=/opt/gyu/trading_journal/.env.runtime", unit
        )
        self.assertIn(
            "ExecStart=/opt/gyu/trading_journal/.venv/bin/uvicorn "
            "app.main:app --host 127.0.0.1 --port 8000",
            unit,
        )
        self.assertNotIn("/home/soso6079", unit)
        self.assertNotIn("--host 0.0.0.0", unit)


if __name__ == "__main__":
    unittest.main()
