import unittest
from datetime import date, datetime

from sqlmodel import Session, SQLModel, create_engine, select
from sqlalchemy.pool import StaticPool

from app.kis_client import NormalizedExecution
from app.models import Event, EventType, SellAllocation, Setting


def execution(*, order_no: str = "1", side: str = "BUY", qty: float = 5, price: float = 100, fee: float = 0, tax: float = 0) -> NormalizedExecution:
    return NormalizedExecution(
        trade_date=date(2026, 6, 19),
        order_no=order_no,
        ticker="005930",
        symbol_name="삼성전자",
        side=side,
        market="KR",
        exchange="KRX",
        currency="KRW",
        cumulative_qty=qty,
        average_price=price,
        executed_at=datetime(2026, 6, 19, 10, 0, int(order_no)),
        fee=fee,
        tax=tax,
        raw_payload={"odno": order_no},
    )


class KisReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            session.add(Setting(id=1, base_currency="KRW"))
            session.commit()

    def test_repeated_snapshot_creates_one_event(self):
        from app.kis_sync import ingest_execution

        with Session(self.engine) as session:
            first = ingest_execution(session, "account-hash", execution(), write_events=True)
            second = ingest_execution(session, "account-hash", execution(), write_events=True)
            session.commit()

            events = session.exec(select(Event).where(Event.type == EventType.BUY)).all()

        self.assertEqual(first.outcome, "created")
        self.assertEqual(second.outcome, "duplicate")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].source_broker, "KIS")

    def test_cumulative_fill_applies_only_incremental_quantity_and_price(self):
        from app.kis_sync import ingest_execution

        with Session(self.engine) as session:
            ingest_execution(session, "account-hash", execution(qty=5, price=100), write_events=True)
            result = ingest_execution(session, "account-hash", execution(qty=8, price=115), write_events=True)
            session.commit()
            events = session.exec(select(Event).where(Event.type == EventType.BUY).order_by(Event.id)).all()

        self.assertEqual(result.applied_qty, 3)
        self.assertEqual([event.qty for event in events], [5, 3])
        self.assertAlmostEqual(events[1].price, 140.0)

    def test_sell_is_allocated_fifo_to_existing_buy_lot(self):
        from app.kis_sync import ingest_execution

        with Session(self.engine) as session:
            buy = ingest_execution(session, "account-hash", execution(order_no="1", qty=10), write_events=True)
            sell = ingest_execution(session, "account-hash", execution(order_no="2", side="SELL", qty=4, price=120), write_events=True)
            session.commit()
            sell_event = session.exec(select(Event).where(Event.type == EventType.SELL)).one()
            allocation = session.exec(select(SellAllocation).where(SellAllocation.sell_event_id == sell_event.id)).one()

        self.assertEqual(buy.outcome, "created")
        self.assertEqual(sell.outcome, "created")
        self.assertEqual(allocation.qty_sold, 4)

    def test_sell_without_open_lot_is_preserved_as_pending(self):
        from app.kis_sync import ingest_execution
        from app.models import BrokerExecution

        with Session(self.engine) as session:
            result = ingest_execution(session, "account-hash", execution(side="SELL"), write_events=True)
            session.commit()
            stored = session.exec(select(BrokerExecution)).one()
            events = session.exec(select(Event)).all()

        self.assertEqual(result.outcome, "pending_allocation")
        self.assertEqual(stored.processing_status, "pending_allocation")
        self.assertEqual(stored.applied_qty, 0)
        self.assertEqual(events, [])

    def test_shadow_mode_stores_execution_without_journal_event(self):
        from app.kis_sync import ingest_execution
        from app.models import BrokerExecution

        with Session(self.engine) as session:
            result = ingest_execution(session, "account-hash", execution(), write_events=False)
            session.commit()
            stored = session.exec(select(BrokerExecution)).one()

        self.assertEqual(result.outcome, "observed")
        self.assertEqual(stored.processing_status, "observed")
        self.assertEqual(stored.applied_qty, 0)

    def test_sell_fee_includes_broker_fee_and_tax(self):
        from app.kis_sync import ingest_execution

        with Session(self.engine) as session:
            ingest_execution(session, "account-hash", execution(order_no="1", qty=10), write_events=True)
            ingest_execution(
                session,
                "account-hash",
                execution(order_no="2", side="SELL", qty=4, price=120, fee=3, tax=5),
                write_events=True,
            )
            session.commit()
            sell_event = session.exec(select(Event).where(Event.type == EventType.SELL)).one()

        self.assertEqual(sell_event.fee, 8)


if __name__ == "__main__":
    unittest.main()
