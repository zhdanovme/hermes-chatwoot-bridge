from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path


class IdempotencyLedger:
    def __init__(self, path: str = ":memory:") -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS processed_events (event_key TEXT PRIMARY KEY, created_at INTEGER NOT NULL)"
        )
        self._db.commit()

    def claim(self, event_key: str) -> bool:
        with self._lock:
            cursor = self._db.execute(
                "INSERT OR IGNORE INTO processed_events(event_key, created_at) VALUES (?, ?)",
                (event_key, int(time.time())),
            )
            self._db.commit()
            return cursor.rowcount == 1

    def release(self, event_key: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM processed_events WHERE event_key = ?", (event_key,))
            self._db.commit()
