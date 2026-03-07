from typing import Dict

from fastapi import APIRouter
from pydantic import BaseModel

from config import config
from responses import PropertyResponse


router = APIRouter(prefix="/management", tags=["Management"])


class ConfiguredDevice(BaseModel):
    DeviceName: str
    DeviceType: str
    DeviceNumber: int


class ServerDescription(BaseModel):
    ServerName: str
    Manufacturer: str
    Version: str
    Location: str


class ServerMetadata:
    Name = "QHYCCD Camera Alpaca Server"
    Manufacturer = "SensorKit"
    Version = "1.0.0"


devices: Dict[int, object] = {}


def set_devices(dev_dict):
    global devices
    devices = dev_dict


@router.get("/apiversions", summary="")
async def api_versions():
    return PropertyResponse.create(value=[1], client_transaction_id=0).model_dump()


@router.get("/v1/description", summary="")
async def server_description():
    desc = ServerDescription(
        ServerName=ServerMetadata.Name,
        Manufacturer=ServerMetadata.Manufacturer,
        Version=ServerMetadata.Version,
        Location=config.server.host,
    )
    return PropertyResponse.create(value=desc.model_dump(), client_transaction_id=0).model_dump()


@router.get("/v1/configureddevices", summary="")
async def configured_devices():
    device = [
        ConfiguredDevice(
            DeviceName=dev.entity,
            DeviceType="Camera",
            DeviceNumber=num,
        ).model_dump()
        for num, dev in devices.items()
    ]
    return PropertyResponse.create(value=device, client_transaction_id=0).model_dump()
