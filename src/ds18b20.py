from __future__ import annotations

import glob
import time
from dataclasses import dataclass
from pathlib import Path


class Ds18b20Error(RuntimeError):
    pass


@dataclass(frozen=True)
class Ds18b20Sample:
    t: float
    c: float
    device_id: str


def _find_devices(base_path: str = "/sys/bus/w1/devices") -> list[Path]:
    pat = str(Path(base_path) / "28-*" / "w1_slave")
    return [Path(p) for p in glob.glob(pat)]


def _parse_w1_slave(text: str) -> float:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        raise Ds18b20Error("Unexpected w1_slave contents")
    if "YES" not in lines[0]:
        raise Ds18b20Error("CRC check failed (w1_slave line 1 not YES)")
    idx = lines[1].find("t=")
    if idx < 0:
        raise Ds18b20Error("Temperature not found in w1_slave")
    milli_c = int(lines[1][idx + 2 :].strip())
    return milli_c / 1000.0


class Ds18b20:
    def __init__(self, *, base_path: str = "/sys/bus/w1/devices"):
        self._base_path = base_path

    def list_device_ids(self) -> list[str]:
        return [p.parent.name for p in _find_devices(self._base_path)]

    def read_c(self, device_id: str | None = None) -> Ds18b20Sample:
        t = time.time()
        if device_id is None:
            devices = _find_devices(self._base_path)
            if not devices:
                raise Ds18b20Error(f"No DS18B20 devices found under {self._base_path!r}")
            path = devices[0]
        else:
            path = Path(self._base_path) / device_id / "w1_slave"
            if not path.exists():
                raise Ds18b20Error(f"Device {device_id!r} not found at {str(path)!r}")

        text = path.read_text(encoding="utf-8", errors="replace")
        c = _parse_w1_slave(text)
        return Ds18b20Sample(t=t, c=c, device_id=path.parent.name)

