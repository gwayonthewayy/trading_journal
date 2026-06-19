import os
import unittest
from datetime import date, datetime
from unittest.mock import patch

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.kis_client import NormalizedExecution
from app.kis_config import load_kis_settings
from app.models import BrokerSyncState, Setting


class KisAdminStateTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            session.add(Setting(id=1))
            session.add(BrokerSyncState(id=1))
            session.commit()

    def settings(self):
        with patch.dict(os.environ, {}, clear=True):
            return load_kis_settings(load_file=False)

    def test_status_never_exposes_credentials_or_raw_payload(self):
        from app.kis_sync import broker_sync_status, ingest_execution

        item = NormalizedExecution(
            trade_date=date(2026, 6, 19), order_no="1", ticker="AAPL", symbol_name="Apple",
            side="SELL", market="US", exchange="NASDAQ", currency="USD", cumulative_qty=1,
            average_price=200, executed_at=datetime(2026, 6, 19, 23, 30), fee=0, tax=0,
            raw_payload={"secret_like_field": "must-not-leak"},
        )
        with Session(self.engine) as session:
            ingest_execution(session, "account-hash", item, write_events=True)
            session.commit()
            status = broker_sync_status(session, self.settings())

        serialized = str(status)
        self.assertNotIn("must-not-leak", serialized)
        self.assertNotIn("app_secret", serialized.lower())
        self.assertEqual(status["pending_count"], 1)

    def test_pause_state_is_persistent(self):
        from app.kis_sync import set_sync_paused

        with Session(self.engine) as session:
            set_sync_paused(session, True)
            session.commit()
        with Session(self.engine) as session:
            state = session.get(BrokerSyncState, 1)

        self.assertTrue(state.paused)


if __name__ == "__main__":
    unittest.main()
