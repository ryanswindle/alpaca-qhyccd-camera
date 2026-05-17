"""
ASCOM Alpaca Camera Server - Main FastAPI Application

This is the main entrypoint that:
- Creates the FastAPI application
- Configures logging
- Sets up discovery responder
- Includes routers from management, setup, and camera modules
- Manages camera device lifecycle
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
from config import config
from discovery import DiscoveryResponder
from log import get_logger, setup_logging


setup_logging()
logger = get_logger()

# Camera device registry
devices: Dict[int, CameraDevice] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager - startup and shutdown."""
    logger.info(f"Starting {config.entity} on {config.server.host}:{config.server.port}")
    
    # Initialize camera devices from config
    for device_config in config.devices:
        cam = CameraDevice(device_config, config.library)
        devices[device_config.device_number] = cam
        logger.info(f"Registered camera: {device_config.entity} (device {device_config.device_number})")
    
    # Share cameras dict with routers
    camera.set_devices(devices)
    management.set_devices(devices)
    
    # Start discovery responder
    try:
        DiscoveryResponder(config.server.host, config.server.port)
    except Exception as e:
        logger.warning(f"Could not start discovery responder: {e}")
    
    yield
    
    # Shutdown: disconnect all cameras
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=config.server.host, port=config.server.port, reload=False, access_log=False)
