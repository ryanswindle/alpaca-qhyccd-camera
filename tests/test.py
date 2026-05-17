import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import time

from astropy.io import fits
import numpy as np

from alpaca.camera import Camera
from alpaca.exceptions import NotImplementedException, InvalidOperationException
from config import config


# array.array typecode → numpy dtype. Mirrors sensorkit's mapping so that
# ImageArrayRaw retrievals preserve the wire dtype (no Python-int round-trip
# via ImageArray's nested-list path, which silently widens to np.int_).
_TYPECODE_TO_DTYPE = {
    "B": "uint8",
    "h": "int16",
    "H": "uint16",
    "i": "int32",
    "I": "uint32",
}


def fetch_image(cam):
    """Retrieve image via ImageArrayRaw to preserve native bit width.

    Alpaca convention: Dimension1=NumX (width), Dimension2=NumY (height).
    Server transmits with X fastest, so the flat buffer reshapes as
    (W, H) and transposes to (H, W) for FITS row-major.
    """
    raw = cam.ImageArrayRaw
    info = cam.ImageArrayInfo
    dtype = _TYPECODE_TO_DTYPE.get(raw.typecode, "uint16")
    arr = np.frombuffer(raw, dtype=dtype).reshape(info.Dimension1, info.Dimension2).T
    return np.ascontiguousarray(arr)


def save_fits(cam, img, filename):
    hdu = fits.PrimaryHDU(img)
    hdu.header["DATE-OBS"] = cam.LastExposureStartTime
    hdu.header["EXPTIME"] = cam.LastExposureDuration
    hdu.header["XBINNING"] = cam.BinX
    hdu.header["YBINNING"] = cam.BinY
    hdu.header["READMODE"] = cam.ReadoutModes[cam.ReadoutMode]
    hdu.writeto(filename, overwrite=True)
    written = fits.getheader(filename)
    print(
        f"Saved {filename} (BITPIX={written['BITPIX']}, "
        f"BZERO={written.get('BZERO', 0)}, "
        f"NAXIS1={written['NAXIS1']}, NAXIS2={written['NAXIS2']})"
    )


cam = Camera(f"{config.server.host}:{config.server.port}", 0)

print(f"  Name:   {cam.Name}")
print(f"  Driver: {cam.DriverVersion}\n")

# Connect
print("Connecting...")
cam.Connected = True
t0 = time.time()
while not cam.Connected:
    time.sleep(0.1)
    if (time.time()-t0) > 30:
        import pdb; pdb.set_trace()
print(f"  Connected: {cam.Connected}")

# Read parameters
props = [
    ("binx, biny",                  lambda c: f"{c.BinX}, {c.BinY}"),
    ("camerastate",                 lambda c: c.CameraState),
    ("cameraxsize, cameraysize",    lambda c: f"{c.CameraXSize}, {c.CameraYSize}"),
    ("ccdtemperature",              lambda c: c.CCDTemperature),
    ("cooleron",                    lambda c: c.CoolerOn),
    ("coolerpower",                 lambda c: c.CoolerPower),
    ("exposuremax",                 lambda c: c.ExposureMax),
    ("exposuremin",                 lambda c: c.ExposureMin),
    ("exposureresolution",          lambda c: c.ExposureResolution),
    ("fullwellcapacity",            lambda c: c.FullWellCapacity),
    ("gain",                        lambda c: c.Gain),
    ("gainmax",                     lambda c: c.GainMax),
    ("gainmin",                     lambda c: c.GainMin),
    ("lastexposureduration",        lambda c: c.LastExposureDuration),
    ("lastexposurestarttime",       lambda c: c.LastExposureStartTime),
    ("maxadu",                      lambda c: c.MaxADU),
    ("maxbinx, maxbiny",            lambda c: f"{c.MaxBinX}, {c.MaxBinY}"),
    ("numx, numy",                  lambda c: f"{c.NumX}, {c.NumY}"),
    ("offset",                      lambda c: c.Offset),
    ("offsetmax",                   lambda c: c.OffsetMax),
    ("offsetmin",                   lambda c: c.OffsetMin),
    ("pixelsizex, pixelsizey",      lambda c: f"{c.PixelSizeX}, {c.PixelSizeY}"),
    ("readoutmode",                 lambda c: c.ReadoutMode),
    ("readoutmodes",                lambda c: c.ReadoutModes),
    ("sensorname",                  lambda c: c.SensorName),
    ("sensortype",                  lambda c: c.SensorType),
    ("setccdtemperature",           lambda c: c.SetCCDTemperature),
    ("startx, starty",              lambda c: f"{c.StartX}, {c.StartY}"),
]

for label, getter in props:
    try:
        print(f"{label} = {getter(cam)}")
    except NotImplementedException:
        print(f"{label} = N/A (not implemented)")
    except InvalidOperationException:
        print(f"{label} = N/A (invalid operation)")

# ============================================================================
# Test 1: 1x1 full-frame exposure
# ============================================================================
cam.BinX = 1
print(f"\n--- Test 1: 1x1 full-frame ---")
print(f"binx={cam.BinX}, numx={cam.NumX}, numy={cam.NumY}")
cam.StartExposure(2.0, True)
t0 = time.time()
while not cam.ImageReady:
    time.sleep(1)
    if (time.time()-t0) > 120:
        print("Timeout!")
        break
if cam.ImageReady:
    img = fetch_image(cam)
    print(f"Got it. img.shape = {img.shape}, dtype = {img.dtype}, max = {int(np.max(img))}, med = {np.median(img)}")
    print(f"LastExposureStartTime = {cam.LastExposureStartTime}")
    print(f"LastExposureDuration = {cam.LastExposureDuration}")
    save_fits(cam, img, "test1_1x1.fits")

# ============================================================================
# Test 2: 4x4 full-frame exposure
# ============================================================================
cam.BinX = 4
print(f"\n--- Test 2: 4x4 full-frame ---")
print(f"binx={cam.BinX}, numx={cam.NumX}, numy={cam.NumY}")
cam.StartExposure(2.0, True)
t0 = time.time()
while not cam.ImageReady:
    time.sleep(1)
    if (time.time()-t0) > 120:
        print("Timeout!")
        break
if cam.ImageReady:
    img = fetch_image(cam)
    print(f"Got it. img.shape = {img.shape}, dtype = {img.dtype}, max = {int(np.max(img))}, med = {np.median(img)}")
    print(f"LastExposureStartTime = {cam.LastExposureStartTime}")
    print(f"LastExposureDuration = {cam.LastExposureDuration}")
    save_fits(cam, img, "test2_4x4.fits")

# ============================================================================
# Test 3: 2x2 ROI (centered 1024x1024 window)
# ============================================================================
cam.BinX = 2
print(f"\n--- Test 3: 2x2 centered 1024x1024 ROI ---")
half_w, half_h = 512, 512
cx = cam.CameraXSize // cam.BinX // 2
cy = cam.CameraYSize // cam.BinY // 2
cam.StartX = cx - half_w
cam.StartY = cy - half_h
cam.NumX = 1024
cam.NumY = 1024
print(f"binx={cam.BinX}, startx={cam.StartX}, starty={cam.StartY}, numx={cam.NumX}, numy={cam.NumY}")
cam.StartExposure(2.0, True)
t0 = time.time()
while not cam.ImageReady:
    time.sleep(1)
    if (time.time()-t0) > 120:
        print("Timeout!")
        break
if cam.ImageReady:
    img = fetch_image(cam)
    print(f"Got it. img.shape = {img.shape}, dtype = {img.dtype}, max = {int(np.max(img))}, med = {np.median(img)}")
    print(f"LastExposureStartTime = {cam.LastExposureStartTime}")
    print(f"LastExposureDuration = {cam.LastExposureDuration}")
    save_fits(cam, img, "test3_2x2_roi.fits")

# ============================================================================
# Back to 1x1 full-frame to verify reset works
# ============================================================================
cam.BinX = 1
print(f"\n--- Test 4: Back to 1x1 full-frame ---")
print(f"binx={cam.BinX}, numx={cam.NumX}, numy={cam.NumY}")

cam.Connected = False
print("\nDone.")
