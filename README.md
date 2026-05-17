# ASCOM Alpaca Server for QHYCCD cameras (libqhyccd)

A FastAPI-based server, implementing the ASCOM **ICameraV4** interface. Communication is via published QHYCCD library,
which has been tested up to version 25.09.29.

---

## Implemented ICameraV4 capabilities as of this driver version

| Capability           | Supported |
|----------------------|-----------|
| BayerOffsetX         | ✘         |
| BayerOffsetY         | ✘         |
| BinX                 | ✔         |
| BinY                 | ✔         |
| CameraState          | ✔         |
| CameraXSize          | ✔         |
| CameraYSize          | ✔         |
| CanAbortExposure     | ✔         |
| CanAsymmetricBin     | ✘         |
| CanFastReadout       | ✘         |
| CanGetCoolerPower    | ✔         |
| CanPulseGuide        | ✘         |
| CanSetCCDTemperature | ✔         |
| CanStopExposure      | ✘         |
| CCDTemperature       | ✔         |
| CoolerOn             | ✔         |
| CoolerPower          | ✔         |
| ElectronsPerADU      | ✘         |
| ExposureMax          | ✔         |
| ExposureMin          | ✔         |
| ExposureResolution   | ✔         |
| FastReadout          | ✘         |
| FullWellCapacity     | ✔         |
| Gain                 | ✔         |
| GainMax              | ✔         |
| GainMin              | ✔         |
| Gains                | ✘         |
| HasShutter           | ✘         |
| HeatSinkTemperature  | ✘         |
| ImageArray           | ✔         |
| ImageReady           | ✔         |
| IsPulseGuiding       | ✘         |
| LastExposureDuration | ✔         |
| MaxADU               | ✔         |
| MaxBinX              | ✔         |
| MaxBinY              | ✔         |
| NumX                 | ✔         |
| NumY                 | ✔         |
| Offset               | ✔         |
| OffsetMax            | ✔         |
| OffsetMin            | ✔         |
| Offsets              | ✘         |
| PercentCompleted     | ✘         |
| PixelSizeX           | ✔         |
| PixelSizeY           | ✔         |
| ReadoutMode          | ✔         |
| ReadoutModes         | ✔         |
| SensorName           | ✔         |
| SensorType           | ✔         |
| SetCCDTemperature    | ✔         |
| StartX               | ✔         |
| StartY               | ✔         |
| SubExposureDuration  | ✘         |
| AbortExposure        | ✔         |
| PulseGuide           | ✘         |
| StartExposure        | ✔         |
| StopExposure         | ✘         |

Tested on the QHYCCD QHY600M, USB only (no PCIe support).

---

## Architecture

| File               | Purpose                                     |
|--------------------|---------------------------------------------|
| `main.py`          | FastAPI app, lifespan, router wiring        |
| `config.py`        | Pydantic config models, YAML loader         |
| `config.yaml`      | User-editable configuration                 |
| `camera.py`        | FastAPI router – ICameraV4 endpoints        |
| `camera_device.py` | Low-level libqhyccd driver                  |
| `libqhyccd.py`     | Wrappers to libqhyccd library               |
| `management.py`    | `/management` Alpaca management endpoints   |
| `setup.py`         | `/setup` HTML stub pages                    |
| `discovery.py`     | UDP Alpaca discovery responder (port 32227) |
| `responses.py`     | Pydantic response models                    |
| `exceptions.py`    | ASCOM Alpaca error classes                  |
| `shr.py`           | Shared FastAPI dependencies / helpers       |
| `log.py`           | Loguru config + stdlib intercept handler    |
| `test.py`          | Quick smoke-test script                     |
| `requirements.txt` | Python package dependencies                 |
| `Dockerfile`       | Container build                             |

---

## Configuration

Edit `config.yaml` to match your camera setup. Example settings:

- `library`: Path to `libqhyccd.so`
- `devices[].defaults`: Default temperature, readout mode, binning, gain, offset, USB traffic

Camera properties (sensor size, pixel size, gain/offset ranges, exposure limits) are
**queried from the SDK at connection time** — no hardcoding required.

Multiple QHYCCD cameras can be registered by adding further entries under
`devices:` with distinct `device_number` values.

## Quick start

```bash
pip install -r requirements.txt
python main.py
```

The server starts on `0.0.0.0:5000` by default (configurable in `config.yaml`).

---

## Smoke test

```bash
# Requires hardware connected, i.e. will operate camera
python test.py
```

---

## Docker

```bash
docker build -t alpaca-qhyccd-camera .
docker run -d --name alpaca-qhyccd-camera \
    -v ./config.yaml:/alpyca/config.yaml:ro \
    --privileged -v /dev/bus/usb:/dev/bus/usb \
    -v /usr/local/lib/libqhyccd.so:/usr/local/lib/libqhyccd.so:ro \
    -v /usr/local/lib/libqhyccd.so.20:/usr/local/lib/libqhyccd.so.20:ro \
    -v /usr/local/lib/libqhyccd.so.25.9.29.10:/usr/local/lib/libqhyccd.so.25.9.29.10:ro \
    --network host \
    --restart unless-stopped \
    alpaca-qhyccd-camera
docker logs -f alpaca-qhyccd-camera
```

---

## ASCOM Conformance

<!-- conformu:start -->
Last tested with **ConformU 4.3.0 (Build 49708.0503dc7)** on 2026-05-16
(`python test_conformu.py`):

| Device | Errors | Issues | Info | Status |
|--------|:------:|:------:|:----:|:------:|
| QHY600M_1 (Camera #0) | 1 | 0 | 263 | ✓ PASS |

_Errors may be non-zero when no hardware is attached (NotConnectedException is the expected response). **Issues == 0** indicates Alpaca protocol conformance._
<!-- conformu:end -->
