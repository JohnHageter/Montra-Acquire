import math

import cv2
from typing import Optional, Tuple
import numpy as np
from montra.io.Camera import Camera, CameraError
import platform


class OpenCVCamera(Camera):
    """OpenCV VideoCapture backend for USB webcams and other system cameras.

    is_blocking = False: cap.read() returns immediately with the latest buffered
    frame.  CameraWorker's timer runs continuously at software_fps to pull frames.

    Watch window is applied in software by cropping the raw frame in _read_frame();
    no hardware ROI is set.
    """

    def __init__(self, device_index=0):
        super().__init__()
        self.device_index = device_index
        self.cap: Optional[cv2.VideoCapture] = None

    def _open(self):
        system = platform.system()

        if system == "Windows":
            backend = cv2.CAP_DSHOW
        elif system == "Linux":
            backend = cv2.CAP_V4L2
        elif system == "Darwin": #MacOS
            backend = cv2.CAP_AVFOUNDATION
        else:
            backend = cv2.CAP_ANY  

        self.cap = cv2.VideoCapture(self.device_index, backend)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if not self.cap.isOpened():
            raise RuntimeError(
                f"Failed to open camera {self.device_index} with backend {backend}"
        )

    def _close(self):
        if self.cap:
            self.cap.release()
            self.cap = None

    def _set(self, parameter, value) -> bool:
        from montra.io.Camera import Parameter
        if not self.cap:
            return False

        try:
            if parameter in (Parameter.EXPOSURE, "exposure"):
                self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
                
                if self.cap.getBackendName() == "DSHOW":
                    # DSHOW encodes exposure as log₂ seconds; convert from microseconds
                    value = math.log2(value / 1e6)
                    
                return bool(self.cap.set(cv2.CAP_PROP_EXPOSURE, value))

            elif parameter in (Parameter.GAIN, "gain"):
                return bool(self.cap.set(cv2.CAP_PROP_GAIN, value))

            elif parameter in (Parameter.FRAME_RATE, "fps"):
                return bool(self.cap.set(cv2.CAP_PROP_FPS, value))

            else:
                return False

        except Exception:
            return False

    def _watch(self, x_off, width, y_off, height) -> bool:
        self.watch_window = x_off, width, y_off, height
        return True

    def _reset_watch_window(self) -> None:
        self.watch_window = None

    def _read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        if self.cap is None or not self.cap.isOpened():
            raise CameraError("Cannot read frame while camera is closed.")

        ret, frame = self.cap.read()

        if not ret or frame is None:
            return False, None

        if self.watch_window is not None:
            x_off, width, y_off, height = self.watch_window
            x0 = max(0, x_off)
            y0 = max(0, y_off)
            x1 = min(x0 + width, frame.shape[1])
            y1 = min(y0 + height, frame.shape[0])
            if x1 > x0 and y1 > y0:
                frame = frame[y0:y1, x0:x1]

        return True, frame
