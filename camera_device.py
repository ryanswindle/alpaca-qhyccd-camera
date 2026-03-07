from ctypes import (
    byref,
    c_double,
    c_uint8,
    c_uint16,
    c_uint32,
    create_string_buffer,
)
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from threading import Event, Lock, Thread
import time
from typing import Dict, List, Optional

from astropy.time import Time
import numpy as np

from config import DeviceConfig
from libqhyccd import QHY_CONTROL, QHY_GPS, QHY_SUCCESS, QHY_ERROR, load_qhyccd_library
from log import get_logger


logger = get_logger()


class CameraState(IntEnum):
    IDLE = 0
    WAITING = 1
    EXPOSING = 2
    READING = 3
    DOWNLOADING = 4
    ERROR = 5


class SensorType(IntEnum):
    MONOCHROME = 0
    COLOR = 1
    RGGB = 2
    CMYG = 3
    CMYG2 = 4
    LRGB = 5


class CameraDevice:
    """Low-level driver for the QHYCCD camera (libqhyccd)."""

    def __init__(self, device_config: DeviceConfig, library_path: str):
        self._lock = Lock()
        self._config = device_config
        self._library_path = library_path

        self.libqhyccd = None
        self.handle = None

        self._connected = False
        self._connecting = False
        self._connect_thread: Optional[Thread] = None

        self._camera_state = CameraState.IDLE
        self._image_ready = False
        self._exposure_complete = Event()
        self._readout_complete = Event()

        self._last_exposure_duration: Optional[float] = None
        self._last_exposure_start_time: Optional[str] = None
        self._timing: Dict = {}

        # These will be populated from the camera on connect
        self._camera_x_size: int = 0
        self._camera_y_size: int = 0
        self._pixel_size_x: float = 0.0
        self._pixel_size_y: float = 0.0
        self._max_bin_x: int = 1
        self._max_bin_y: int = 1

        # ROI state (in binned pixels per ASCOM spec)
        self._bin_x: int = 1
        self._bin_y: int = 1
        self._start_x: int = 0
        self._start_y: int = 0
        self._num_x: int = 0
        self._num_y: int = 0

        # Camera parameters
        self._exposure_min: float = 0.0
        self._exposure_max: float = 3600.0
        self._exposure_resolution: float = 0.000001
        self._gain_min: int = 0
        self._gain_max: int = 0
        self._offset_min: int = 0
        self._offset_max: int = 0
        self._set_ccd_temperature: float = device_config.defaults.temperature

        # Readout modes
        self._readout_mode: int = 0
        self._readout_modes: List[str] = []

        # Full well capacities: {readout_mode_index: {binning: capacity}}
        self._full_well_capacities: Dict[int, float] = {}

        # Camera firmware version
        self._firmware_version: str = ""
        self._sensor_name: str = "Unknown"
        self._camera_model: str = "Unknown"

    #######################################
    # ASCOM Methods Common To All Devices #
    #######################################
    def connect(self) -> None:
        if self._connected or self._connecting:
            return
        self._connecting = True
        self._connect_thread = Thread(target=self._connect_worker, daemon=True)
        self._connect_thread.start()

    def _connect_worker(self) -> None:
        """Load and initialize the library, open the camera, query and set parameters."""
        try:
            # Load the library
            if self.libqhyccd is None:
                self.libqhyccd = load_qhyccd_library(self._library_path)

            # Initialize resources
            res = self.libqhyccd.InitQHYCCDResource()
            if res != QHY_SUCCESS:
                raise RuntimeError("InitQHYCCDResource failed")

            # Scan for cameras
            cnt = self.libqhyccd.ScanQHYCCD()
            if not cnt:
                raise RuntimeError("No QHYCCD cameras found")

            logger.debug(f"Found {cnt} QHYCCD camera(s)")

            # Enumerate all cameras and match by serial number from config
            matched_index = None
            camera_ids = []
            for i in range(cnt):
                buf = create_string_buffer(64)
                res = self.libqhyccd.GetQHYCCDId(i, buf)
                if res == QHY_SUCCESS:
                    cam_id = buf.value.decode()
                    camera_ids.append(cam_id)
                    logger.debug(f"Camera {i}: {cam_id}")
                    # SDK IDs look like e.g. "QHY600M-954e9347bc645f17e"
                    # Match the serial_number portion after the dash
                    if (
                        matched_index is None
                        and self._config.serial_number
                        and self._config.serial_number in cam_id
                    ):
                        matched_index = i

            if matched_index is None:
                if self._config.serial_number:
                    logger.warning(
                        f"No camera matching serial '{self._config.serial_number}' found in "
                        f"{camera_ids}, falling back to camera 0"
                    )
                matched_index = 0

            # Re-read the matched camera's ID into a fresh buffer for OpenQHYCCD
            open_buf = create_string_buffer(64)
            self.libqhyccd.GetQHYCCDId(matched_index, open_buf)
            self._camera_model = open_buf.value.decode()

            # Open the camera
            self.handle = self.libqhyccd.OpenQHYCCD(open_buf)
            if self.handle is None:
                raise RuntimeError("OpenQHYCCD returned null handle")

            logger.debug(f"Opened camera {matched_index}: {self._camera_model}")

            # Get firmware version
            fwv = create_string_buffer(4)
            res = self.libqhyccd.GetQHYCCDFPGAVersion(self.handle, c_uint8(0), fwv)
            if res == QHY_SUCCESS:
                year, month, day = fwv.raw[0], fwv.raw[1], fwv.raw[2]
                self._firmware_version = f"20{year:02d}{month:02d}{day:02d}"
                logger.debug(f"Camera firmware version: {self._firmware_version}")
            else:
                logger.warning("Could not read FPGA version")

            # SDK initialization must happen BEFORE querying chip properties.
            # The correct QHYCCD SDK sequence is:
            #   OpenQHYCCD → SetQHYCCDReadMode → SetQHYCCDStreamMode → InitQHYCCD
            # Only then will GetQHYCCDChipInfo etc. return correct values.
            self._init_library()

            # Now query camera properties from the SDK
            self._query_camera_properties()

            # Set remaining default parameters (temperature, gain, offset, binning, etc.)
            self._set_default_parameters()

            # Use camera model as sensor name
            self._sensor_name = self._camera_model

            self._connected = True
            self._camera_state = CameraState.IDLE
            self._image_ready = False
            logger.info(f"Connected to camera {self._config.entity}")

        except Exception as e:
            logger.error(f"Connection failed for {self._config.entity}: {e}")
            self._connected = False
            self._camera_state = CameraState.ERROR
            raise
        finally:
            self._connecting = False

    def _init_library(self) -> None:
        # Set initial readout mode
        defaults = self._config.defaults
        res = self.libqhyccd.SetQHYCCDReadMode(
            self.handle, c_uint32(defaults.readout_mode)
        )
        if res != QHY_SUCCESS:
            logger.warning(f"SetQHYCCDReadMode({defaults.readout_mode}) failed")

        # Set stream mode to single frame
        res = self.libqhyccd.SetQHYCCDStreamMode(self.handle, c_uint8(0))
        if res != QHY_SUCCESS:
            raise RuntimeError("SetQHYCCDStreamMode failed")

        # Initialize the camera
        res = self.libqhyccd.InitQHYCCD(self.handle)
        if res != QHY_SUCCESS:
            raise RuntimeError("InitQHYCCD failed")

        logger.debug("SDK initialized (ReadMode → StreamMode → InitQHYCCD)")

    def _query_camera_properties(self) -> None:
        """Query all camera properties from the library."""

        # Chip info: sensor size, pixel size, bit depth
        chip_w = c_double()
        chip_h = c_double()
        img_w = c_uint32()
        img_h = c_uint32()
        pix_w = c_double()
        pix_h = c_double()
        bpp = c_uint32()

        res = self.libqhyccd.GetQHYCCDChipInfo(
            self.handle,
            byref(chip_w),
            byref(chip_h),
            byref(img_w),
            byref(img_h),
            byref(pix_w),
            byref(pix_h),
            byref(bpp),
        )
        if res != QHY_SUCCESS:
            raise RuntimeError("GetQHYCCDChipInfo failed")

        self._camera_x_size = img_w.value
        self._camera_y_size = img_h.value
        self._pixel_size_x = pix_w.value
        self._pixel_size_y = pix_h.value

        logger.debug(
            f"Chip info: {self._camera_x_size}x{self._camera_y_size}, "
            f"pixel size: {self._pixel_size_x}x{self._pixel_size_y} um, "
            f"bpp: {bpp.value}"
        )

        # Query effective area for debug purposes
        eff_sx = c_uint32()
        eff_sy = c_uint32()
        eff_w = c_uint32()
        eff_h = c_uint32()
        res = self.libqhyccd.GetQHYCCDEffectiveArea(
            self.handle, byref(eff_sx), byref(eff_sy), byref(eff_w), byref(eff_h)
        )
        if res == QHY_SUCCESS:
            logger.debug(
                f"Effective area: ({eff_sx.value},{eff_sy.value}) {eff_w.value}x{eff_h.value}"
            )

        # Exposure limits
        exp_min = c_double()
        exp_max = c_double()
        exp_step = c_double()
        res = self.libqhyccd.GetQHYCCDParamMinMaxStep(
            self.handle,
            QHY_CONTROL.EXPOSURE,
            byref(exp_min),
            byref(exp_max),
            byref(exp_step),
        )
        if res != QHY_SUCCESS:
            raise RuntimeError("GetQHYCCDParamMinMaxStep(EXPOSURE) failed")
        # SDK reports exposure in microseconds, ASCOM uses seconds
        self._exposure_min = exp_min.value / 1e6
        self._exposure_max = exp_max.value / 1e6
        self._exposure_resolution = exp_step.value / 1e6
        logger.debug(
            f"Exposure range: {self._exposure_min:.6f} - {self._exposure_max:.1f} s in increments of {self._exposure_resolution} s"
        )

        # Gain limits
        gain_min = c_double()
        gain_max = c_double()
        gain_step = c_double()
        res = self.libqhyccd.GetQHYCCDParamMinMaxStep(
            self.handle,
            QHY_CONTROL.GAIN,
            byref(gain_min),
            byref(gain_max),
            byref(gain_step),
        )
        if res != QHY_SUCCESS:
            raise RuntimeError("GetQHYCCDParamMinMaxStep(GAIN) failed")
        self._gain_min = int(gain_min.value)
        self._gain_max = int(gain_max.value)
        logger.debug(f"Gain range: {self._gain_min} - {self._gain_max}")

        # Offset limits
        off_min = c_double()
        off_max = c_double()
        off_step = c_double()
        res = self.libqhyccd.GetQHYCCDParamMinMaxStep(
            self.handle,
            QHY_CONTROL.OFFSET,
            byref(off_min),
            byref(off_max),
            byref(off_step),
        )
        if res != QHY_SUCCESS:
            raise RuntimeError("GetQHYCCDParamMinMaxStep(OFFSET) failed")
        self._offset_min = int(off_min.value)
        self._offset_max = int(off_max.value)
        logger.debug(f"Offset range: {self._offset_min} - {self._offset_max}")

        # Readout modes
        self._get_available_readout_modes()

        # Binning modes
        self._get_available_binnings()

        # Full well capacities
        self._get_full_well_capacities()

    def _get_available_readout_modes(self):
        num_modes = c_uint32()
        res = self.libqhyccd.GetQHYCCDNumberOfReadModes(self.handle, byref(num_modes))
        if res == QHY_SUCCESS and num_modes.value > 0:
            self._readout_modes = []
            for i in range(num_modes.value):
                name_buf = create_string_buffer(64)
                res = self.libqhyccd.GetQHYCCDReadModeName(
                    self.handle, c_uint32(i), name_buf
                )
                if res == QHY_SUCCESS:
                    self._readout_modes.append(name_buf.value.decode())
                else:
                    self._readout_modes.append(f"Mode {i}")
            logger.debug(f"Readout modes: {self._readout_modes}")

        else:
            logger.warning("Could not query readout modes, using Default")
            self._readout_modes = ["Default"]

    def _get_available_binnings(self):
        """Probe library for supported binning modes and set min and max bin accordingly."""
        bin_controls = {
            1: QHY_CONTROL.CAM_BIN1X1MODE,
            2: QHY_CONTROL.CAM_BIN2X2MODE,
            3: QHY_CONTROL.CAM_BIN3X3MODE,
            4: QHY_CONTROL.CAM_BIN4X4MODE,
            6: QHY_CONTROL.CAM_BIN6X6MODE,
            8: QHY_CONTROL.CAM_BIN8X8MODE,
        }
        max_bin = 1
        for bin_val, control_id in bin_controls.items():
            if (
                self.libqhyccd.IsQHYCCDControlAvailable(self.handle, control_id)
                == QHY_SUCCESS
            ):
                logger.debug(f"Binning {bin_val}x{bin_val} supported")
                max_bin = bin_val
            else:
                logger.debug(f"Binning {bin_val}x{bin_val} not supported")
        self._max_bin_x = max_bin
        self._max_bin_y = max_bin

    def _get_full_well_capacities(self):
        """Query full well capacity for each supported binning mode at minimum gain."""
        self._fullwellcapacities = {}
        if (
            self.libqhyccd.IsQHYCCDControlAvailable(self.handle, QHY_CONTROL.CURVE_FULL_WELL)
            != QHY_SUCCESS
        ):
            logger.warning("QHYCCD_curveFullWell not available, setting all to 0")
            for bin_val in range(1, self._max_bin_x + 1):
                self._full_well_capacities[bin_val] = 0.0
            return
        c_fullwell = c_double()
        for bin_val in range(1, self._max_bin_x + 1):
            status = self.libqhyccd.SetQHYCCDBinMode(
                self.handle, c_uint32(bin_val), c_uint32(bin_val)
            )
            if status != QHY_SUCCESS:
                logger.warning(f"SetQHYCCDBinMode({bin_val}x{bin_val}) failed")
                self._full_well_capacities[bin_val] = 0.0
                continue
            ret = self.libqhyccd.QHYCCD_curveFullWell(
                self.handle, c_double(self._gain_min), byref(c_fullwell)
            )
            if ret == QHY_SUCCESS:
                self._full_well_capacities[bin_val] = c_fullwell.value
                logger.debug(
                    f"Full well at {bin_val}x{bin_val}, gain {int(self._gain_min)} for readout mode {self._readout_mode}: "
                    f"{c_fullwell.value:.0f} e-"
                )
            else:
                logger.warning(
                    f"QHYCCD_curveFullWell failed for {bin_val}x{bin_val}"
                )
                self._full_well_capacities[bin_val] = 0.0
        # Restore binning to current setting
        self.libqhyccd.SetQHYCCDBinMode(
            self.handle, c_uint32(self._bin_x), c_uint32(self._bin_y)
        )

    def _set_default_parameters(self) -> None:
        """Set default parameters from config. Called AFTER _init_sdk and _query_camera_properties."""
        defaults = self._config.defaults

        # Readout mode
        self._readout_mode = defaults.readout_mode

        # Enable GPS time stamping (do not raise on failure)
        res = self.libqhyccd.SetQHYCCDParam(self.handle, QHY_CONTROL.GPS, c_double(1.0))
        if res != QHY_SUCCESS:
            logger.warning("Could not enable GPS timestamping")

        # CCD temperature
        self.set_ccd_temperature = defaults.temperature

        # Set bit depth to 16
        res = self.libqhyccd.SetQHYCCDBitsMode(self.handle, c_uint32(16))
        if res != QHY_SUCCESS:
            logger.warning("Could not set 16-bit mode")

        # Set gain and offset
        res = self.libqhyccd.SetQHYCCDParam(
            self.handle, QHY_CONTROL.GAIN, c_double(float(defaults.gain))
        )
        if res != QHY_SUCCESS:
            logger.warning("Could not set default gain")

        res = self.libqhyccd.SetQHYCCDParam(
            self.handle, QHY_CONTROL.OFFSET, c_double(float(defaults.offset))
        )
        if res != QHY_SUCCESS:
            logger.warning("Could not set default offset")

        # Lower USB traffic
        res = self.libqhyccd.SetQHYCCDParam(
            self.handle, QHY_CONTROL.USBTRAFFIC, c_double(defaults.usb_traffic)
        )
        if res != QHY_SUCCESS:
            logger.warning("Could not set USB traffic")

        # Set binning and full-frame ROI
        self._start_x = 0
        self._start_y = 0
        self._bin_x = 1
        self._bin_y = 1
        self._num_x = self._camera_x_size
        self._num_y = self._camera_y_size

        # Apply default binning through the unified ROI setter
        self._set_roi(bin_x=defaults.binning, bin_y=defaults.binning)

        logger.info(f"Default parameters set for {self._config.entity}")

    @property
    def connected(self) -> bool:
        return self._connected

    @connected.setter
    def connected(self, value: bool) -> None:
        if value and not self._connected:
            self.connect()
        elif not value and self._connected:
            self.disconnect()

    @property
    def connecting(self) -> bool:
        return self._connecting

    def disconnect(self) -> None:
        if not self._connected:
            return
        try:
            if self._camera_state in (CameraState.EXPOSING, CameraState.READING):
                self.abort_exposure()
            if self.handle is not None:
                self.libqhyccd.CloseQHYCCD(self.handle)
            self._connected = False
            self._camera_state = CameraState.IDLE
            logger.info(f"Disconnected from camera {self._config.entity}")
        except Exception as e:
            logger.error(f"Disconnect error: {e}")

    ######################
    # ICamera properties #
    ######################
    @property
    def bin_x(self) -> int:
        return self._bin_x

    @bin_x.setter
    def bin_x(self, value: int) -> None:
        self._set_roi(bin_x=value, bin_y=value)

    @property
    def bin_y(self) -> int:
        return self._bin_y

    @bin_y.setter
    def bin_y(self, value: int) -> None:
        self._set_roi(bin_x=value, bin_y=value)

    @property
    def camera_state(self) -> CameraState:
        return self._camera_state

    @property
    def camera_x_size(self) -> int:
        return self._camera_x_size

    @property
    def camera_y_size(self) -> int:
        return self._camera_y_size

    @property
    def can_abort_exposure(self) -> bool:
        return True

    @property
    def can_asymmetric_bin(self) -> bool:
        return False

    @property
    def can_fast_readout(self) -> bool:
        return False

    @property
    def can_get_cooler_power(self) -> bool:
        return True

    @property
    def can_pulse_guide(self) -> bool:
        return False

    @property
    def can_set_ccd_temperature(self) -> bool:
        return True

    @property
    def can_stop_exposure(self) -> bool:
        return False

    @property
    def ccd_temperature(self) -> float:
        val = self.libqhyccd.GetQHYCCDParam(self.handle, QHY_CONTROL.CURTEMP)
        return val

    @property
    def cooler_on(self) -> bool:
        val = self.libqhyccd.GetQHYCCDParam(self.handle, QHY_CONTROL.CURPWM)
        return val > 0

    @property
    def cooler_power(self) -> float:
        val = self.libqhyccd.GetQHYCCDParam(self.handle, QHY_CONTROL.CURPWM)
        return val / 255.0 * 100.0

    @property
    def exposure_max(self) -> float:
        return self._exposure_max

    @property
    def exposure_min(self) -> float:
        return self._exposure_min

    @property
    def exposure_resolution(self) -> float:
        return self._exposure_resolution

    @property
    def full_well_capacity(self) -> float:
        return self._full_well_capacities[self._bin_x]

    @property
    def gain(self) -> int:
        val = self.libqhyccd.GetQHYCCDParam(self.handle, QHY_CONTROL.GAIN)
        return int(val)

    @gain.setter
    def gain(self, value: int) -> None:
        res = self.libqhyccd.SetQHYCCDParam(
            self.handle, QHY_CONTROL.GAIN, c_double(float(value))
        )
        if res != QHY_SUCCESS:
            raise RuntimeError("SetQHYCCDParam(GAIN) failed")

    @property
    def gain_max(self) -> int:
        return self._gain_max

    @property
    def gain_min(self) -> int:
        return self._gain_min

    @property
    def has_shutter(self) -> bool:
        return False

    @property
    def image_array(self) -> np.ndarray:
        """Returns a 2D numpy array of the last captured image."""
        if not self._image_ready:
            raise RuntimeError("No image ready")

        self._camera_state = CameraState.DOWNLOADING

        # Get current ROI from camera
        roi_sx = c_uint32()
        roi_sy = c_uint32()
        roi_nx = c_uint32()
        roi_ny = c_uint32()
        res = self.libqhyccd.GetQHYCCDCurrentROI(
            self.handle, byref(roi_sx), byref(roi_sy), byref(roi_nx), byref(roi_ny)
        )
        if res != QHY_SUCCESS:
            raise RuntimeError("GetQHYCCDCurrentROI failed")

        # Allocate buffer
        mem_len = self.libqhyccd.GetQHYCCDMemLength(self.handle)
        data = (c_uint16 * (mem_len // 2 + 1))()

        # Get precise exposure timing info (optional — may not be supported by all cameras)
        has_precise_info = False
        pixel_period_ps = c_uint32()
        line_period_ns = c_uint32()
        frame_period_us = c_uint32()
        clocks_per_line = c_uint32()
        lines_per_frame = c_uint32()
        actual_exposure_us = c_uint32()
        is_long_exposure = c_uint8()

        res = self.libqhyccd.GetQHYCCDPreciseExposureInfo(
            self.handle,
            byref(pixel_period_ps),
            byref(line_period_ns),
            byref(frame_period_us),
            byref(clocks_per_line),
            byref(lines_per_frame),
            byref(actual_exposure_us),
            byref(is_long_exposure),
        )
        if res == QHY_SUCCESS:
            has_precise_info = True
        else:
            logger.warning(
                "GetQHYCCDPreciseExposureInfo not supported, using requested duration"
            )

        readout_offset_us_val = 0.0
        readout_offset_tmp = c_double()
        res = self.libqhyccd.GetQHYCCDRollingShutterEndOffset(
            self.handle, c_uint32(0), byref(readout_offset_tmp)
        )
        if res == QHY_SUCCESS:
            readout_offset_us_val = readout_offset_tmp.value
        else:
            logger.warning("GetQHYCCDRollingShutterEndOffset not supported")

        # Retrieve the image
        img_w = c_uint32()
        img_h = c_uint32()
        bpp = c_uint32()
        channels = c_uint32()

        res = self.libqhyccd.GetQHYCCDSingleFrame(
            self.handle, byref(img_w), byref(img_h), byref(bpp), byref(channels), data
        )
        if res != QHY_SUCCESS:
            self._camera_state = CameraState.ERROR
            raise RuntimeError("GetQHYCCDSingleFrame failed")

        img = (
            np.frombuffer(
                data, dtype=np.uint16, offset=0, count=img_w.value * img_h.value
            )
            .reshape(img_h.value, img_w.value)
            .copy()
        )

        # Parse GPS timing information
        try:
            gps = QHY_GPS.from_address(img.ctypes.data)
            vsync_status = gps.create_status(gps.NowFlag)
            if vsync_status in ["LOCKED", "LOCKING"] and has_precise_info:
                end_seconds = (
                    gps.NowSeconds
                    + readout_offset_us_val / 1e6
                    + line_period_ns.value / 1e9 * 2 * (roi_sy.value // 2)
                )
                start_time = gps.create_timestamp(
                    end_seconds - actual_exposure_us.value / 1e6, gps.NowCounts
                )
                end_time = gps.create_timestamp(end_seconds, gps.NowCounts)
                self._timing["DATE-OBS"] = start_time
                self._last_exposure_start_time = start_time
                self._timing["DATE-END"] = end_time
                self._last_exposure_duration = (
                    Time(end_time, format="isot") - Time(start_time, format="isot")
                ).to_value("sec")
                self._timing["TIME-SRC"] = "GPS"
                self._timing["GPS-SEQN"] = gps.SequenceNumber
                self._timing["GPS-LAT"] = gps.Latitude
                self._timing["GPS-LON"] = gps.Longitude
                logger.debug(
                    f"GPS timing: start={start_time}, end={end_time}, status={vsync_status}"
                )
            else:
                if vsync_status not in ["LOCKED", "LOCKING"]:
                    logger.warning(f"GPS is {vsync_status}, using system clock")
                else:
                    logger.warning(
                        "GPS locked but no precise exposure info, using system clock"
                    )
                self._use_system_clock_timing()
        except Exception as e:
            logger.warning(f"GPS parsing failed: {e}, using system clock")
            self._use_system_clock_timing()

        self._camera_state = CameraState.IDLE
        self._image_ready = False

        logger.debug(f"Image: {img.shape[1]}x{img.shape[0]}, dtype={img.dtype}")
        return img

    def _use_system_clock_timing(self) -> None:
        """Fallback timing using system clock and requested exposure duration.

        Called when GPS is unavailable or precise exposure info is not supported.
        Uses DATE-OBS (set in start_exposure) and _last_exposure_duration to compute DATE-END.
        """
        if "DATE-OBS" in self._timing and self._last_exposure_duration is not None:
            self._timing["DATE-END"] = (
                Time(self._timing["DATE-OBS"])
                + timedelta(seconds=self._last_exposure_duration)
            ).isot
        self._timing["TIME-SRC"] = "SYSCLOCK"

    @property
    def image_ready(self) -> bool:
        return self._image_ready

    @property
    def last_exposure_duration(self) -> float:
        return self._last_exposure_duration

    @property
    def last_exposure_start_time(self) -> str:
        return self._last_exposure_start_time

    @property
    def max_adu(self) -> int:
        return 65535

    @property
    def max_bin_x(self) -> int:
        return self._max_bin_x

    @property
    def max_bin_y(self) -> int:
        return self._max_bin_y

    @property
    def num_x(self) -> int:
        return self._num_x

    @num_x.setter
    def num_x(self, value: int) -> None:
        self._set_roi(num_x=value)

    @property
    def num_y(self) -> int:
        return self._num_y

    @num_y.setter
    def num_y(self, value: int) -> None:
        self._set_roi(num_y=value)

    @property
    def offset(self) -> int:
        val = self.libqhyccd.GetQHYCCDParam(self.handle, QHY_CONTROL.OFFSET)
        return int(val)

    @offset.setter
    def offset(self, value: int) -> None:
        res = self.libqhyccd.SetQHYCCDParam(
            self.handle, QHY_CONTROL.OFFSET, c_double(float(value))
        )
        if res != QHY_SUCCESS:
            raise RuntimeError("SetQHYCCDParam(OFFSET) failed")

    @property
    def offset_max(self) -> int:
        return self._offset_max

    @property
    def offset_min(self) -> int:
        return self._offset_min

    @property
    def pixel_size_x(self) -> float:
        return self._pixel_size_x

    @property
    def pixel_size_y(self) -> float:
        return self._pixel_size_y

    @property
    def readout_mode(self) -> int:
        return self._readout_mode

    @readout_mode.setter
    def readout_mode(self, value: int) -> None:
        if value < 0 or value >= len(self._readout_modes):
            raise ValueError(
                f"ReadoutMode {value} out of range 0-{len(self._readout_modes) - 1}"
            )
        res = self.libqhyccd.SetQHYCCDReadMode(self.handle, c_uint32(value))
        if res != QHY_SUCCESS:
            raise RuntimeError(f"SetQHYCCDReadMode({value}) failed")
        self._readout_mode = value
        logger.info(f"Set readout mode to {self._readout_modes[value]}")

        # Re-populate full well capacities
        self._get_full_well_capacities()

    @property
    def readout_modes(self) -> List[str]:
        return self._readout_modes

    @property
    def sensor_name(self) -> str:
        return self._sensor_name

    @property
    def sensor_type(self) -> SensorType:
        return SensorType.MONOCHROME

    @property
    def set_ccd_temperature(self) -> float:
        return self._set_ccd_temperature

    @set_ccd_temperature.setter
    def set_ccd_temperature(self, value: float) -> None:
        res = self.libqhyccd.SetQHYCCDParam(
            self.handle, QHY_CONTROL.COOLER, c_double(value)
        )
        if res != QHY_SUCCESS:
            raise RuntimeError("SetQHYCCDParam(COOLER) failed")
        self._set_ccd_temperature = value
        logger.debug(f"Set CCD temperature to {value}")

    @property
    def start_x(self) -> int:
        return self._start_x

    @start_x.setter
    def start_x(self, value: int) -> None:
        self._set_roi(start_x=value)

    @property
    def start_y(self) -> int:
        return self._start_y

    @start_y.setter
    def start_y(self, value: int) -> None:
        self._set_roi(start_y=value)

    @property
    def timestamp(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _get_roi(self) -> None:
        """Read current ROI from camera and convert to binned pixels."""
        sx = c_uint32()
        sy = c_uint32()
        nx = c_uint32()
        ny = c_uint32()
        res = self.libqhyccd.GetQHYCCDCurrentROI(
            self.handle, byref(sx), byref(sy), byref(nx), byref(ny)
        )
        if res != QHY_SUCCESS:
            logger.warning("Could not read current ROI")
            return
        # The library returns unbinned pixel values for start but binned sizes for width/height
        # Actually, the QHY SDK SetQHYCCDResolution takes (startx, starty, sizex, sizey)
        # where sizex/sizey are already in binned pixels after SetQHYCCDBinMode
        self._start_x = sx.value
        self._start_y = sy.value
        self._num_x = nx.value
        self._num_y = ny.value

    def _set_roi(
        self, start_x=None, num_x=None, bin_x=None, start_y=None, num_y=None, bin_y=None
    ) -> None:
        """
        Set ROI with proper validation and ordering.

        All start/num values are in binned pixels per ASCOM spec.
        When binning changes, ROI is reset to full frame at the new binning.
        """
        bx = bin_x if bin_x is not None else self._bin_x
        by = bin_y if bin_y is not None else self._bin_y
        binning_changed = bx != self._bin_x or by != self._bin_y

        # Validate binning
        if bx < 1 or bx > self._max_bin_x:
            raise ValueError(f"BinX {bx} not in range 1-{self._max_bin_x}")
        if by < 1 or by > self._max_bin_y:
            raise ValueError(f"BinY {by} not in range 1-{self._max_bin_y}")

        # When binning changes, reset to full frame at new binning
        if binning_changed:
            # Apply binning to hardware
            res = self.libqhyccd.SetQHYCCDBinMode(
                self.handle, c_uint32(bx), c_uint32(by)
            )
            if res != QHY_SUCCESS:
                raise RuntimeError(f"SetQHYCCDBinMode({bx}, {by}) failed")
            self._bin_x = bx
            self._bin_y = by

            # Reset to full frame at new binning
            max_binned_x = self._camera_x_size // bx
            max_binned_y = self._camera_y_size // by
            sx = 0
            sy = 0
            nx = max_binned_x
            ny = max_binned_y
        else:
            sx = start_x if start_x is not None else self._start_x
            sy = start_y if start_y is not None else self._start_y
            nx = num_x if num_x is not None else self._num_x
            ny = num_y if num_y is not None else self._num_y

        # Max binned dimensions
        max_binned_x = self._camera_x_size // bx
        max_binned_y = self._camera_y_size // by

        # Validate and clamp start values
        if sx < 0:
            sx = 0
        if sy < 0:
            sy = 0
        if sx >= max_binned_x:
            sx = max_binned_x - 1
        if sy >= max_binned_y:
            sy = max_binned_y - 1

        # Validate and clamp num values to fit within remaining space
        max_nx = max_binned_x - sx
        max_ny = max_binned_y - sy

        if nx < 1:
            nx = 1
        if ny < 1:
            ny = 1
        if nx > max_nx:
            nx = max_nx
        if ny > max_ny:
            ny = max_ny

        # Apply resolution to hardware
        res = self.libqhyccd.SetQHYCCDResolution(
            self.handle, c_uint32(sx), c_uint32(sy), c_uint32(nx), c_uint32(ny)
        )
        if res != QHY_SUCCESS:
            raise RuntimeError(f"SetQHYCCDResolution({sx}, {sy}, {nx}, {ny}) failed")

        # Store values
        self._start_x = sx
        self._start_y = sy
        self._num_x = nx
        self._num_y = ny

    ###################
    # ICamera methods #
    ###################
    def start_exposure(self, duration: float, light: bool) -> None:
        if self._camera_state != CameraState.IDLE:
            raise RuntimeError("Camera is not idle")

        # Set the exposure time (library uses microseconds)
        res = self.libqhyccd.SetQHYCCDParam(
            self.handle, QHY_CONTROL.EXPOSURE, c_double(duration * 1e6)
        )
        if res != QHY_SUCCESS:
            raise RuntimeError("SetQHYCCDParam(EXPOSURE) failed")

        # Start the exposure
        res = self.libqhyccd.ExpQHYCCDSingleFrame(self.handle)
        if res != QHY_SUCCESS:
            raise RuntimeError("ExpQHYCCDSingleFrame failed")

        self._camera_state = CameraState.EXPOSING
        self._image_ready = False

        # Record start time (may be overwritten by GPS metadata)
        self._last_exposure_duration = duration
        self._timing["DATE-OBS"] = Time.now().isot
        self._last_exposure_start_time = self._timing["DATE-OBS"]

        # Start background state transition threads
        self._exposure_complete.clear()
        self._readout_complete.clear()
        Thread(target=self._exposure_timer, args=(duration,), daemon=True).start()
        Thread(target=self._readout_timer, daemon=True).start()
        Thread(target=self._wait_for_image, daemon=True).start()

    def _exposure_timer(self, duration: float) -> None:
        """Timer thread to transition camera state after exposure completes."""
        time.sleep(duration)
        self._camera_state = CameraState.READING
        self._exposure_complete.set()

    def _readout_timer(self) -> None:
        """Timer thread to signal readout completion."""
        self._exposure_complete.wait()
        # No way to monitor transition, just blow through it for now
        time.sleep(0.1)
        self._readout_complete.set()

    def _wait_for_image(self) -> None:
        """Wait for readout to complete, then mark image as ready."""
        self._readout_complete.wait()
        self._camera_state = CameraState.DOWNLOADING
        self._image_ready = True

    def abort_exposure(self) -> None:
        if self._camera_state in (
            CameraState.EXPOSING,
            CameraState.READING,
            CameraState.WAITING,
        ):
            res = self.libqhyccd.CancelQHYCCDExposingAndReadout(self.handle)
            if res != QHY_SUCCESS:
                logger.warning("CancelQHYCCDExposingAndReadout failed")
            self._camera_state = CameraState.IDLE
            self._image_ready = False
            self._exposure_complete.set()
            self._readout_complete.set()
