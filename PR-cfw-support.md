# PR: Add optional filter wheel support via SDK CFW interface

**Branch:** `feature/cfw-support`  
**Base:** `fix/qhy174gps-support` (or `main` if that's merged first)

## Summary

Adds ASCOM Alpaca FilterWheel (IFilterWheelV3) endpoints to the camera server for filter wheels connected via the 4-pin CFW cable. The filter wheel is controlled through the camera's SDK handle — no separate serial port or USB adapter required.

## Motivation

QHY cameras with a 4-pin CFW port (e.g. QHY174GPS, QHY600M) can drive a filter wheel directly through `libqhyccd`. This avoids needing a separate serial-based filter wheel service and keeps both devices managed through a single Alpaca server instance.

## Changes

### New files

| File | Description |
|------|-------------|
| `src/cfw_device.py` | CFW driver class using SDK functions: `IsQHYCCDCFWPlugged`, `SendOrder2QHYCCDCFW`, `GetQHYCCDCFWStatus` |
| `src/filter_wheel.py` | Full IFilterWheelV3 Alpaca router at `/api/v1/filterwheel/{devnum}/...` |
| `config.example.yaml` | Annotated example config showing filter wheel syntax (commented out) |

### Modified files

| File | Change |
|------|--------|
| `src/config.py` | Added `CFWConfig` model; added optional `filter_wheel` field to `Config` |
| `src/main.py` | Registers CFW device and filter wheel router when `filter_wheel:` is in config; disconnects CFW before camera on shutdown |
| `src/management.py` | Includes filter wheel in `/management/v1/configureddevices` response |

## Usage

Add a `filter_wheel:` section to `config.yaml`:

```yaml
filter_wheel:
  entity: QHYFilterWheel
  device_number: 0
  names:
    - Sloan-u
    - Sloan-g
    - Sloan-r
    - Sloan-i
    - Sloan-z
    - Luminance
  focus_offsets:
    - 0
    - 0
    - 0
    - 0
    - 0
    - 0
  timeout: 60
```

Omit the section entirely to run without filter wheel support (no code paths change, router is not registered).

## API Endpoints

All standard IFilterWheelV3 endpoints at `/api/v1/filterwheel/0/`:

- `PUT connected` — connect (camera must be connected first)
- `GET connected` / `GET connecting`
- `GET names` / `GET focusoffsets`
- `GET position` — returns 0-based index, or -1 while moving
- `PUT position` — command a move (async, returns immediately)
- `GET devicestate` / `GET description` / `GET driverinfo` / etc.

## Important Notes

- **Connect order matters**: the camera must be connected before the filter wheel, since the CFW device borrows the camera's SDK handle.
- **Single server**: both camera and filter wheel are served on the same port (e.g. 5900). No separate service/container needed.
- **Backward compatible**: without the `filter_wheel:` config section, the server behaves identically to before.

## Testing

Verified on QHY174GPS + QHY CFW3 hardware:
- Filter wheel detected via `IsQHYCCDCFWPlugged`
- Position reads correctly via `GetQHYCCDCFWStatus`
- Moves complete and poll correctly (position returns -1 during move)
- Back-to-back moves work
- Camera exposures still work independently while filter wheel is connected
