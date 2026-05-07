from __future__ import annotations

import time

from .adxl345 import Adxl345
from .config import AppConfig
from .ds18b20 import Ds18b20
from .motor_tb6600 import Enable, MoveSteps, SetSpeed, Stop, Tb6600MotorController


def main() -> None:
    cfg = AppConfig()

    print("=== ADXL345 ===")
    adxl = Adxl345(
        bus=cfg.adxl345.spi.bus,
        device=cfg.adxl345.spi.device,
        max_hz=cfg.adxl345.spi.max_hz,
        mode=cfg.adxl345.spi.mode,
    )
    try:
        devid = adxl.detect()
        print(f"DEVID=0x{devid:02X} (expected 0xE5)")
        adxl.configure(range_g=cfg.adxl345.range_g, odr_hz=cfg.adxl345.odr_hz)
        for _ in range(5):
            s = adxl.sample()
            print(f"t={s.t:.3f} x={s.x_g:+.3f}g y={s.y_g:+.3f}g z={s.z_g:+.3f}g")
            time.sleep(0.05)
    finally:
        adxl.close()

    print("\n=== DS18B20 ===")
    ds = Ds18b20(base_path=cfg.ds18b20.base_path)
    ids = ds.list_device_ids()
    print(f"devices={ids}")
    s = ds.read_c()
    print(f"t={s.t:.3f} temp={s.c:.3f}C id={s.device_id}")

    print("\n=== TB6600 stepper (very slow) ===")
    motor = Tb6600MotorController(
        step_gpio=cfg.stepper.pins.step_gpio,
        dir_gpio=cfg.stepper.pins.dir_gpio,
        ena_gpio=cfg.stepper.pins.ena_gpio,
        invert_dir=cfg.stepper.invert_dir,
        step_pulse_us=cfg.stepper.step_pulse_us,
    )
    motor.start()
    try:
        motor.command_queue.put(Enable(True))
        motor.command_queue.put(SetSpeed(steps_per_sec=200.0))
        time.sleep(2.0)
        motor.command_queue.put(MoveSteps(steps=400, max_steps_per_sec=600.0, accel_steps_per_sec2=2000.0))
        time.sleep(3.0)
        motor.command_queue.put(SetSpeed(steps_per_sec=-200.0))
        time.sleep(2.0)
        motor.command_queue.put(Stop("coast"))
        time.sleep(0.5)
    finally:
        motor.stop()
        motor.close()

    print("\nValidation complete.")


if __name__ == "__main__":
    main()

