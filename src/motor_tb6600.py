from __future__ import annotations

import dataclasses
import math
import queue
import threading
import time
from dataclasses import dataclass


try:
    import pigpio  # type: ignore
except Exception:  # pragma: no cover
    pigpio = None


class MotorError(RuntimeError):
    pass


@dataclass(frozen=True)
class SetSpeed:
    steps_per_sec: float  # can be negative for reverse


@dataclass(frozen=True)
class MoveSteps:
    steps: int  # signed
    max_steps_per_sec: float = 1200.0
    accel_steps_per_sec2: float = 3000.0


@dataclass(frozen=True)
class Stop:
    mode: str = "coast"  # "coast" | "decel"


@dataclass(frozen=True)
class Enable:
    enabled: bool


MotorCommand = SetSpeed | MoveSteps | Stop | Enable


@dataclass
class MotorStatus:
    enabled: bool = True
    mode: str = "stopped"  # stopped | continuous | move
    target_steps_per_sec: float = 0.0
    position_steps: int = 0
    last_error: str | None = None


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


class Tb6600MotorController(threading.Thread):
    """
    Background motor controller using pigpio waves for stable STEP pulses.

    Policy (from plan): continuous speed is the background mode. A MoveSteps command
    temporarily ramps to 0, runs the move, then restores the previous speed.
    """

    def __init__(
        self,
        *,
        step_gpio: int = 18,
        dir_gpio: int = 23,
        ena_gpio: int | None = 24,
        invert_dir: bool = False,
        step_pulse_us: int = 5,
        command_q: queue.Queue[MotorCommand] | None = None,
        status: MotorStatus | None = None,
    ):
        super().__init__(daemon=True)
        if pigpio is None:
            raise MotorError("pigpio is not available. Install it on Raspberry Pi and run the pigpio daemon.")

        self._pi = pigpio.pi()
        if not self._pi.connected:
            raise MotorError("Cannot connect to pigpio daemon. Start it with: `sudo pigpiod`")

        self._step = step_gpio
        self._dir = dir_gpio
        self._ena = ena_gpio
        self._invert_dir = invert_dir
        self._pulse_us = max(1, int(step_pulse_us))

        self._cmd_q: queue.Queue[MotorCommand] = command_q or queue.Queue()
        self.status = status or MotorStatus()

        self._stop_evt = threading.Event()
        self._wave_id: int | None = None
        self._current_speed: float = 0.0

        self._setup_gpio()

    @property
    def command_queue(self) -> queue.Queue[MotorCommand]:
        return self._cmd_q

    def _setup_gpio(self) -> None:
        self._pi.set_mode(self._step, pigpio.OUTPUT)
        self._pi.set_mode(self._dir, pigpio.OUTPUT)
        if self._ena is not None:
            self._pi.set_mode(self._ena, pigpio.OUTPUT)
            # Many TB6600 boards use ENA low=enable, but it varies. We'll default to enabled by driving low.
            self._pi.write(self._ena, 0)

        self._pi.write(self._step, 0)
        self._pi.write(self._dir, 0)

    def close(self) -> None:
        self.stop()
        try:
            self.join(timeout=2.0)
        except Exception:
            pass
        self._pi.stop()

    def stop(self) -> None:
        self._stop_evt.set()
        try:
            self._cmd_q.put_nowait(Stop("coast"))
        except Exception:
            pass

    def _set_enabled(self, enabled: bool) -> None:
        self.status.enabled = enabled
        if self._ena is None:
            return
        # Default: drive low to enable
        self._pi.write(self._ena, 0 if enabled else 1)

    def _set_dir(self, forward: bool) -> None:
        val = 1 if forward else 0
        if self._invert_dir:
            val ^= 1
        self._pi.write(self._dir, val)

    def _stop_wave(self) -> None:
        if self._wave_id is not None:
            try:
                self._pi.wave_tx_stop()
            except Exception:
                pass
            try:
                self._pi.wave_delete(self._wave_id)
            except Exception:
                pass
            self._wave_id = None

    def _start_continuous_wave(self, steps_per_sec: float) -> None:
        self._stop_wave()
        if abs(steps_per_sec) < 1e-6:
            self._current_speed = 0.0
            self.status.mode = "stopped"
            return

        forward = steps_per_sec > 0
        self._set_dir(forward)
        sps = abs(steps_per_sec)
        period_us = int(1_000_000 / sps)
        hi_us = min(self._pulse_us, max(1, period_us // 2))
        lo_us = max(1, period_us - hi_us)

        self._pi.wave_add_new()
        pulses = [
            pigpio.pulse(1 << self._step, 0, hi_us),
            pigpio.pulse(0, 1 << self._step, lo_us),
        ]
        self._pi.wave_add_generic(pulses)
        wid = self._pi.wave_create()
        if wid < 0:
            raise MotorError(f"pigpio wave_create failed ({wid})")
        self._wave_id = wid
        self._pi.wave_send_repeat(wid)

        self._current_speed = steps_per_sec
        self.status.mode = "continuous"

    def _ramp_speed(self, target: float, accel: float = 3000.0, dt: float = 0.05) -> None:
        accel = max(1.0, accel)
        while not self._stop_evt.is_set():
            cur = self._current_speed
            if abs(target - cur) < 1.0:
                self._start_continuous_wave(target)
                self.status.target_steps_per_sec = target
                return
            step = accel * dt
            nxt = cur + _clamp(target - cur, -step, step)
            self._start_continuous_wave(nxt)
            self.status.target_steps_per_sec = target
            time.sleep(dt)

    def _emit_steps_blocking(self, steps: int, max_sps: float, accel_sps2: float) -> None:
        steps_total = abs(int(steps))
        if steps_total == 0:
            return

        forward = steps > 0
        self._set_dir(forward)

        max_sps = max(10.0, float(max_sps))
        accel_sps2 = max(100.0, float(accel_sps2))

        # Trapezoid profile in segments (keep waves small).
        # We'll create ~N segments, each with a constant speed for some steps.
        # This is not perfect, but it is stable and simple.
        # Compute ramp steps: v^2 = 2*a*s  -> s = v^2/(2a)
        ramp_steps = int((max_sps * max_sps) / (2.0 * accel_sps2))
        ramp_steps = min(ramp_steps, steps_total // 2)
        cruise_steps = steps_total - 2 * ramp_steps

        def segment_speeds() -> list[tuple[int, float]]:
            segs: list[tuple[int, float]] = []
            # ramp up
            ramp_segs = max(1, min(20, ramp_steps))  # at most 20 segments
            for i in range(ramp_segs):
                # speed increases linearly in segments
                frac0 = i / ramp_segs
                frac1 = (i + 1) / ramp_segs
                s0 = int(round(ramp_steps * frac0))
                s1 = int(round(ramp_steps * frac1))
                n = max(1, s1 - s0)
                v = max_sps * frac1
                segs.append((n, max(20.0, v)))
            # cruise
            if cruise_steps > 0:
                segs.append((cruise_steps, max_sps))
            # ramp down
            for i in range(ramp_segs - 1, -1, -1):
                frac1 = (i + 1) / ramp_segs
                frac0 = i / ramp_segs
                s0 = int(round(ramp_steps * frac0))
                s1 = int(round(ramp_steps * frac1))
                n = max(1, s1 - s0)
                v = max_sps * frac1
                segs.append((n, max(20.0, v)))
            return segs

        remaining = steps_total
        for n_steps, sps in segment_speeds():
            if self._stop_evt.is_set():
                break
            n_steps = min(n_steps, remaining)
            if n_steps <= 0:
                continue
            remaining -= n_steps

            period_us = int(1_000_000 / sps)
            hi_us = min(self._pulse_us, max(1, period_us // 2))
            lo_us = max(1, period_us - hi_us)

            self._pi.wave_add_new()
            pulses = [pigpio.pulse(1 << self._step, 0, hi_us), pigpio.pulse(0, 1 << self._step, lo_us)]
            self._pi.wave_add_generic(pulses)
            wid = self._pi.wave_create()
            if wid < 0:
                raise MotorError(f"pigpio wave_create failed ({wid})")

            self._pi.wave_send_repeat(wid)
            # wait enough time for n_steps to elapse then stop
            time.sleep(n_steps / sps)
            self._pi.wave_tx_stop()
            self._pi.wave_delete(wid)

            if forward:
                self.status.position_steps += n_steps
            else:
                self.status.position_steps -= n_steps

        self._pi.write(self._step, 0)

    def run(self) -> None:
        self.status.last_error = None
        prev_cont_speed: float = 0.0

        while not self._stop_evt.is_set():
            try:
                cmd = self._cmd_q.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                match cmd:
                    case Enable(enabled=enabled):
                        self._set_enabled(enabled)
                        if not enabled:
                            self._start_continuous_wave(0.0)
                    case Stop(mode=_mode):
                        self._start_continuous_wave(0.0)
                    case SetSpeed(steps_per_sec=sps):
                        if not self.status.enabled:
                            continue
                        self.status.target_steps_per_sec = float(sps)
                        self._start_continuous_wave(float(sps))
                        prev_cont_speed = float(sps)
                    case MoveSteps(steps=steps, max_steps_per_sec=max_sps, accel_steps_per_sec2=accel):
                        if not self.status.enabled:
                            continue
                        self.status.mode = "move"
                        # Ramp down background speed, run move, then restore.
                        prev_cont_speed = self._current_speed
                        self._ramp_speed(0.0, accel=max(500.0, accel))
                        self._emit_steps_blocking(int(steps), float(max_sps), float(accel))
                        self._ramp_speed(prev_cont_speed, accel=max(500.0, accel))
                    case _:
                        raise MotorError(f"Unknown command: {cmd!r}")
            except Exception as e:  # keep thread alive
                self.status.last_error = str(e)
                self._start_continuous_wave(0.0)

        self._start_continuous_wave(0.0)
        self._stop_wave()

