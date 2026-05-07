# python3 -m src.main
from __future__ import annotations

import csv
import signal
import threading
import time
from pathlib import Path

from src.adxl345 import Adxl345, Adxl345Error
from src.config import AppConfig
from src.ds18b20 import Ds18b20, Ds18b20Error


class PeriodicWorker(threading.Thread):
    def __init__(self, *, name: str, period_s: float, fn, stop_evt: threading.Event):
        super().__init__(daemon=True, name=name)
        self._period = max(0.001, float(period_s))
        self._fn = fn
        self._stop_evt = stop_evt

    def run(self) -> None:
        nxt = time.time()
        while not self._stop_evt.is_set():
            now = time.time()
            if now < nxt:
                time.sleep(min(0.05, nxt - now))
                continue
            nxt += self._period
            try:
                self._fn()
            except Exception:
                # Keep worker loop alive even if a read/write fails occasionally.
                continue


def _append_csv_row(path: str, *, fieldnames: list[str], row: dict[str, object]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    exists = p.exists()
    with p.open("a", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=fieldnames)
        if not exists or fp.tell() == 0:
            w.writeheader()
        w.writerow(row)


def run_app(cfg: AppConfig) -> None:
    stop_evt = threading.Event()

    # Sensors
    ds = Ds18b20(base_path=cfg.ds18b20.base_path)
    adxl: Adxl345 | None = None

    try:
        adxl = Adxl345(
            bus=cfg.adxl345.spi.bus,
            device=cfg.adxl345.spi.device,
            max_hz=cfg.adxl345.spi.max_hz,
            mode=cfg.adxl345.spi.mode,
        )
        adxl.configure(range_g=cfg.adxl345.range_g, odr_hz=cfg.adxl345.odr_hz)
        _ = adxl.detect()
    except Exception as e:
        raise Adxl345Error(str(e))

    ds_csv = "ds18b20_data.csv"
    adxl_csv = "adxl345_data.csv"

    def adxl_fn() -> None:
        assert adxl is not None
        s = adxl.sample()
        _append_csv_row(
            adxl_csv,
            fieldnames=["t", "x_g", "y_g", "z_g"],
            row={"t": f"{s.t:.6f}", "x_g": s.x_g, "y_g": s.y_g, "z_g": s.z_g},
        )

    def ds_fn() -> None:
        s = ds.read_c()
        _append_csv_row(
            ds_csv,
            fieldnames=["t", "c", "device_id"],
            row={"t": f"{s.t:.6f}", "c": s.c, "device_id": s.device_id},
        )

    adxl_worker = PeriodicWorker(
        name="Adxl345Worker",
        period_s=1.0 / max(1.0, cfg.adxl345.sample_hz),
        fn=adxl_fn,
        stop_evt=stop_evt,
    )
    ds_worker = PeriodicWorker(
        name="Ds18b20Worker",
        period_s=cfg.ds18b20.poll_s,
        fn=ds_fn,
        stop_evt=stop_evt,
    )
    adxl_worker.start()
    ds_worker.start()

    def _handle(_sig, _frame) -> None:
        stop_evt.set()

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)

    try:
        while not stop_evt.is_set():
            time.sleep(0.2)
    finally:
        stop_evt.set()

        adxl_worker.join(timeout=2.0)
        ds_worker.join(timeout=2.0)
        try:
            if adxl is not None:
                adxl.close()
        except Exception:
            pass


def main() -> None:
    cfg = AppConfig()
    try:
        run_app(cfg)
    except (Adxl345Error, Ds18b20Error) as e:
        raise SystemExit(str(e))


if __name__ == "__main__":
    main()

