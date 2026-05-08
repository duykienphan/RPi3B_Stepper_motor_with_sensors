from __future__ import annotations

import time
from dataclasses import dataclass


try:
    import pigpio  # type: ignore
except Exception:  # pragma: no cover
    pigpio = None


class MotorError(RuntimeError):
    pass


@dataclass
class MotorStatus:
    enabled: bool = True
    running: bool = False
    direction: int = 0  # +1 forward, -1 reverse, 0 stopped
    steps_sent: int = 0  # signed


class Tb6600Motor:
    """
    Minimal TB6600 stepper controller (PUL/DIR/ENA) using pigpio waves.

    - forward()/reverse(): continuous spin at given speed
    - stop(): stop continuous spin
    - move_steps()/move_revolutions(): blocking move and update counters
    - revolutions(): derived from steps_sent / pulses_per_rev

    Notes:
    - This uses BCM GPIO numbering.
    - pigpio daemon must be running: `sudo pigpiod`
    """

    def __init__(
        self,
        *,
        step_gpio: int,
        dir_gpio: int,
        ena_gpio: int | None,
        pulses_per_rev: int = 1600,
        invert_dir: bool = False,
        step_pulse_us: int = 5,
    ) -> None:
        if pigpio is None:
            raise MotorError("pigpio is not available. Install it on Raspberry Pi and run the pigpio daemon.")
        if pulses_per_rev <= 0:
            raise MotorError("pulses_per_rev must be > 0")

        self._pi = pigpio.pi()
        if not self._pi.connected:
            raise MotorError("Cannot connect to pigpio daemon. Start it with: `sudo pigpiod`")

        self._step = int(step_gpio)
        self._dir = int(dir_gpio)
        self._ena = int(ena_gpio) if ena_gpio is not None else None

        self._invert_dir = bool(invert_dir)
        self._pulse_us = max(1, int(step_pulse_us))
        self._pulses_per_rev = int(pulses_per_rev)

        self.status = MotorStatus()
        self._wave_id: int | None = None

        self._setup_gpio()
        self.enable(True)

    def close(self) -> None:
        try:
            self.stop()
        finally:
            self._pi.stop()

    def _setup_gpio(self) -> None:
        self._pi.set_mode(self._step, pigpio.OUTPUT)
        self._pi.set_mode(self._dir, pigpio.OUTPUT)
        if self._ena is not None:
            self._pi.set_mode(self._ena, pigpio.OUTPUT)

        self._pi.write(self._step, 0)
        self._pi.write(self._dir, 0)
        if self._ena is not None:
            self._pi.write(self._ena, 0)  # default enabled

    def enable(self, enabled: bool) -> None:
        self.status.enabled = bool(enabled)
        if self._ena is None:
            return
        # ENA low=enable
        self._pi.write(self._ena, 0 if enabled else 1)
        if not enabled:
            self.stop()

    def _set_dir(self, forward: bool) -> int:
        val = 1 if forward else 0
        if self._invert_dir:
            val ^= 1
        self._pi.write(self._dir, val)
        return 1 if forward else -1

    def _stop_wave(self) -> None:
        if self._wave_id is None:
            return
        try:
            self._pi.wave_tx_stop()
        except Exception:
            pass
        try:
            self._pi.wave_delete(self._wave_id)
        except Exception:
            pass
        self._wave_id = None

    def _build_wave(self, steps_per_sec: float) -> int:
        sps = abs(float(steps_per_sec))
        if sps <= 0.0:
            raise MotorError("steps_per_sec must be > 0")
        period_us = int(1_000_000 / sps)
        hi_us = min(self._pulse_us, max(1, period_us // 2))
        lo_us = max(1, period_us - hi_us)

        self._pi.wave_add_new()
        self._pi.wave_add_generic(
            [
                pigpio.pulse(1 << self._step, 0, hi_us),
                pigpio.pulse(0, 1 << self._step, lo_us),
            ]
        )
        wid = self._pi.wave_create()
        if wid < 0:
            raise MotorError(f"pigpio wave_create failed ({wid})")
        return wid

    def stop(self) -> None:
        self._stop_wave()
        self._pi.write(self._step, 0)
        self.status.running = False
        self.status.direction = 0

    def forward(self, *, steps_per_sec: float) -> None:
        self._spin(steps_per_sec=float(steps_per_sec), forward=True)

    def reverse(self, *, steps_per_sec: float) -> None:
        self._spin(steps_per_sec=float(steps_per_sec), forward=False)

    def _spin(self, *, steps_per_sec: float, forward: bool) -> None:
        if not self.status.enabled:
            return
        if steps_per_sec <= 0:
            raise MotorError("steps_per_sec must be > 0")

        self.stop()
        self.status.direction = self._set_dir(forward)
        wid = self._build_wave(steps_per_sec)
        self._wave_id = wid
        self._pi.wave_send_repeat(wid)
        self.status.running = True

    def move_steps(self, steps: int, *, steps_per_sec: float) -> None:
        """
        Blocking move of N step pulses.
        Positive steps => forward, negative => reverse.
        """
        if not self.status.enabled:
            return

        n = int(steps)
        if n == 0:
            return
        if steps_per_sec <= 0:
            raise MotorError("steps_per_sec must be > 0")

        # ensure continuous spin is stopped
        self.stop()

        forward = n > 0
        direction = self._set_dir(forward)

        wid = self._build_wave(steps_per_sec)
        try:
            self._pi.wave_send_repeat(wid)
            time.sleep(abs(n) / float(steps_per_sec))
            self._pi.wave_tx_stop()
        finally:
            try:
                self._pi.wave_delete(wid)
            except Exception:
                pass
            self._pi.write(self._step, 0)

        self.status.steps_sent += direction * abs(n)

    def move_revolutions(self, revolutions: float, *, rpm: float) -> None:
        """
        Blocking move of N revolutions (can be negative for reverse).
        """
        revs = float(revolutions)
        if abs(revs) < 1e-12:
            return
        if rpm <= 0:
            raise MotorError("rpm must be > 0")

        steps = int(round(revs * self._pulses_per_rev))
        steps_per_sec = (rpm * self._pulses_per_rev) / 60.0
        self.move_steps(steps, steps_per_sec=steps_per_sec)

    def revolutions(self) -> float:
        return self.status.steps_sent / float(self._pulses_per_rev)


if __name__ == "__main__":
    motor = Tb6600Motor(step_gpio=17, dir_gpio=27, ena_gpio=22)
    motor.forward(steps_per_sec=100)
    time.sleep(1)
    motor.reverse(steps_per_sec=100)
    time.sleep(1)
    motor.stop()
    motor.close()