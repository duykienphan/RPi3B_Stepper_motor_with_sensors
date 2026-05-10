from __future__ import annotations

import csv
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LogItem:
    t: float
    kind: str
    data: dict[str, Any]


class CsvLogger(threading.Thread):
    """
    Queue-based CSV logger.

    Output columns:
    - t: unix seconds (float string)
    - kind: sample type ("adxl345", "ds18b20", "motor", ...)
    - data: repr(dict) for flexible payloads
    """

    def __init__(
        self,
        *,
        out_path: str,
        in_q: queue.Queue[LogItem],
        flush_every_n: int = 50,
    ):
        super().__init__(daemon=True)
        self._path = Path(out_path)
        self._q = in_q
        self._flush_every_n = max(1, int(flush_every_n))
        self._stop_evt = threading.Event()
        self._fp = None
        self._writer: csv.DictWriter | None = None
        self._n = 0

    def stop(self) -> None:
        self._stop_evt.set()

    def _open(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fp = self._path.open("a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._fp, fieldnames=["t", "kind", "data"])
        if self._fp.tell() == 0:
            self._writer.writeheader()
            self._fp.flush()

    def run(self) -> None:
        self._open()
        assert self._fp is not None
        assert self._writer is not None

        while not self._stop_evt.is_set():
            try:
                item = self._q.get(timeout=0.2)
            except queue.Empty:
                continue

            self._writer.writerow(
                {
                    "t": f"{item.t:.6f}",
                    "kind": item.kind,
                    "data": repr(item.data),
                }
            )
            self._n += 1
            if self._n % self._flush_every_n == 0:
                self._fp.flush()

        self._fp.flush()
        self._fp.close()

