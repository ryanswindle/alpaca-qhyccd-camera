from typing import Annotated, Dict, Optional

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Response
from fastapi.responses import JSONResponse

from camera_device import CameraDevice
from exceptions import (
    DriverException,
    InvalidOperationException,
    InvalidValueException,
    NotConnectedException,
    NotImplementedException,
)
from log import get_logger
from responses import ImageArrayResponse, MethodResponse, PropertyResponse, StateValue
from shr import AlpacaGetParams, AlpacaPutParams, alpaca_put_params, to_bool


logger = get_logger()

router = APIRouter(prefix="/api/v1/camera", tags=["Camera"])

devices: Dict[int, CameraDevice] = {}


def set_devices(dev_dict: Dict[int, CameraDevice]):
    global devices
    devices = dev_dict


def get_device(devnum: int) -> CameraDevice:
    if devnum not in devices:
        raise HTTPException(
            status_code=400,
            detail=f"Device number {devnum} does not exist.",
        )
    return devices[devnum]


##################################
# High-level device/library info #
##################################
class DeviceMetadata:
    Name = "QHYCCD Camera"
    Version = "1.0.0"
    Description = "QHYCCD Camera ASCOM Alpaca Driver via libqhyccd"
    DeviceType = "Camera"
    Info = "Alpaca Device\nImplements ICameraV4\nASCOM Initiative"
    InterfaceVersion = 4


def _connected_property(device: CameraDevice, attr_name, params):
    """Helper for simple properties that require connection.

    Takes an attribute *name* (string) rather than a value so the
    underlying property is read only after the connection check
    passes — important because many property getters call into a
    hardware library that may not be loaded if no device is attached.
    """
    if not device.connected:
        return PropertyResponse.create(
            value=None,
            client_transaction_id=params.client_transaction_id,
            error=NotConnectedException(),
        ).model_dump()
    try:
        value = getattr(device, attr_name)
    except Exception as ex:
        return PropertyResponse.create(
            value=None,
            client_transaction_id=params.client_transaction_id,
            error=DriverException(0x500, f"Camera.{attr_name} failed", ex),
        ).model_dump()
    return PropertyResponse.create(
        value=value,
        client_transaction_id=params.client_transaction_id,
    ).model_dump()


#######################################
# ASCOM Methods Common To All Devices #
#######################################
@router.put("/{devnum}/action", summary="")
async def action(devnum: int, params: AlpacaPutParams = Depends(alpaca_put_params)):
    get_device(devnum)
    return MethodResponse.create(
        client_transaction_id=params.client_transaction_id,
        error=NotImplementedException("Action"),
    ).model_dump()


@router.put("/{devnum}/commandblind", summary="")
async def commandblind(devnum: int, params: AlpacaPutParams = Depends(alpaca_put_params)):
    get_device(devnum)
    return MethodResponse.create(
        client_transaction_id=params.client_transaction_id,
        error=NotImplementedException("CommandBlind"),
    ).model_dump()


@router.put("/{devnum}/commandbool", summary="")
async def commandbool(devnum: int, params: AlpacaPutParams = Depends(alpaca_put_params)):
    get_device(devnum)
    return MethodResponse.create(
        client_transaction_id=params.client_transaction_id,
        error=NotImplementedException("CommandBool"),
    ).model_dump()


@router.put("/{devnum}/commandstring", summary="")
async def commandstring(devnum: int, params: AlpacaPutParams = Depends(alpaca_put_params)):
    get_device(devnum)
    return MethodResponse.create(
        client_transaction_id=params.client_transaction_id,
        error=NotImplementedException("CommandString"),
    ).model_dump()


@router.put("/{devnum}/connect", summary="")
async def connect(devnum: int, params: AlpacaPutParams = Depends(alpaca_put_params)):
    device = get_device(devnum)
    try:
        device.connect()
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
        ).model_dump()
    except Exception as ex:
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
            error=DriverException(0x500, "Camera.Connect failed", ex),
        ).model_dump()


@router.get("/{devnum}/connected", summary="")
async def connected_get(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return PropertyResponse.create(
        value=device.connected,
        client_transaction_id=params.client_transaction_id,
    ).model_dump()


@router.put("/{devnum}/connected", summary="")
async def connected_put(devnum: int, params: AlpacaPutParams = Depends(alpaca_put_params)):
    device = get_device(devnum)
    value = params.get("Connected")
    if value is None:
        raise HTTPException(status_code=400, detail="Missing required parameter 'Connected'")
    conn = to_bool(value)
    try:
        device.connected = conn
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
        ).model_dump()
    except HTTPException:
        raise
    except Exception as ex:
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
            error=DriverException(0x500, "Camera.Connected failed", ex),
        ).model_dump()


@router.get("/{devnum}/connecting", summary="")
async def connecting_get(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return PropertyResponse.create(
        value=device.connecting,
        client_transaction_id=params.client_transaction_id,
    ).model_dump()


@router.get("/{devnum}/description", summary="")
async def description(devnum: int, params: AlpacaGetParams = Depends()):
    get_device(devnum)
    return PropertyResponse.create(
        value=DeviceMetadata.Description,
        client_transaction_id=params.client_transaction_id,
    ).model_dump()


@router.get("/{devnum}/devicestate", summary="")
async def devicestate(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    if not device.connected:
        return PropertyResponse.create(
            value=[],
            client_transaction_id=params.client_transaction_id,
            error=NotConnectedException(),
        ).model_dump()
    try:
        val = [
            StateValue(Name="CameraState", Value=int(device.camera_state)).model_dump(),
            StateValue(Name="CCDTemperature", Value=device.ccd_temperature).model_dump(),
            StateValue(Name="CoolerPower", Value=device.cooler_power).model_dump(),
            StateValue(Name="ImageReady", Value=device.image_ready).model_dump(),
            StateValue(Name="TimeStamp", Value=device.timestamp).model_dump(),
        ]
        return PropertyResponse.create(
            value=val,
            client_transaction_id=params.client_transaction_id,
        ).model_dump()
    except Exception as ex:
        return PropertyResponse.create(
            value=None,
            client_transaction_id=params.client_transaction_id,
            error=DriverException(0x500, "Camera.DeviceState failed", ex),
        ).model_dump()


@router.put("/{devnum}/disconnect", summary="")
async def disconnect(devnum: int, params: AlpacaPutParams = Depends(alpaca_put_params)):
    device = get_device(devnum)
    try:
        device.disconnect()
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
        ).model_dump()
    except Exception as ex:
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
            error=DriverException(0x500, "Camera.Disconnect failed", ex),
        ).model_dump()


@router.get("/{devnum}/driverinfo", summary="")
async def driverinfo(devnum: int, params: AlpacaGetParams = Depends()):
    get_device(devnum)
    return PropertyResponse.create(
        value=DeviceMetadata.Info,
        client_transaction_id=params.client_transaction_id,
    ).model_dump()


@router.get("/{devnum}/driverversion", summary="")
async def driverversion(devnum: int, params: AlpacaGetParams = Depends()):
    get_device(devnum)
    return PropertyResponse.create(
        value=DeviceMetadata.Version,
        client_transaction_id=params.client_transaction_id,
    ).model_dump()


@router.get("/{devnum}/interfaceversion", summary="")
async def interfaceversion(devnum: int, params: AlpacaGetParams = Depends()):
    get_device(devnum)
    return PropertyResponse.create(
        value=DeviceMetadata.InterfaceVersion,
        client_transaction_id=params.client_transaction_id,
    ).model_dump()


@router.get("/{devnum}/name", summary="")
async def name(devnum: int, params: AlpacaGetParams = Depends()):
    get_device(devnum)
    return PropertyResponse.create(
        value=DeviceMetadata.Name,
        client_transaction_id=params.client_transaction_id,
    ).model_dump()


@router.get("/{devnum}/supportedactions", summary="")
async def supportedactions(devnum: int, params: AlpacaGetParams = Depends()):
    get_device(devnum)
    return PropertyResponse.create(
        value=[],
        client_transaction_id=params.client_transaction_id,
    ).model_dump()


######################
# ICamera properties #
######################
@router.get("/{devnum}/bayeroffsetx", summary="")
async def bayeroffsetx(devnum: int, params: AlpacaGetParams = Depends()):
    get_device(devnum)
    return PropertyResponse.create(
        value=None,
        client_transaction_id=params.client_transaction_id,
        error=NotImplementedException("BayerOffsetX"),
    ).model_dump()


@router.get("/{devnum}/bayeroffsety", summary="")
async def bayeroffsety(devnum: int, params: AlpacaGetParams = Depends()):
    get_device(devnum)
    return PropertyResponse.create(
        value=None,
        client_transaction_id=params.client_transaction_id,
        error=NotImplementedException("BayerOffsetY"),
    ).model_dump()


@router.get("/{devnum}/binx", summary="")
async def binx_get(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "bin_x", params)


@router.put("/{devnum}/binx", summary="")
async def binx_put(devnum: int, BinX: Annotated[str, Form()], params: AlpacaPutParams = Depends(alpaca_put_params)):
    device = get_device(devnum)
    # Validate BinX *before* the connected check so bad values yield 400.
    try:
        bin_x = int(BinX)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"BinX must be an integer, got {BinX!r}")
    if not device.connected:
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
            error=NotConnectedException(),
        ).model_dump()
    try:
        device.bin_x = bin_x
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
        ).model_dump()
    except ValueError as ex:
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
            error=InvalidValueException(str(ex)),
        ).model_dump()


@router.get("/{devnum}/biny", summary="")
async def biny_get(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "bin_y", params)


@router.put("/{devnum}/biny", summary="")
async def biny_put(devnum: int, BinY: Annotated[str, Form()], params: AlpacaPutParams = Depends(alpaca_put_params)):
    device = get_device(devnum)
    # Validate BinY *before* the connected check so bad values yield 400.
    try:
        bin_y = int(BinY)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"BinY must be an integer, got {BinY!r}")
    if not device.connected:
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
            error=NotConnectedException(),
        ).model_dump()
    try:
        device.bin_y = bin_y
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
        ).model_dump()
    except ValueError as ex:
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
            error=InvalidValueException(str(ex)),
        ).model_dump()


@router.get("/{devnum}/camerastate", summary="")
async def camerastate(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    if not device.connected:
        return PropertyResponse.create(
            value=None,
            client_transaction_id=params.client_transaction_id,
            error=NotConnectedException(),
        ).model_dump()
    try:
        return PropertyResponse.create(
            value=int(device.camera_state),
            client_transaction_id=params.client_transaction_id,
        ).model_dump()
    except Exception as ex:
        return PropertyResponse.create(
            value=None,
            client_transaction_id=params.client_transaction_id,
            error=DriverException(0x500, "Camera.CameraState failed", ex),
        ).model_dump()


@router.get("/{devnum}/cameraxsize", summary="")
async def cameraxsize(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "camera_x_size", params)


@router.get("/{devnum}/cameraysize", summary="")
async def cameraysize(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "camera_y_size", params)


@router.get("/{devnum}/canabortexposure", summary="")
async def canabortexposure(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "can_abort_exposure", params)


@router.get("/{devnum}/canasymmetricbin", summary="")
async def canasymmetricbin(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "can_asymmetric_bin", params)


@router.get("/{devnum}/canfastreadout", summary="")
async def canfastreadout(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "can_fast_readout", params)


@router.get("/{devnum}/cangetcoolerpower", summary="")
async def cangetcoolerpower(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "can_get_cooler_power", params)


@router.get("/{devnum}/canpulseguide", summary="")
async def canpulseguide(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "can_pulse_guide", params)


@router.get("/{devnum}/cansetccdtemperature", summary="")
async def cansetccdtemperature(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "can_set_ccd_temperature", params)


@router.get("/{devnum}/canstopexposure", summary="")
async def canstopexposure(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "can_stop_exposure", params)


@router.get("/{devnum}/ccdtemperature", summary="")
async def ccdtemperature(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "ccd_temperature", params)


@router.get("/{devnum}/cooleron", summary="")
async def cooleron_get(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "cooler_on", params)


@router.put("/{devnum}/cooleron", summary="")
async def cooleron_put(devnum: int, CoolerOn: Annotated[str, Form()], params: AlpacaPutParams = Depends(alpaca_put_params)):
    get_device(devnum)
    # Validate CoolerOn even though we may no-op so bad values yield 400.
    to_bool(CoolerOn)
    return MethodResponse.create(
        client_transaction_id=params.client_transaction_id,
    ).model_dump()


@router.get("/{devnum}/coolerpower", summary="")
async def coolerpower(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "cooler_power", params)


@router.get("/{devnum}/electronsperadu", summary="")
async def electronsperadu(devnum: int, params: AlpacaGetParams = Depends()):
    get_device(devnum)
    return PropertyResponse.create(
        value=None,
        client_transaction_id=params.client_transaction_id,
        error=NotImplementedException("ElectronsPerADU"),
    ).model_dump()


@router.get("/{devnum}/exposuremax", summary="")
async def exposuremax(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "exposure_max", params)


@router.get("/{devnum}/exposuremin", summary="")
async def exposuremin(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "exposure_min", params)


@router.get("/{devnum}/exposureresolution", summary="")
async def exposureresolution(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "exposure_resolution", params)


@router.get("/{devnum}/fastreadout", summary="")
async def fastreadout_get(devnum: int, params: AlpacaGetParams = Depends()):
    get_device(devnum)
    return PropertyResponse.create(
        value=None,
        client_transaction_id=params.client_transaction_id,
        error=NotImplementedException("FastReadout"),
    ).model_dump()


@router.put("/{devnum}/fastreadout", summary="")
async def fastreadout_put(devnum: int, FastReadout: Annotated[str, Form()], params: AlpacaPutParams = Depends(alpaca_put_params)):
    get_device(devnum)
    return MethodResponse.create(
        client_transaction_id=params.client_transaction_id,
        error=NotImplementedException("FastReadout"),
    ).model_dump()


@router.get("/{devnum}/fullwellcapacity", summary="")
async def fullwellcapacity(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "full_well_capacity", params)


@router.get("/{devnum}/gain", summary="")
async def gain_get(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "gain", params)


@router.put("/{devnum}/gain", summary="")
async def gain_put(devnum: int, Gain: Annotated[str, Form()], params: AlpacaPutParams = Depends(alpaca_put_params)):
    device = get_device(devnum)
    # Validate Gain *before* the connected check so bad values yield 400.
    try:
        val = int(Gain)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Gain must be an integer, got {Gain!r}")
    if not device.connected:
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
            error=NotConnectedException(),
        ).model_dump()
    try:
        if val < device.gain_min or val > device.gain_max:
            return MethodResponse.create(
                client_transaction_id=params.client_transaction_id,
                error=InvalidValueException(
                    f"Gain {val} out of range {device.gain_min}-{device.gain_max}"
                ),
            ).model_dump()
        device.gain = val
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
        ).model_dump()
    except ValueError as ex:
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
            error=InvalidValueException(str(ex)),
        ).model_dump()


@router.get("/{devnum}/gainmax", summary="")
async def gainmax(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "gain_max", params)


@router.get("/{devnum}/gainmin", summary="")
async def gainmin(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "gain_min", params)


@router.get("/{devnum}/gains", summary="")
async def gains(devnum: int, params: AlpacaGetParams = Depends()):
    get_device(devnum)
    return PropertyResponse.create(
        value=None,
        client_transaction_id=params.client_transaction_id,
        error=NotImplementedException("Gains"),
    ).model_dump()


@router.get("/{devnum}/hasshutter", summary="")
async def hasshutter(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "has_shutter", params)


@router.get("/{devnum}/heatsinktemperature", summary="")
async def heatsinktemperature(devnum: int, params: AlpacaGetParams = Depends()):
    get_device(devnum)
    return PropertyResponse.create(
        value=None,
        client_transaction_id=params.client_transaction_id,
        error=NotImplementedException("HeatSinkTemperature"),
    ).model_dump()


@router.get("/{devnum}/imagearray", summary="")
async def imagearray(devnum: int, params: AlpacaGetParams = Depends(), accept: Optional[str] = Header(None)):
    device = get_device(devnum)
    if not device.connected:
        return PropertyResponse.create(
            value=None,
            client_transaction_id=params.client_transaction_id,
            error=NotConnectedException(),
        ).model_dump()
    if not device.image_ready:
        return PropertyResponse.create(
            value=None,
            client_transaction_id=params.client_transaction_id,
            error=InvalidOperationException("Image not ready"),
        ).model_dump()
    try:
        img = device.image_array
        iar = ImageArrayResponse.create(
            value=img,
            client_transaction_id=params.client_transaction_id,
        )
        if accept and "imagebytes" in accept.lower():
            return Response(
                content=iar.to_imagebytes(),
                media_type="application/imagebytes",
            )
        response_data = iar.model_dump()
        response_data["Value"] = img.tolist()
        return JSONResponse(content=response_data)
    except Exception as ex:
        return PropertyResponse.create(
            value=None,
            client_transaction_id=params.client_transaction_id,
            error=DriverException(0x500, "Camera.ImageArray failed", ex),
        ).model_dump()


@router.get("/{devnum}/imagearrayvariant", summary="")
async def imagearrayvariant(devnum: int, params: AlpacaGetParams = Depends()):
    get_device(devnum)
    return PropertyResponse.create(
        value=None,
        client_transaction_id=params.client_transaction_id,
        error=NotImplementedException("ImageArrayVariant"),
    ).model_dump()


@router.get("/{devnum}/imageready", summary="")
async def imageready(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "image_ready", params)


@router.get("/{devnum}/ispulseguiding", summary="")
async def ispulseguiding(devnum: int, params: AlpacaGetParams = Depends()):
    get_device(devnum)
    return PropertyResponse.create(
        value=None,
        client_transaction_id=params.client_transaction_id,
        error=NotImplementedException("IsPulseGuiding"),
    ).model_dump()


@router.get("/{devnum}/lastexposureduration", summary="")
async def lastexposureduration(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "last_exposure_duration", params)


@router.get("/{devnum}/lastexposurestarttime", summary="")
async def lastexposurestarttime(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "last_exposure_start_time", params)


@router.get("/{devnum}/maxadu", summary="")
async def maxadu(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "max_adu", params)


@router.get("/{devnum}/maxbinx", summary="")
async def maxbinx(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "max_bin_x", params)


@router.get("/{devnum}/maxbiny", summary="")
async def maxbiny(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "max_bin_y", params)


@router.get("/{devnum}/numx", summary="")
async def numx_get(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "num_x", params)


@router.put("/{devnum}/numx", summary="")
async def numx_put(devnum: int, NumX: Annotated[str, Form()], params: AlpacaPutParams = Depends(alpaca_put_params)):
    device = get_device(devnum)
    if not device.connected:
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
            error=NotConnectedException(),
        ).model_dump()
    try:
        device.num_x = int(NumX)
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
        ).model_dump()
    except ValueError as ex:
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
            error=InvalidValueException(str(ex)),
        ).model_dump()


@router.get("/{devnum}/numy", summary="")
async def numy_get(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "num_y", params)


@router.put("/{devnum}/numy", summary="")
async def numy_put(devnum: int, NumY: Annotated[str, Form()], params: AlpacaPutParams = Depends(alpaca_put_params)):
    device = get_device(devnum)
    if not device.connected:
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
            error=NotConnectedException(),
        ).model_dump()
    try:
        device.num_y = int(NumY)
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
        ).model_dump()
    except ValueError as ex:
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
            error=InvalidValueException(str(ex)),
        ).model_dump()


@router.get("/{devnum}/offset", summary="")
async def offset_get(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "offset", params)


@router.put("/{devnum}/offset", summary="")
async def offset_put(devnum: int, Offset: Annotated[str, Form()], params: AlpacaPutParams = Depends(alpaca_put_params)):
    device = get_device(devnum)
    if not device.connected:
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
            error=NotConnectedException(),
        ).model_dump()
    try:
        val = int(Offset)
        if val < device.offset_min or val > device.offset_max:
            return MethodResponse.create(
                client_transaction_id=params.client_transaction_id,
                error=InvalidValueException(
                    f"Offset {val} out of range {device.offset_min}-{device.offset_max}"
                ),
            ).model_dump()
        device.offset = val
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
        ).model_dump()
    except ValueError as ex:
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
            error=InvalidValueException(str(ex)),
        ).model_dump()


@router.get("/{devnum}/offsetmax", summary="")
async def offsetmax(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "offset_max", params)


@router.get("/{devnum}/offsetmin", summary="")
async def offsetmin(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "offset_min", params)


@router.get("/{devnum}/offsets", summary="")
async def offsets(devnum: int, params: AlpacaGetParams = Depends()):
    get_device(devnum)
    return PropertyResponse.create(
        value=None,
        client_transaction_id=params.client_transaction_id,
        error=NotImplementedException("Offsets"),
    ).model_dump()


@router.get("/{devnum}/percentcompleted", summary="")
async def percentcompleted(devnum: int, params: AlpacaGetParams = Depends()):
    get_device(devnum)
    return PropertyResponse.create(
        value=None,
        client_transaction_id=params.client_transaction_id,
        error=NotImplementedException("PercentCompleted"),
    ).model_dump()


@router.get("/{devnum}/pixelsizex", summary="")
async def pixelsizex(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "pixel_size_x", params)


@router.get("/{devnum}/pixelsizey", summary="")
async def pixelsizey(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "pixel_size_y", params)


@router.get("/{devnum}/readoutmode", summary="")
async def readoutmode_get(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "readout_mode", params)


@router.put("/{devnum}/readoutmode", summary="")
async def readoutmode_put(devnum: int, ReadoutMode: Annotated[str, Form()], params: AlpacaPutParams = Depends(alpaca_put_params)):
    device = get_device(devnum)
    if not device.connected:
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
            error=NotConnectedException(),
        ).model_dump()
    try:
        device.readout_mode = int(ReadoutMode)
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
        ).model_dump()
    except ValueError as ex:
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
            error=InvalidValueException(str(ex)),
        ).model_dump()


@router.get("/{devnum}/readoutmodes", summary="")
async def readoutmodes(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "readout_modes", params)


@router.get("/{devnum}/sensorname", summary="")
async def sensorname(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "sensor_name", params)


@router.get("/{devnum}/sensortype", summary="")
async def sensortype(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, int(device.sensor_type), params)


@router.get("/{devnum}/setccdtemperature", summary="")
async def setccdtemperature_get(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "set_ccd_temperature", params)


@router.put("/{devnum}/setccdtemperature", summary="")
async def setccdtemperature_put(devnum: int, SetCCDTemperature: Annotated[str, Form()], params: AlpacaPutParams = Depends(alpaca_put_params)):
    device = get_device(devnum)
    if not device.connected:
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
            error=NotConnectedException(),
        ).model_dump()
    try:
        device.set_ccd_temperature = float(SetCCDTemperature)
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
        ).model_dump()
    except ValueError as ex:
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
            error=InvalidValueException(str(ex)),
        ).model_dump()


@router.get("/{devnum}/startx", summary="")
async def startx_get(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "start_x", params)


@router.put("/{devnum}/startx", summary="")
async def startx_put(devnum: int, StartX: Annotated[str, Form()], params: AlpacaPutParams = Depends(alpaca_put_params)):
    device = get_device(devnum)
    if not device.connected:
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
            error=NotConnectedException(),
        ).model_dump()
    try:
        device.start_x = int(StartX)
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
        ).model_dump()
    except ValueError as ex:
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
            error=InvalidValueException(str(ex)),
        ).model_dump()


@router.get("/{devnum}/starty", summary="")
async def starty_get(devnum: int, params: AlpacaGetParams = Depends()):
    device = get_device(devnum)
    return _connected_property(device, "start_y", params)


@router.put("/{devnum}/starty", summary="")
async def starty_put(devnum: int, StartY: Annotated[str, Form()],params: AlpacaPutParams = Depends(alpaca_put_params)):
    device = get_device(devnum)
    if not device.connected:
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
            error=NotConnectedException(),
        ).model_dump()
    try:
        device.start_y = int(StartY)
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
        ).model_dump()
    except ValueError as ex:
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
            error=InvalidValueException(str(ex)),
        ).model_dump()


@router.get("/{devnum}/subexposureduration", summary="")
async def subexposureduration_get(devnum: int, params: AlpacaGetParams = Depends()):
    get_device(devnum)
    return PropertyResponse.create(
        value=None,
        client_transaction_id=params.client_transaction_id,
        error=NotImplementedException("SubExposureDuration"),
    ).model_dump()


@router.put("/{devnum}/subexposureduration", summary="")
async def subexposureduration_put(devnum: int, SubExposureDuration: Annotated[str, Form()], params: AlpacaPutParams = Depends(alpaca_put_params)):
    get_device(devnum)
    return MethodResponse.create(
        client_transaction_id=params.client_transaction_id,
        error=NotImplementedException("SubExposureDuration"),
    ).model_dump()


###################
# ICamera methods #
###################
@router.put("/{devnum}/abortexposure", summary="")
async def abortexposure(devnum: int, params: AlpacaPutParams = Depends(alpaca_put_params)):
    device = get_device(devnum)
    if not device.connected:
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
            error=NotConnectedException(),
        ).model_dump()
    try:
        device.abort_exposure()
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
        ).model_dump()
    except Exception as ex:
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
            error=DriverException(0x500, "Camera.AbortExposure failed", ex),
        ).model_dump()


@router.put("/{devnum}/pulseguide", summary="")
async def pulseguide(devnum: int, Direction: Annotated[str, Form()], Duration: Annotated[str, Form()], params: AlpacaPutParams = Depends(alpaca_put_params)):
    get_device(devnum)
    return MethodResponse.create(
        client_transaction_id=params.client_transaction_id,
        error=NotImplementedException("PulseGuide"),
    ).model_dump()


@router.put("/{devnum}/startexposure", summary="")
async def startexposure(devnum: int, Duration: Annotated[str, Form()], Light: Annotated[str, Form()], params: AlpacaPutParams = Depends(alpaca_put_params)):
    device = get_device(devnum)
    if not device.connected:
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
            error=NotConnectedException(),
        ).model_dump()
    try:
        device.start_exposure(float(Duration), to_bool(Light))
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
        ).model_dump()
    except HTTPException:
        raise
    except ValueError as ex:
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
            error=InvalidValueException(str(ex)),
        ).model_dump()
    except Exception as ex:
        return MethodResponse.create(
            client_transaction_id=params.client_transaction_id,
            error=DriverException(0x500, "Camera.StartExposure failed", ex),
        ).model_dump()


@router.put("/{devnum}/stopexposure", summary="")
async def stopexposure(devnum: int, params: AlpacaPutParams = Depends(alpaca_put_params)):
    get_device(devnum)
    return MethodResponse.create(
        client_transaction_id=params.client_transaction_id,
        error=NotImplementedException("StopExposure"),
    ).model_dump()
