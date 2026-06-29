# PR: Fix QHY174GPS compatibility issues

**Branch:** `fix/qhy174gps-support`  
**Base:** `main`

## Summary

Fixes two issues discovered when running the Alpaca camera server with a QHY174GPS:

## Changes

### 1. `ExpQHYCCDSingleFrame` error handling (`start_exposure`)

The QHY174GPS returns non-zero "pending" status codes from `ExpQHYCCDSingleFrame` that are **not** failures. Only `QHY_ERROR` (0xFFFFFFFF) indicates an actual error. Previously, any non-zero return would raise an exception.

```python
# Before:
if res != QHY_SUCCESS:
    raise RuntimeError("ExpQHYCCDSingleFrame failed")

# After:
if res == QHY_ERROR:
    raise RuntimeError("ExpQHYCCDSingleFrame failed")
```

### 2. Camera state after readout (`_wait_for_image`)

Once the image is buffered in memory, the camera state was left at `DOWNLOADING` (4). This caused subsequent `start_exposure()` calls to fail with "Camera is not idle" if the client never fetched the image via `imagearray`.

Now the state returns to `IDLE` once the frame is ready — the actual download/transfer to the client is handled separately in `image_array`.

## Testing

Verified on QHY174GPS hardware:
- Camera connects successfully via SDK
- Single exposures complete without error
- Back-to-back exposures work (no "not idle" error)
- GPS timestamping functional when locked

## Notes

- `config.yaml` changes (entity name, temperature target) are **not** included — those are deployment-specific.
- The QHY SDK can get stuck if the container is killed without clean shutdown. Use `docker compose down` or ensure `stop_grace_period` is set in docker-compose.yml.
