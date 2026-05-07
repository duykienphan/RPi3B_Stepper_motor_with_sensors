from __future__ import annotations

import queue
import signal
import threading
import time
from dataclasses import asdict

from .adxl345 import Adxl345, Adxl345Error
from .config import AppConfig
from .ds18b20 import Ds18b20, Ds18b20Error
from .logger import CsvLogger, LogItem
from .motor_tb6600 import (
    Enable,
    MoveSteps,
    MotorError,
    MotorStatus,
    SetSpeed,
    Stop,
    Tb6600MotorController,
)


class PeriodicSampler(threading.Thread):
    def __init__(self, *, name: str, period_s: float, fn, out_q: queue.Queue[LogItem]):
        super().__init__(daemon=True, name=name)
        self._period = max(0.001, float(period_s))
        self._fn = fn
        self._q = out_q
        self._stop_evt = threading.Event()

    def stop(self) -> None:
        self._stop_evt.set()

    def run(self) -> None:
        nxt = time.time()
        while not self._stop_evt.is_set():
            now = time.time()
            if now < nxt:
                time.sleep(min(0.05, nxt - now))
                continue
            nxt += self._period
            try:
                item = self._fn()
                self._q.put(item)
            except Exception:
                # keep sampling loop alive even if a read fails occasionally
                continue


def run_app(cfg: AppConfig) -> None:
    log_q: queue.Queue[LogItem] = queue.Queue(maxsize=5000)

    logger = CsvLogger(out_path=cfg.logging.csv_path, in_q=log_q, flush_every_n=cfg.logging.flush_every_n)
    logger.start()

    # Sensors
    adxl = None
    ds = Ds18b20(base_path=cfg.ds18b20.base_path)

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

    def adxl_fn() -> LogItem:
        s = adxl.sample()
        return LogItem(t=s.t, kind="adxl345", data={"x_g": s.x_g, "y_g": s.y_g, "z_g": s.z_g})

    def ds_fn() -> LogItem:
        s = ds.read_c()
        return LogItem(t=s.t, kind="ds18b20", data={"c": s.c, "device_id": s.device_id})

    adxl_sampler = PeriodicSampler(
        name="Adxl345Sampler",
        period_s=1.0 / max(1.0, cfg.adxl345.sample_hz),
        fn=adxl_fn,
        out_q=log_q,
    )
    ds_sampler = PeriodicSampler(name="Ds18b20Sampler", period_s=cfg.ds18b20.poll_s, fn=ds_fn, out_q=log_q)
    adxl_sampler.start()
    ds_sampler.start()

    # Motor
    status = MotorStatus()
    motor = Tb6600MotorController(
        step_gpio=cfg.stepper.pins.step_gpio,
        dir_gpio=cfg.stepper.pins.dir_gpio,
        ena_gpio=cfg.stepper.pins.ena_gpio,
        invert_dir=cfg.stepper.invert_dir,
        step_pulse_us=cfg.stepper.step_pulse_us,
        status=status,
    )
    motor.start()
    motor.command_queue.put(Enable(True))

    stop_evt = threading.Event()

    def _handle(_sig, _frame) -> None:
        stop_evt.set()

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)

    # Demo policy loop:
    # - Start a gentle continuous speed
    # - Every 10 seconds, queue a short move (preempt background, then resume)
    motor.command_queue.put(SetSpeed(steps_per_sec=400.0))
    last_move = time.time()

    try:
        while not stop_evt.is_set():
            time.sleep(0.2)

            # Periodically log motor status
            log_q.put(
                LogItem(
                    t=time.time(),
                    kind="motor",
                    data={
                        "enabled": status.enabled,
                        "mode": status.mode,
                        "target_steps_per_sec": status.target_steps_per_sec,
                        "position_steps": status.position_steps,
                        "last_error": status.last_error,
                    },
                )
            )

            if time.time() - last_move > 10.0:
                last_move = time.time()
                motor.command_queue.put(MoveSteps(steps=800, max_steps_per_sec=1200.0, accel_steps_per_sec2=3000.0))
    finally:
        # Shutdown order: stop samplers, stop motor wave, stop logger.
        adxl_sampler.stop()
        ds_sampler.stop()
        motor.command_queue.put(Stop("coast"))
        motor.stop()

        adxl_sampler.join(timeout=2.0)
        ds_sampler.join(timeout=2.0)
        try:
            motor.join(timeout=2.0)
        except Exception:
            pass

        try:
            motor.close()
        except Exception:
            pass
        try:
            if adxl is not None:
                adxl.close()
        except Exception:
            pass
        logger.stop()
        logger.join(timeout=2.0)


def main() -> None:
    cfg = AppConfig()
    try:
        run_app(cfg)
    except (Adxl345Error, Ds18b20Error, MotorError) as e:
        raise SystemExit(str(e))


if __name__ == "__main__":
    main()

