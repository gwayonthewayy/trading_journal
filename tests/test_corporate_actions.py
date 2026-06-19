import unittest
from datetime import datetime

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Event, EventType, Lot, Setting
from app.schemas import BuyRequest
from app.services import create_buy


class BonusIssueTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            session.add(Setting(id=1, base_currency="KRW"))
            buy = create_buy(
                session,
                BuyRequest(
                    ticker="183300",
                    market="KR",
                    currency="KRW",
                    qty=52,
                    price=144_300,
                    symbol_name="코미코",
                    ts=datetime(2026, 5, 20, 9, 1, 54),
                ),
            )
            self.lot_id = int(buy["lot_id"])
            session.commit()

    def test_bonus_issue_preserves_total_cost(self):
        from app.schemas import BonusIssueRequest
        from app.services import create_bonus_issue

        with Session(self.engine) as session:
            result = create_bonus_issue(
                session,
                BonusIssueRequest(
                    lot_id=self.lot_id,
                    additional_qty=52,
                    ts=datetime(2026, 6, 15, 0, 0),
                    source_tag="komico_bonus_20260527",
                    note="1:1 bonus issue",
                ),
            )
            session.commit()
            lot = session.get(Lot, self.lot_id)
            action = session.exec(
                select(Event).where(Event.type == EventType.CORPORATE_ACTION)
            ).one()

        self.assertFalse(result["duplicate"])
        self.assertEqual(result["new_qty"], 104)
        self.assertEqual(result["new_entry_price"], 72_150)
        self.assertEqual(lot.qty_open, 104)
        self.assertEqual(lot.entry_price, 72_150)
        self.assertEqual(action.qty, 52)
        self.assertEqual(action.price, 72_150)
        self.assertEqual(action.reason, "BONUS_ISSUE")

    def test_bonus_issue_source_tag_is_idempotent(self):
        from app.schemas import BonusIssueRequest
        from app.services import create_bonus_issue

        request = BonusIssueRequest(
            lot_id=self.lot_id,
            additional_qty=52,
            ts=datetime(2026, 6, 15, 0, 0),
            source_tag="komico_bonus_20260527",
        )
        with Session(self.engine) as session:
            first = create_bonus_issue(session, request)
            second = create_bonus_issue(session, request)
            session.commit()
            actions = session.exec(
                select(Event).where(Event.type == EventType.CORPORATE_ACTION)
            ).all()

        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(len(actions), 1)


if __name__ == "__main__":
    unittest.main()
