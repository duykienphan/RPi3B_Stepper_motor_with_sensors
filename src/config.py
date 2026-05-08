from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpiConfig:
    bus: int = 0
    device: int = 0  # CE0
    max_hz: int = 5_000_000
    mode: int = 3


@dataclass(frozen=True)
class Adxl345Config:
    spi: SpiConfig = SpiConfig()
    range_g: int = 16  # 2,4,8,16
    odr_hz: float = 200.0
    sample_hz: float = 200.0


@dataclass(frozen=True)
class Ds18b20Config:
    poll_s: float = 1.0                     # polling interval in seconds
    base_path: str = "/sys/bus/w1/devices"  # run `sudo raspi-config` -> Interfacing Options -> OneWire -> Enable


@dataclass(frozen=True)
class Tb6600Pins:
    # GPIO mapping (BCM numbering): PUL=STEP, DIR, ENA
    step_gpio: int = 17
    dir_gpio: int = 27
    ena_gpio: int | None = 22


@dataclass(frozen=True)
class StepperConfig:
    pins: Tb6600Pins = Tb6600Pins()
    steps_per_rev: int = 200
    # TB6600 microstep setting. With a typical 1.8° motor (200 steps/rev),
    # microstep=8 => 200*8 = 1600 pulses per revolution.
    microstep: int = 8
    invert_dir: bool = False
    step_pulse_us: int = 5
    active_high_enable: bool = True


@dataclass(frozen=True)
class LoggingConfig:
    csv_path: str = "run.csv"
    flush_every_n: int = 50


@dataclass(frozen=True)
class AppConfig:
    adxl345: Adxl345Config = Adxl345Config()
    ds18b20: Ds18b20Config = Ds18b20Config()
    stepper: StepperConfig = StepperConfig()
    logging: LoggingConfig = LoggingConfig()

