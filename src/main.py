"""
ASCOM Alpaca Camera Server - Main FastAPI Application

This is the main entrypoint that:
- Creates the FastAPI application
- Configures logging
- Sets up discovery responder
- Includes routers from management, setup, and camera modules
- Manages camera device lifecycle
- Optionally exposes a filter wheel via the SDK CFW interface
"""

from contextlib import asynccontextmanager
from typing import Dict

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

import camera
import management
import setup
from camera_device import CameraDevice
from cfw_device import CFWDevice
from config import config
from discovery import DiscoveryResponder
from log import get_logger, setup_logging


setup_logging()
logger = get_logger()

# Camera device registry
devices: Dict[int, CameraDevice] = {}

# Filter wheel device registry (optional)
cfw_devices: Dict[int, CFWDevice] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager - startup and shutdown."""
    logger.info(f"Starting {config.entity} on {config.server.host}:{config.server.port}")

    # Initialize camera devices from config
    for device_config in config.devices:
        cam = CameraDevice(device_config, config.library)
        devices[device_config.device_number] = cam
        logger.info(f"Registered camera: {device_config.entity} (device {device_config.device_number})")

    # Initialize filter wheel if configured
    if config.filter_wheel is not None:
        cfw_cfg = config.filter_wheel
        # The CFW shares the camera handle; use the first camera device
        # (or the one matching the CFW's device_number if multiple cameras)
        camera_dev = devices.get(0)
        if camera_dev is not None:
            cfw = CFWDevice(cfw_cfg, camera_dev)
            cfw_devices[cfw_cfg.device_number] = cfw
            logger.info(
                f"Registered filter wheel: {cfw_cfg.entity} "
                f"(device {cfw_cfg.device_number}, via camera handle)"
            )
        else:
            logger.warning("Filter wheel configured but no camera device 0 found")

    # Share device dicts with routers
    camera.set_devices(devices)
    management.set_devices(devices, cfw_devices if cfw_devices else None)

    if cfw_devices:
        import filter_wheel
        filter_wheel.set_devices(cfw_devices)

    # Start discovery responder
    try:
        DiscoveryResponder(config.server.host, config.server.port)
    except Exception as e:
        logger.warning(f"Could not start discovery responder: {e}")

    yield

    # Shutdown: disconnect filter wheels first, then cameras
    for cfw in cfw_devices.values():
        if cfw.connected:
            cfw.disconnect()
    for cam in devices.values():
        if cam.connected:
            cam.disconnect()
    logger.info("Server shutdown")


# Create FastAPI application
app = FastAPI(
    title="ASCOM Alpaca Camera Server",
    description="ASCOM Alpaca API for QHYCCD cameras",
    version="1.0.0",
    lifespan=lifespan
)

@app.exception_handler(RequestValidationError)
async def _alpaca_validation_handler(request: Request, exc: RequestValidationError):
    """Alpaca clients (e.g. ConformU) expect HTTP 400 for malformed
    parameters; FastAPI defaults to 422. Remap so we match the spec."""
    return JSONResponse(status_code=400, content={"detail": exc.errors()})


# Include routers
app.include_router(management.router)
app.include_router(setup.router)
app.include_router(camera.router)

# Include filter wheel router if configured
if config.filter_wheel is not None:
    import filter_wheel
    app.include_router(filter_wheel.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=config.server.host, port=config.server.port, reload=False, access_log=False)
