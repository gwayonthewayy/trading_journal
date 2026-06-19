from __future__ import annotations

import logging
import threading
from datetime import date, timedelta

from sqlmodel import Session

from app.database import engine, init_db
from app.kis_config import load_kis_settings
from app.kis_sync import record_sync_error, run_rest_reconciliation, set_websocket_status
from app.kis_websocket import run_websocket_listener


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger = logging.getLogger("kis-sync")
    settings = load_kis_settings()
    if not settings.sync_enabled:
        logger.error("KIS_SYNC_ENABLED is false; worker will not start")
        return 2

    init_db()
    wake_event = threading.Event()

    def update_websocket_status(status: str) -> None:
        with Session(engine) as status_session:
            set_websocket_status(status_session, status)
            status_session.commit()

    threading.Thread(
        target=run_websocket_listener,
        args=(settings, wake_event, update_websocket_status),
        name="kis-websocket-signal",
        daemon=True,
    ).start()

    first_run = True
    last_reconciled_date: date | None = None
    while True:
        today = date.today()
        start = today - timedelta(days=7) if first_run else today
        if last_reconciled_date is not None and last_reconciled_date < today:
            start = last_reconciled_date
        try:
            with Session(engine) as session:
                summary = run_rest_reconciliation(session, settings, start=start, end=today)
                session.commit()
            logger.info(
                "KIS reconcile fetched=%d created=%d duplicate=%d pending=%d observed=%d",
                summary.fetched, summary.created, summary.duplicates, summary.pending, summary.observed,
            )
            first_run = False
            last_reconciled_date = today
        except Exception as exc:
            with Session(engine) as error_session:
                record_sync_error(error_session, exc)
                error_session.commit()
            logger.error("KIS reconciliation failed: %s", type(exc).__name__)

        wake_event.wait(timeout=settings.poll_seconds)
        wake_event.clear()


if __name__ == "__main__":
    raise SystemExit(main())
