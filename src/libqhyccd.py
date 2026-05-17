"""
libqhyccd wrapper with proper ctypes function signatures.

Provides constants, data classes, GPS parsing, and library loading
with explicit argtypes/restype declarations for 64-bit stability.
"""

from ctypes import (
    CDLL, POINTER, Structure, byref, c_char_p, c_double, c_int, c_int32,
    c_uint8, c_uint16, c_uint32, cdll, create_string_buffer
)

from astropy.time import Time

from log import get_logger


logger = get_logger()

#############
# Constants #
#############
QHY_SUCCESS = 0
QHY_ERROR = 0xFFFFFFFF


###############
# Control IDs #
###############
class QHY_CONTROL:
    GAIN = 6
    OFFSET = 7
    EXPOSURE = 8
    USBTRAFFIC = 12
    CURTEMP = 14
    CURPWM = 15
    MANUALPWM = 16
    COOLER = 18
    CAM_BIN1X1MODE = 21
    CAM_BIN2X2MODE = 22
    CAM_BIN3X3MODE = 23
    CAM_BIN4X4MODE = 24
    CAM_CHIPTEMPERATURESENSOR_INTERFACE = 32
    GPS = 36
    UVLO_STATUS = 67
    CAM_BIN6X6MODE = 75
    CAM_BIN8X8MODE = 76
    CURVE_FULL_WELL = 102


###################################################
# GPS structure (from warwick-one-metre/qhy-camd) #
###################################################
class QHY_GPS(Structure):
    _pack_ = 1
    _fields_ = [
        ("SequenceNumber", c_uint32.__ctype_be__),
        ("unused1", c_uint8),
        ("ImageWidth", c_uint16.__ctype_be__),
        ("ImageHeight", c_uint16.__ctype_be__),
        ("_Latitude", c_uint32.__ctype_be__),
        ("_Longitude", c_uint32.__ctype_be__),
        ("StartFlag", c_uint8),
        ("StartSeconds", c_uint32.__ctype_be__),
        ("StartCounts", 3 * c_uint8),
        ("EndFlag", c_uint8),
        ("EndSeconds", c_uint32.__ctype_be__),
        ("EndCounts", 3 * c_uint8),
        ("NowFlag", c_uint8),
        ("NowSeconds", c_uint32.__ctype_be__),
        ("NowCounts", 3 * c_uint8),
        ("_PPSDelta", 3 * c_uint8),
    ]

    @classmethod
    def create_timestamp(cls, seconds, count_bytes):
        """Timestamps are encoded as seconds since 2450000.5 JD plus 10MHz clock cycles."""
        counts = int.from_bytes(count_bytes, byteorder='big', signed=False)
        return Time((seconds + counts / 1e7) / (3600 * 24) + 2450000.5, format='jd').isot

    @classmethod
    def create_status(cls, flag):
        return ['OFFLINE', 'SEARCHING', 'LOCKING', 'LOCKED'][(flag // 16) % 4]

    @property
    def Latitude(self):
        minutes = (self._Latitude % 10000000) / 100000
        degrees = (self._Latitude // 10000000) % 100
        sign = -1 if self._Latitude > 1000000000 else 1
        return sign * (degrees + minutes / 60)

    @property
    def Longitude(self):
        minutes = (self._Longitude % 1000000) / 10000
        degrees = (self._Longitude // 1000000) % 100
        sign = -1 if self._Longitude > 1000000000 else 1
        return sign * (degrees + minutes / 60)

    @property
    def PPSDelta(self):
        return int.from_bytes(self._PPSDelta, byteorder='big', signed=False)


def load_qhyccd_library(library_path: str) -> CDLL:
    """Load the QHYCCD shared library with proper function signatures."""
    lib = cdll.LoadLibrary(library_path)

    # ---- Resource management ----
    lib.InitQHYCCDResource.argtypes = []
    lib.InitQHYCCDResource.restype = c_uint32

    lib.ReleaseQHYCCDResource.argtypes = []
    lib.ReleaseQHYCCDResource.restype = c_uint32

    # ---- Scanning and identification ----
    lib.ScanQHYCCD.argtypes = []
    lib.ScanQHYCCD.restype = c_uint32

    lib.GetQHYCCDId.argtypes = [c_uint32, c_char_p]
    lib.GetQHYCCDId.restype = c_uint32

    # ---- Open / Close ----
    lib.OpenQHYCCD.argtypes = [c_char_p]
    lib.OpenQHYCCD.restype = POINTER(c_uint32)

    lib.CloseQHYCCD.argtypes = [POINTER(c_uint32)]
    lib.CloseQHYCCD.restype = c_uint32

    # ---- Configuration ----
    lib.SetQHYCCDStreamMode.argtypes = [POINTER(c_uint32), c_uint8]
    lib.SetQHYCCDStreamMode.restype = c_uint32

    lib.InitQHYCCD.argtypes = [POINTER(c_uint32)]
    lib.InitQHYCCD.restype = c_uint32

    lib.SetQHYCCDReadMode.argtypes = [POINTER(c_uint32), c_uint32]
    lib.SetQHYCCDReadMode.restype = c_uint32

    lib.GetQHYCCDNumberOfReadModes.argtypes = [POINTER(c_uint32), POINTER(c_uint32)]
    lib.GetQHYCCDNumberOfReadModes.restype = c_uint32

    lib.GetQHYCCDReadModeName.argtypes = [POINTER(c_uint32), c_uint32, c_char_p]
    lib.GetQHYCCDReadModeName.restype = c_uint32

    lib.SetQHYCCDBitsMode.argtypes = [POINTER(c_uint32), c_uint32]
    lib.SetQHYCCDBitsMode.restype = c_uint32

    lib.SetQHYCCDBinMode.argtypes = [POINTER(c_uint32), c_uint32, c_uint32]
    lib.SetQHYCCDBinMode.restype = c_uint32

    lib.SetQHYCCDResolution.argtypes = [POINTER(c_uint32), c_uint32, c_uint32, c_uint32, c_uint32]
    lib.SetQHYCCDResolution.restype = c_uint32

    # ---- Parameters ----
    lib.SetQHYCCDParam.argtypes = [POINTER(c_uint32), c_int, c_double]
    lib.SetQHYCCDParam.restype = c_uint32

    lib.GetQHYCCDParam.argtypes = [POINTER(c_uint32), c_int]
    lib.GetQHYCCDParam.restype = c_double

    lib.GetQHYCCDParamMinMaxStep.argtypes = [
        POINTER(c_uint32), c_int,
        POINTER(c_double), POINTER(c_double), POINTER(c_double)
    ]
    lib.GetQHYCCDParamMinMaxStep.restype = c_uint32

    # ---- Chip info ----
    lib.GetQHYCCDChipInfo.argtypes = [
        POINTER(c_uint32),
        POINTER(c_double), POINTER(c_double),  # chip width/height mm
        POINTER(c_uint32), POINTER(c_uint32),   # image width/height px
        POINTER(c_double), POINTER(c_double),   # pixel width/height um
        POINTER(c_uint32)                        # bpp
    ]
    lib.GetQHYCCDChipInfo.restype = c_uint32

    lib.QHYCCD_curveFullWell.restype = c_uint32
    lib.QHYCCD_curveFullWell.argtypes = [
        POINTER(c_uint32),
        c_double,
        POINTER(c_double),
    ]

    # ---- ROI ----
    lib.GetQHYCCDCurrentROI.argtypes = [
        POINTER(c_uint32),
        POINTER(c_uint32), POINTER(c_uint32),  # startx, starty
        POINTER(c_uint32), POINTER(c_uint32)   # sizex, sizey
    ]
    lib.GetQHYCCDCurrentROI.restype = c_uint32

    # ---- Exposure ----
    lib.ExpQHYCCDSingleFrame.argtypes = [POINTER(c_uint32)]
    lib.ExpQHYCCDSingleFrame.restype = c_uint32

    lib.GetQHYCCDSingleFrame.argtypes = [
        POINTER(c_uint32),
        POINTER(c_uint32), POINTER(c_uint32),  # width, height
        POINTER(c_uint32), POINTER(c_uint32),   # bpp, channels
        POINTER(c_uint16)                       # data buffer (uint16 array)
    ]
    lib.GetQHYCCDSingleFrame.restype = c_uint32

    lib.CancelQHYCCDExposingAndReadout.argtypes = [POINTER(c_uint32)]
    lib.CancelQHYCCDExposingAndReadout.restype = c_uint32

    lib.GetQHYCCDMemLength.argtypes = [POINTER(c_uint32)]
    lib.GetQHYCCDMemLength.restype = c_uint32

    # ---- Precise exposure info ----
    lib.GetQHYCCDPreciseExposureInfo.argtypes = [
        POINTER(c_uint32),
        POINTER(c_uint32), POINTER(c_uint32), POINTER(c_uint32),  # pixel_period_ps, line_period_ns, frame_period_us
        POINTER(c_uint32), POINTER(c_uint32),                      # clocks_per_line, lines_per_frame
        POINTER(c_uint32), POINTER(c_uint8)                        # actual_exposure_us, is_long_exposure
    ]
    lib.GetQHYCCDPreciseExposureInfo.restype = c_uint32

    lib.GetQHYCCDRollingShutterEndOffset.argtypes = [
        POINTER(c_uint32), c_uint32, POINTER(c_double)
    ]
    lib.GetQHYCCDRollingShutterEndOffset.restype = c_uint32

    # ---- Firmware version ----
    lib.GetQHYCCDFPGAVersion.argtypes = [POINTER(c_uint32), c_uint8, c_char_p]
    lib.GetQHYCCDFPGAVersion.restype = c_uint32

    # ---- Effective area ----
    lib.GetQHYCCDEffectiveArea.argtypes = [
        POINTER(c_uint32),
        POINTER(c_uint32), POINTER(c_uint32),
        POINTER(c_uint32), POINTER(c_uint32)
    ]
    lib.GetQHYCCDEffectiveArea.restype = c_uint32

    logger.debug(f"Loaded QHYCCD library from {library_path}")
    return lib
