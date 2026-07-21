import time
import numpy as np
from typing import Any, Optional, Tuple
from montra.io.Camera import Camera, CameraError


class TestCamera(Camera):
    """
    Synthetic camera for UI testing.
    Produces moving gradient frames.
    """

    def __init__(self, width: int = 640, height: int = 480):
        super().__init__()

        self.width = width
        self.height = height

        self.fps = 30.0
        self.exposure = 1.0
        self.gain = 1.0

        self._streaming = False
        self._last_frame: Optional[np.ndarray] = None
        self._last_frame_time = 0.0
        self._frame_counter = 0

        self.watch_x = 0
        self.watch_y = 0
        self.watch_w = width
        self.watch_h = height

    def _open(self) -> None:
        self._frame_counter = 0
        self._last_frame = None
        self._streaming = False

    def _close(self) -> None:
        self._streaming = False
        self._last_frame = None

    def _set(self, key, value: Any) -> bool:
        from montra.io.Camera import Parameter
        try:
            if key in (Parameter.EXPOSURE, "exposure"):
                self.exposure = float(value)
            elif key in (Parameter.GAIN, "gain"):
                self.gain = float(value)
            elif key in (Parameter.FRAME_RATE, "fps"):
                return self._set_framerate(float(value))
            else:
                return False
            return True
        except Exception:
            return False

    def _set_framerate(self, fps: float) -> bool:
        if fps <= 0:
            return False
        self.fps = fps
        return True

    def _watch(self, x_start: int, width: int, y_start: int, height: int) -> bool:
        self.watch_x = max(0, int(x_start))
        self.watch_y = max(0, int(y_start))
        self.watch_w = max(1, int(width))
        self.watch_h = max(1, int(height))
        return True

    def _read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        try:
            if not self._streaming:
                self._do_start_stream()

            frame = self._do_grab_frame()
            return True, frame
        except Exception:
            return False, None

    def _do_start_stream(self):
        self._streaming = True
        self._last_frame_time = 0.0

    def _do_grab_frame(self) -> np.ndarray:
        now = time.time()
        min_interval = 1.0 / self.fps

        if now - self._last_frame_time < min_interval:
            time.sleep(min_interval - (now - self._last_frame_time))

        frame = self._generate_frame()
        frame = self._apply_watch_window(frame)

        self._last_frame = frame
        self._last_frame_time = time.time()
        return frame

    # ---------- synthetic image generation ----------

    def _generate_frame(self) -> np.ndarray:
        speed = max(1, int(self.exposure * 5))
        self._frame_counter = (self._frame_counter + speed) & 0xFF
        c = np.uint8(self._frame_counter)

        x = np.arange(self.width, dtype=np.uint8)
        y = np.arange(self.height, dtype=np.uint8)
        xv, yv = np.meshgrid(x, y)

        frame = np.empty((self.height, self.width, 3), dtype=np.uint8)

        gain_scale = np.clip(self.gain, 0.1, 5.0)

        frame[..., 0] = np.clip(xv + c * gain_scale, 0, 255)
        frame[..., 1] = np.clip(yv + c * gain_scale * 1.5, 0, 255)
        frame[..., 2] = np.clip(128 * gain_scale, 0, 255)

        return frame

    def _apply_watch_window(self, frame: np.ndarray) -> np.ndarray:
        x0 = self.watch_x
        y0 = self.watch_y
        x1 = min(x0 + self.watch_w, frame.shape[1])
        y1 = min(y0 + self.watch_h, frame.shape[0])
        return frame[y0:y1, x0:x1]

    def _reset_watch_window(self) -> None:
        self.watch_x = 0
        self.watch_y = 0
        self.watch_w = self.width
        self.watch_h = self.height
