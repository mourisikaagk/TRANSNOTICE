from __future__ import annotations

import logging
import threading
from typing import Callable

from config import Settings
from database.db import connect
from services.collector_service import run_all

log = logging.getLogger(__name__)


class SchedulerService:
    """Wakes up every tick and runs the sources that are due. Each source has its own refresh_minutes."""

    def __init__(self, settings: Settings, clock: Callable):
        self.settings = settings
        self.clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def tick(self) -> dict:
        conn = connect(self.settings.database_path)
        try:
            return run_all(conn, self.settings, self.clock, trigger="scheduler", only_due=True)
        finally:
            conn.close()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("Scheduler tick failed")
            self._stop.wait(self.settings.scheduler_tick_seconds)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="transitnotice-scheduler", daemon=True)
        self._thread.start()
        log.info("Scheduler started (tick every %ss)", self.settings.scheduler_tick_seconds)

    def stop(self) -> None:
        self._stop.set()
