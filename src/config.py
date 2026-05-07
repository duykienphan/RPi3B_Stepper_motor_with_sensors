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
    poll_s: float = 1.0
    base_path: str = "/sys/bus/w1/devices"


@dataclass(frozen=True)
class Tb6600Pins:
    step_gpio: int = 18
    dir_gpio: int = 23
    ena_gpio: int | None = 24


@dataclass(frozen=True)
class StepperConfig:
    pins: Tb6600Pins = Tb6600Pins()
    steps_per_rev: int = 200
    microstep: int = 16
    invert_dir: bool = False
    step_pulse_us: int = 5


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

