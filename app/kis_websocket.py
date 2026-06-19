from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import Callable

from app.kis_client import KisClient
from app.kis_config import KisSettings

logger = logging.getLogger(__name__)


async def listen_for_execution_signals(
    settings: KisSettings,
    wake_event: threading.Event,
    status_callback: Callable[[str], None] | None = None,
) -> None:
    """Wake REST reconciliation on notices; never create Journal events here."""
    try:
        import websockets
    except ImportError:
        logger.warning("websockets is unavailable; REST polling remains active")
        return

    client = KisClient(settings)
    approval_key = client.approval_key()
    tr_ids = ("H0STCNI0", "H0GSCNI0") if settings.environment == "real" else ("H0STCNI9", "H0GSCNI9")
    while True:
        try:
            if status_callback:
                status_callback("connecting")
            async with websockets.connect(settings.websocket_url, ping_interval=30, ping_timeout=20) as socket:
                if status_callback:
                    status_callback("connected")
                for tr_id in tr_ids:
                    await socket.send(json.dumps({
                        "header": {"approval_key": approval_key, "custtype": "P", "tr_type": "1", "content-type": "utf-8"},
                        "body": {"input": {"tr_id": tr_id, "tr_key": settings.hts_id}},
                    }))
                async for message in socket:
                    if isinstance(message, str) and "PINGPONG" in message:
                        await socket.send(message)
                        continue
                    wake_event.set()
        except Exception as exc:
            if status_callback:
                status_callback("reconnecting")
            logger.warning("KIS WebSocket disconnected (%s); retrying", type(exc).__name__)
            await asyncio.sleep(5)


def run_websocket_listener(
    settings: KisSettings,
    wake_event: threading.Event,
    status_callback: Callable[[str], None] | None = None,
) -> None:
    asyncio.run(listen_for_execution_signals(settings, wake_event, status_callback))
