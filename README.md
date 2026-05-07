# rpi3b_adc_step_motor

Raspberry Pi 3B+ Python project to read:

- **DS18B20** temperature sensor via **1-Wire** (Linux sysfs)
- **ADXL345** accelerometer via **SPI** (`spidev`)

`src/main.py` runs **two background threads** (one per sensor) and appends readings to:

- `ds18b20_data.csv`
- `adxl345_data.csv`

## Hardware prerequisites (Pi)

### Enable interfaces

- **SPI**: enable SPI in `raspi-config`
- **1-Wire**: enable 1-Wire in `raspi-config`

### Typical wiring

- **ADXL345 (SPI0, CE0)**
  - SCLK=GPIO11 (pin 23)
  - MOSI=GPIO10 (pin 19)
  - MISO=GPIO9 (pin 21)
  - CE0=GPIO8 (pin 24)
  - Power: **3.3V only**
- **DS18B20 (1-Wire)**
  - Data → GPIO4 (pin 7)
  - **4.7k pull-up** from data to 3.3V

## Python setup

Create a venv and install dependencies (on Raspberry Pi):

```bash
./setup_env.sh
```

Notes:
- DS18B20 uses sysfs reads, so no extra package is required.
- ADXL345 requires `spidev` and SPI enabled.

## Run

From the **project root**:

```bash
python3 -m src.main
```

Stop with `Ctrl+C`. The program handles SIGINT/SIGTERM and will stop both threads cleanly.

## Output files

### `ds18b20_data.csv`

Columns:
- `t`: unix timestamp (seconds)
- `c`: temperature (°C)
- `device_id`: DS18B20 device id (e.g. `28-...`)

### `adxl345_data.csv`

Columns:
- `t`: unix timestamp (seconds)
- `x_g`, `y_g`, `z_g`: acceleration in g

## Configuration

Default settings are in `src/config.py` (`AppConfig`), including:

- DS18B20 poll interval (`ds18b20.poll_s`, `ds18b20.base_path`)
- ADXL345 SPI settings (`adxl345.spi.bus`, `adxl345.spi.device`, speed, mode) and sample rate (`adxl345.sample_hz`)

