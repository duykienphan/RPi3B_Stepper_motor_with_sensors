from __future__ import annotations

import time
from dataclasses import dataclass


try:
    import spidev  # type: ignore
except Exception:  # pragma: no cover
    spidev = None


class Adxl345Error(RuntimeError):
    pass


class Reg:
    DEVID = 0x00
    BW_RATE = 0x2C
    POWER_CTL = 0x2D
    INT_ENABLE = 0x2E
    INT_MAP = 0x2F
    DATA_FORMAT = 0x31
    DATAX0 = 0x32


_RANGE_TO_DATA_FORMAT = {
    2: 0x00,
    4: 0x01,
    8: 0x02,
    16: 0x03,
}


def _odr_to_bw_rate(odr_hz: float) -> int:
    # ADXL345 BW_RATE codes. We'll choose the closest supported.
    table = [
        (0.10, 0x00),
        (0.20, 0x01),
        (0.39, 0x02),
        (0.78, 0x03),
        (1.56, 0x04),
        (3.13, 0x05),
        (6.25, 0x06),
        (12.5, 0x07),
        (25.0, 0x08),
        (50.0, 0x09),
        (100.0, 0x0A),
        (200.0, 0x0B),
        (400.0, 0x0C),
        (800.0, 0x0D),
        (1600.0, 0x0E),
        (3200.0, 0x0F),
    ]
    best = min(table, key=lambda x: abs(x[0] - odr_hz))
    return best[1]


@dataclass(frozen=True)
class Adxl345Sample:
    t: float
    x_g: float
    y_g: float
    z_g: float


class Adxl345:
    """
    Minimal ADXL345 SPI driver (register-level).

    Notes:
    - SPI reads use (0x80 | reg) and multi-byte reads use (0xC0 | reg).
    - We configure FULL_RES so scale is ~3.9 mg/LSB (independent of range).
    """

    def __init__(self, *, bus: int = 0, device: int = 0, max_hz: int = 5_000_000, mode: int = 3):
        if spidev is None:
            raise Adxl345Error("spidev is not available. Install it on Raspberry Pi and enable SPI.")

        self._spi = spidev.SpiDev()
        self._spi.open(bus, device)
        self._spi.max_speed_hz = max_hz
        self._spi.mode = mode

    def close(self) -> None:
        try:
            self._spi.close()
        except Exception:
            pass

    def read_reg(self, reg: int, n: int = 1) -> list[int]:
        if n <= 0:
            return []
        addr = (0xC0 if n > 1 else 0x80) | (reg & 0x3F)
        resp = self._spi.xfer2([addr] + [0x00] * n)
        return resp[1:]

    def write_reg(self, reg: int, value: int) -> None:
        addr = reg & 0x3F
        self._spi.xfer2([addr, value & 0xFF])

    def detect(self) -> int:
        return self.read_reg(Reg.DEVID, 1)[0]

    def configure(self, *, range_g: int = 16, odr_hz: float = 200.0) -> None:
        if range_g not in _RANGE_TO_DATA_FORMAT:
            raise Adxl345Error(f"Unsupported range_g={range_g}. Choose one of {sorted(_RANGE_TO_DATA_FORMAT)}")

        # Standby
        self.write_reg(Reg.POWER_CTL, 0x00)
        time.sleep(0.01)

        bw = _odr_to_bw_rate(odr_hz)
        self.write_reg(Reg.BW_RATE, bw)

        # FULL_RES (bit3) + range bits
        data_format = 0x08 | _RANGE_TO_DATA_FORMAT[range_g]
        self.write_reg(Reg.DATA_FORMAT, data_format)

        # Measure mode
        self.write_reg(Reg.POWER_CTL, 0x08)
        time.sleep(0.01)

    @staticmethod
    def _to_int16(lo: int, hi: int) -> int:
        v = (hi << 8) | lo
        return v - 0x10000 if v & 0x8000 else v

    def read_xyz_raw(self) -> tuple[int, int, int]:
        b = self.read_reg(Reg.DATAX0, 6)
        x = self._to_int16(b[0], b[1])
        y = self._to_int16(b[2], b[3])
        z = self._to_int16(b[4], b[5])
        return x, y, z

    def read_xyz_g(self) -> tuple[float, float, float]:
        x, y, z = self.read_xyz_raw()
        # FULL_RES scale ~ 3.9 mg/LSB = 0.0039 g/LSB
        scale = 0.0039
        return x * scale, y * scale, z * scale

    def sample(self) -> Adxl345Sample:
        t = time.time()
        xg, yg, zg = self.read_xyz_g()
        return Adxl345Sample(t=t, x_g=xg, y_g=yg, z_g=zg)

