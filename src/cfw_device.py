"""
Filter wheel device driver using the QHYCCD SDK CFW functions.

Controls a filter wheel connected to the camera via the 4-pin CFW cable.
Requires a connected CameraDevice instance (shares the same SDK handle).
"""

import threading
import time
from datetime import datetime, timezone
from typing import List, Optional

from ctypes import c_char_p, c_uint32, create_string_buffer, POINTER

from config import CFWConfig
from log import get_logger


logger = get_logger()

QHY_SUCCESS = 0


class CFWBusyError(RuntimeError):
    """Raised when a command is rejected because the wheel is currently moving."""


class CFWDevice:
    """Filter wheel controlled via the QHYCCD SDK (4-pin CFW cable to camera)."""

    def __init__(self, cfw_config: CFWConfig, camera_device):
        """
        Args:
            cfw_config: Filter wheel configuration (names, offsets, etc.)
            camera_device: A CameraDevice instance whose SDK handle we share.
        """
        self._config = cfw_config
        self._camera = camera_device

        self._connected = False
        self._connecting = False
        self._moving = False
        self._position: int = -1
        self._move_target: int = -1

    @property
    def _handle(self):
        """Borrow the camera's SDK handle."""
        return self._camera.handle

    @property
    def _lib(self):
        """Borrow the camera's loaded library."""
        return self._camera.libqhyccd

    # ─── ASCOM Common ────────────────────────────────────────────────

    def connect(self) -> None:
        """Connect to the filter wheel (auto-connects camera if needed)."""
        if self._connected or self._connecting:
            return

        self._connecting = True
        try:
            # Auto-connect the camera if it isn't already connected
            if not self._camera.connected:
                logger.info("Auto-connecting camera for filter wheel...")
                self._camera.connected = True
                if not self._camera.connected:
                    raise RuntimeError(
                        "Failed to auto-connect camera for filter wheel"
                    )

            # Declare CFW function signatures if not already done
            self._ensure_cfw_signatures()

            # Check if CFW is plugged in
            res = self._lib.IsQHYCCDCFWPlugged(self._handle)
            if res != QHY_SUCCESS:
                raise RuntimeError(
                    "No filter wheel detected (IsQHYCCDCFWPlugged failed)"
                )

            # Read initial position
            self._position = self._read_position()
            self._connected = True
            logger.info(
                f"Connected to filter wheel: {self._config.entity} "
                f"(position {self._position})"
            )
        except Exception as e:
            logger.error(f"CFW connect failed: {e}")
            self._connected = False
            raise
        finally:
            self._connecting = False

    def disconnect(self) -> None:
        """Disconnect from the filter wheel."""
        self._connected = False
        self._moving = False
        self._move_target = -1
        self._position = -1
        logger.info(f"Disconnected from filter wheel: {self._config.entity}")

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

    @property
    def entity(self) -> str:
        return self._config.entity

    # ─── IFilterWheel ────────────────────────────────────────────────

    @property
    def focus_offsets(self) -> List[int]:
        return self._config.focus_offsets

    @property
    def names(self) -> List[str]:
        return self._config.names

    @property
    def position(self) -> int:
        """Return current filter position (0-based), or -1 if moving."""
        if self._moving:
            return -1
        return self._position

    @position.setter
    def position(self, value: int) -> None:
        """Command the wheel to move to a position (0-based).

        Per ASCOM IFilterWheelV3, issuing a new position while moving
        redirects the wheel — it does NOT raise an error.
        """
        if not self._connected:
            raise RuntimeError("Filter wheel is not connected")

        num_filters = len(self._config.names)
        if value < 0 or value >= num_filters:
            raise ValueError(
                f"Position {value} out of range (0-{num_filters - 1})"
            )

        # SDK uses ASCII position string
        order = str(value).encode()
        res = self._lib.SendOrder2QHYCCDCFW(self._handle, order, c_uint32(len(order)))
        if res != QHY_SUCCESS:
            raise RuntimeError(f"SendOrder2QHYCCDCFW failed (res={res})")

        # Signal any existing move thread to stop, then start a new one
        self._move_target = value
        self._moving = True
        logger.info(f"Moving filter wheel to position {value}")
        threading.Thread(
            target=self._wait_for_move, args=(value,), daemon=True
        ).start()

    @property
    def timestamp(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # ─── Internal ────────────────────────────────────────────────────

    def _ensure_cfw_signatures(self) -> None:
        """Declare ctypes signatures for CFW functions (idempotent)."""
        lib = self._lib
        if hasattr(lib, "_cfw_sigs_set"):
            return

        lib.IsQHYCCDCFWPlugged.argtypes = [POINTER(c_uint32)]
        lib.IsQHYCCDCFWPlugged.restype = c_uint32

        lib.GetQHYCCDCFWStatus.argtypes = [POINTER(c_uint32), c_char_p]
        lib.GetQHYCCDCFWStatus.restype = c_uint32

        lib.SendOrder2QHYCCDCFW.argtypes = [POINTER(c_uint32), c_char_p, c_uint32]
        lib.SendOrder2QHYCCDCFW.restype = c_uint32

        lib._cfw_sigs_set = True
        logger.debug("CFW ctypes signatures registered")

    def _read_position(self) -> int:
        """Query current filter wheel position from SDK.

        GetQHYCCDCFWStatus writes a short string into the buffer.
        The QHY SDK returns the position as a single byte whose VALUE is
        the 0-based position number (NOT an ASCII character). Some firmware
        versions return ASCII digits, so we handle both.
        """
        buf = create_string_buffer(64)
        res = self._lib.GetQHYCCDCFWStatus(self._handle, buf)
        if res != QHY_SUCCESS:
            logger.warning(f"GetQHYCCDCFWStatus failed (res={res})")
            return -1

        raw = buf.raw
        # The SDK writes at least one byte — check the raw byte value
        byte_val = raw[0]

        # Some QHY firmware returns an ASCII digit character ('0'=0x30, etc.)
        # Others return the raw position number (0x00, 0x01, etc.)
        # A value of 0xFF or similar means "moving" or "unknown"
        num_filters = len(self._config.names)

        if byte_val < num_filters:
            # Raw position byte (0, 1, 2, ...)
            logger.debug(f"CFW status raw byte: {byte_val} -> position {byte_val}")
            return byte_val
        elif ord('0') <= byte_val <= ord('9'):
            # ASCII digit character
            pos = byte_val - ord('0')
            logger.debug(f"CFW status ASCII byte: {chr(byte_val)} -> position {pos}")
            return pos

        # Try decoding as string for multi-byte responses
        try:
            status = buf.value.decode().strip()
            if status and status[0].isdigit():
                pos = int(status[0])
                logger.debug(f"CFW status string: {status!r} -> position {pos}")
                return pos
        except (UnicodeDecodeError, ValueError):
            pass

        logger.debug(f"CFW status unrecognized: raw[0]={byte_val:#04x}, treating as moving")
        return -1

    def _wait_for_move(self, target: int) -> None:
        """Poll CFW status until the target position is reached or timeout.

        If a new move is commanded (self._move_target changes), this thread
        exits silently — the new thread takes over monitoring.

        The QHY SDK may briefly return the OLD position before the wheel
        physically starts moving, so we require seeing a transition:
        either reading -1 (moving) first, or reading the target position
        after a brief settling delay.
        """
        timeout = self._config.timeout
        t0 = time.time()
        saw_moving_or_different = False

        # Brief delay for the move command to take effect in hardware
        time.sleep(0.3)

        while self._moving and self._move_target == target:
            pos = self._read_position()

            if pos == -1 or (pos >= 0 and pos != target):
                # Wheel is either in motion or at an intermediate position
                saw_moving_or_different = True
            elif pos == target:
                if saw_moving_or_different or (time.time() - t0) > 0.5:
                    # We either saw the wheel move, or enough time has passed
                    # that we trust the SDK is reporting the final position
                    self._position = target
                    self._moving = False
                    logger.info(f"Filter wheel arrived at position {target}")
                    return

            if (time.time() - t0) > timeout:
                # Only clear moving state if we're still the active move
                if self._move_target == target:
                    self._moving = False
                    logger.error(
                        f"Filter wheel move to {target} timed out after {timeout}s"
                    )
                    if pos >= 0:
                        self._position = pos
                return

            # Check if this thread was superseded
            if self._move_target != target:
                return

            time.sleep(0.3)
