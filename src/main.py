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
from src.motor_tb6600 import MotorError, Tb6600Motor


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
    motor: Tb6600Motor | None = None

    # Shared state for motor control
    state_lock = threading.Lock()
    latest_x_g: float = 0.0

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

    try:
        motor = Tb6600Motor(
            step_gpio=cfg.stepper.pins.step_gpio,
            dir_gpio=cfg.stepper.pins.dir_gpio,
            ena_gpio=cfg.stepper.pins.ena_gpio,
            pulses_per_rev=cfg.stepper.steps_per_rev * cfg.stepper.microstep,
            invert_dir=cfg.stepper.invert_dir,
            active_high_enable=cfg.stepper.active_high_enable,
        )
    except MotorError:
        motor = None

    ds_csv = "ds18b20_data.csv"
    adxl_csv = "adxl345_data.csv"

    def adxl_fn() -> None:
        assert adxl is not None
        s = adxl.sample()
        nonlocal latest_x_g
        with state_lock:
            latest_x_g = float(s.x_g)
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

    class StepperWorker(threading.Thread):
        def __init__(self) -> None:
            super().__init__(daemon=True, name="Tb6600Worker")
            self._last_cmd: int = 0  # -1,0,+1

        def run(self) -> None:
            if motor is None:
                return
            thr = float(cfg.stepper_control.x_threshold_g)
            batch = max(1, int(cfg.stepper_control.batch_pulses))
            delay_s = max(1e-6, float(cfg.stepper.step_delay_s))
            poll_s = max(0.001, float(cfg.stepper_control.poll_s))

            while not stop_evt.is_set():
                with state_lock:
                    x = float(latest_x_g)

                cmd = 0
                if x > thr:
                    cmd = 1
                elif x < -thr:
                    cmd = -1

                if cmd == 0:
                    if self._last_cmd != 0:
                        motor.stop()
                        self._last_cmd = 0
                    time.sleep(poll_s)
                    continue

                # "Spin" by sending pulses in small batches so direction can change quickly.
                if cmd != self._last_cmd:
                    motor.stop()
                    self._last_cmd = cmd
                    time.sleep(0.05)  # small pause after direction change

                try:
                    motor.move_steps(cmd * batch, delay_s=delay_s)
                except Exception:
                    # Keep thread alive; next loop may recover.
                    time.sleep(0.1)

    stepper_worker: StepperWorker | None = StepperWorker() if motor is not None else None
    if stepper_worker is not None:
        stepper_worker.start()

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
        if stepper_worker is not None:
            stepper_worker.join(timeout=2.0)
        try:
            if adxl is not None:
                adxl.close()
        except Exception:
            pass
        try:
            if motor is not None:
                motor.close()
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

