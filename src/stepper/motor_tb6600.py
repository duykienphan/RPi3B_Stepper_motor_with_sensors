from __future__ import annotations

import time
from dataclasses import dataclass


try:
    import RPi.GPIO as GPIO  # type: ignore
except Exception:  # pragma: no cover
    GPIO = None


class MotorError(RuntimeError):
    pass


@dataclass
class MotorStatus:
    enabled: bool = True
    direction: int = 0  # +1 forward, -1 reverse, 0 stopped/unknown
    steps_sent: int = 0  # signed


class Tb6600Motor:
    """
    Minimal TB6600 stepper controller (PUL/DIR/ENA) using RPi.GPIO.

    - forward()/reverse(): drive PUL pin for N pulses (blocking)
    - stop(): disable controller output (ENA)
    - move_steps()/move_revolutions(): blocking move and update counters
    - revolutions(): derived from steps_sent / pulses_per_rev

    Notes:
    - This uses BCM GPIO numbering.
    - This matches the common TB6600 wiring in your script:
      ENA high=enable, DIR low=forward, DIR high=reverse.
    """

    def __init__(
        self,
        *,
        step_gpio: int,
        dir_gpio: int,
        ena_gpio: int | None,
        pulses_per_rev: int = 1600,
        invert_dir: bool = False,
        active_high_enable: bool = True,
    ) -> None:
        if GPIO is None:
            raise MotorError("RPi.GPIO is not available. Install it on Raspberry Pi: `sudo apt install python3-rpi.gpio`")
        if pulses_per_rev <= 0:
            raise MotorError("pulses_per_rev must be > 0")

        self._step = int(step_gpio)
        self._dir = int(dir_gpio)
        self._ena = int(ena_gpio) if ena_gpio is not None else None

        self._invert_dir = bool(invert_dir)
        self._pulses_per_rev = int(pulses_per_rev)
        self._active_high_enable = bool(active_high_enable)

        self.status = MotorStatus()

        self._setup_gpio()
        self.enable(True)

    def close(self) -> None:
        self.stop()
        GPIO.cleanup()

    def _setup_gpio(self) -> None:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self._step, GPIO.OUT)
        GPIO.setup(self._dir, GPIO.OUT)
        if self._ena is not None:
            GPIO.setup(self._ena, GPIO.OUT)

        GPIO.output(self._step, GPIO.LOW)
        GPIO.output(self._dir, GPIO.LOW)
        if self._ena is not None:
            # Default disabled until enable(True) is called.
            GPIO.output(self._ena, GPIO.LOW if self._active_high_enable else GPIO.HIGH)

    def enable(self, enabled: bool) -> None:
        self.status.enabled = bool(enabled)
        if self._ena is None:
            return
        if self._active_high_enable:
            GPIO.output(self._ena, GPIO.HIGH if enabled else GPIO.LOW)
        else:
            GPIO.output(self._ena, GPIO.LOW if enabled else GPIO.HIGH)

    def _set_dir(self, forward: bool) -> int:
        # Match user's script: DIR low=forward, high=reverse
        val = GPIO.LOW if forward else GPIO.HIGH
        if self._invert_dir:
            val = GPIO.HIGH if val == GPIO.LOW else GPIO.LOW
        GPIO.output(self._dir, val)
        return 1 if forward else -1

    def stop(self) -> None:
        self.enable(False)
        GPIO.output(self._step, GPIO.LOW)
        self.status.direction = 0

    def forward(self, pulses: int, *, delay_s: float) -> None:
        self.move_steps(int(pulses), delay_s=float(delay_s))

    def reverse(self, pulses: int, *, delay_s: float) -> None:
        self.move_steps(-int(pulses), delay_s=float(delay_s))

    def move_steps(self, steps: int, *, delay_s: float) -> None:
        """
        Blocking move of N step pulses.
        Positive steps => forward, negative => reverse.

        delay_s matches your script:
        HIGH -> sleep(delay_s) -> LOW -> sleep(delay_s)
        """
        n = int(steps)
        if n == 0:
            return
        if delay_s <= 0:
            raise MotorError("delay_s must be > 0")

        forward = n > 0
        direction = self._set_dir(forward)
        self.status.direction = direction
        self.enable(True)

        for _ in range(abs(n)):
            GPIO.output(self._step, GPIO.HIGH)
            time.sleep(delay_s)
            GPIO.output(self._step, GPIO.LOW)
            time.sleep(delay_s)

        self.status.steps_sent += direction * abs(n)
        self.enable(False)
        self.status.direction = 0

    def move_revolutions(self, revolutions: float, *, delay_s: float) -> None:
        """
        Blocking move of N revolutions (can be negative for reverse).
        """
        revs = float(revolutions)
        if abs(revs) < 1e-12:
            return

        steps = int(round(revs * self._pulses_per_rev))
        self.move_steps(steps, delay_s=float(delay_s))

    def revolutions(self) -> float:
        return self.status.steps_sent / float(self._pulses_per_rev)


if __name__ == "__main__":
    # Demo based on your script (forward/reverse cycles).
    # Pull GPIO mapping + microstep from AppConfig when available.
    try:
        from src.common.config import AppConfig  # type: ignore

        cfg = AppConfig()
        PUL = cfg.stepper.pins.step_gpio
        DIR = cfg.stepper.pins.dir_gpio
        ENA = cfg.stepper.pins.ena_gpio
        PULSES_PER_REV = cfg.stepper.steps_per_rev * cfg.stepper.microstep
    except Exception:
        PUL, DIR, ENA = 17, 27, 22
        PULSES_PER_REV = 1600

    # delay_s is the delay between pulse toggles (speed control).
    # Start conservative; decrease for faster speed.
    DELAY_S = 0.0001
    CYCLES = 3

    motor = Tb6600Motor(
        step_gpio=PUL,
        dir_gpio=DIR,
        ena_gpio=ENA,
        pulses_per_rev=PULSES_PER_REV,
        active_high_enable=True,
    )
    try:
        for i in range(CYCLES):
            motor.forward(PULSES_PER_REV, delay_s=DELAY_S)
            time.sleep(0.5)
            motor.reverse(PULSES_PER_REV, delay_s=DELAY_S)
            time.sleep(0.5)
            print(f"Number of cycles completed: {i + 1}")
            print(f"Number of cycles remaining: {CYCLES - (i + 1)}")
            print(f"Total revolutions (net): {motor.revolutions():.6f}")
    finally:
        motor.close()
        print("Cycling Completed")