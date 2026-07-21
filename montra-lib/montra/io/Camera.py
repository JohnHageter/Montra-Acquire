from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, Any, Tuple
import numpy as np
import time


class Parameter(Enum):
    FRAME_RATE = 0
    EXPOSURE = 1
    GAIN = 2
    WIDTH = 3
    HEIGHT = 4
    X_OFFSET = 5
    Y_OFFSET = 6


class Camera(ABC):
    """Abstract base class for all camera backends.

    Subclasses implement the five abstract methods (_open, _close, _set, _watch,
    _reset_watch_window, _read_frame).  The public methods (open, close, set, watch,
    read) add state-checking wrappers around those.

    Threading:
        open() / close() / set() / watch() are called from the CameraWorker thread.
        read() is called from that thread's polling timer (_read_frame slot).

    Watch window:
        Hardware cameras (IDS, FLIR) apply the ROI at the sensor level via _watch().
        Software cameras (OpenCV, Test) store the ROI and crop in _read_frame().
        Both patterns are valid implementations of the abstract interface.

    Pixel format:
        All backends must return BGR (3-channel uint8) frames from _read_frame() so
        that CameraWorker, the preview label, and VideoWriter receive a consistent
        format.  Mono sensors should replicate the single channel to 3-channel BGR.

    Blocking flag:
        Set is_blocking = True on backends whose _read_frame() blocks until the
        hardware delivers a frame (e.g. IDS WaitForFinishedBuffer, FLIR GetNextImage).
        CameraWorker uses this flag to choose the polling strategy: blocking cameras
        use a short restart interval so the timer fires immediately after each read;
        non-blocking cameras let the timer run continuously at the software fps rate.
    """

    # True for cameras whose read() blocks until the hardware delivers a frame.
    # False for cameras that return immediately with the latest buffered frame.
    is_blocking: bool = False

    def __init__(self):
        self.cam = None
        self.watch_window: Optional[Tuple[
            float, float, float, float
        ]] = None # x_off, width, y_off, height
        self._is_open: bool = False

    def open(self) -> bool:
        """
        Open the camera device.
        """
        if self._is_open:
            return True

        try:
            self._open()
            self._is_open = True
            return True
        except Exception as e:
            self._is_open = False

            print(type(e).__name__, e)
            raise CameraError("Failed to open camera.") from e

    def close(self) -> None:
        """
        Close and release the camera.
        """
        if not self._is_open:
            return

        try:
            self._close()
        finally:
            self._is_open = False
            self.cam = None

    def watch(self, x_off=None, width=None, y_off=None, height=None):
        try:
            if width is None or height is None or x_off is None or y_off is None:
                self._reset_watch_window()
                return True

            if width <= 0 or height <= 0 or x_off < 0 or y_off < 0:
                return False
            self._watch(x_off, width, y_off, height)
            return True
        except Exception:
            return False

    def set(self, parameter: Parameter, value: Any) -> bool:
        """
        Set a camera parameter (exposure, gain, fps, etc).
        """
        if not self._is_open:
            raise InvalidStateError("Camera must be opened before setting parameters.")

        try:
            return bool(self._set(parameter, value))
        except Exception as e:
            raise CameraError(f"Failed to set parameter '{parameter}'") from e

    def read(self) -> Tuple[bool, np.ndarray, float]:
        """
        Read a frame from the camera.

        Returns:
            success: bool
            frame: ndarray or None
            timestamp: perf_counter timestamp
        """
        if not self._is_open:
            raise InvalidStateError("Camera must be opened before reading.")

        success, frame = self._read_frame()
        timestamp = time.perf_counter()
        return success, frame, timestamp

    @abstractmethod
    def _open(self) -> None:
        """
        Backend-specific open.
        Must raise on fatal failure.
        """
        ...

    @abstractmethod
    def _close(self) -> None:
        """
        Backend-specific close.
        """
        ...

    @abstractmethod
    def _set(self, parameter: Parameter, value: Any) -> bool:
        """
        Backend-specific parameter setter.
        Return False if unsupported or rejected.
        """
        ...

    @abstractmethod
    def _watch(self, x_off: int, width: int, y_off: int, height: int) -> bool:
        """Set an ROI within the camera.

        Hardware cameras apply the ROI at the sensor (x_off, width, y_off, height).
        Software cameras store it and crop in _read_frame().
        Return True on success, False if the ROI was rejected.
        """
        ...

    @abstractmethod
    def _reset_watch_window(self) -> None:
        """Reset the watch window to the full sensor field of view."""
        ...

    @abstractmethod
    def _read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Backend-specific frame grab.

        Returns (success, frame).  Must NOT raise on normal capture failure —
        return (False, None) instead.  Frame must be BGR uint8 (3-channel).
        """
        ...


class CameraError(Exception):
    """Base class for all camera-related errors."""


class InvalidStateError(CameraError):
    """Invalid operation for the current camera state."""


class CaptureError(CameraError):
    """Frame capture failed."""
