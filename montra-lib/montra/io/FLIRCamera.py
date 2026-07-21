"""FLIR camera backend using the Spinnaker SDK (PySpin).

PySpin is not on PyPI — download the Spinnaker SDK from FLIR's website and
install the matching Python wheel for your platform.

Usage:
    from montra.io.FLIRCamera import FLIRCamera
    if not FLIRCamera.is_available():
        raise RuntimeError("PySpin not installed")
    cam = FLIRCamera()        # selects the first FLIR camera found
    cam.open()
    ok, frame, ts = cam.read()
    cam.close()
"""

from __future__ import annotations

import numpy as np
from typing import Optional, Tuple

from .Camera import Camera, CameraError, Parameter


class FLIRCamera(Camera):
    """FLIR / Point Grey camera via Spinnaker SDK (PySpin).

    Continuous-acquisition model: the SDK streams frames into an internal ring
    buffer.  GetNextImage blocks until the oldest pending buffer is available,
    so preview reads can drift behind reality if the software is slower than the
    camera.  drain_stale() discards accumulated buffers before a preview read.

    is_blocking = True: GetNextImage(1000) holds the camera thread for up to one
    hardware frame interval.  CameraWorker restarts its timer at _BLOCKING_POLL_MS
    after each read instead of letting it run freely.

    Pixel format: frames are converted to BGR8 (3-channel) to match the other
    backends.  On mono-only sensors that do not support BGR8 the fallback converts
    Mono8 to a 3-channel BGR array by replicating the single channel.

    All PySpin imports are deferred so that the rest of the application works on
    machines where the Spinnaker SDK is not installed.
    """

    is_blocking: bool = True

    @staticmethod
    def is_available() -> bool:
        """Return True if PySpin is installed and importable."""
        try:
            import PySpin  # noqa: F401
            return True
        except ImportError:
            return False

    def __init__(self, camera_index: int = 0) -> None:
        super().__init__()
        self._camera_index = camera_index
        self._system = None

    # ── Camera ABC implementation ─────────────────────────────────────────────

    def _open(self) -> None:
        import PySpin
        self._system = PySpin.System.GetInstance()
        cam_list = self._system.GetCameras()
        n = cam_list.GetSize()
        if n == 0:
            cam_list.Clear()
            raise CameraError("No FLIR cameras found. Check USB/GigE connection.")
        if self._camera_index >= n:
            cam_list.Clear()
            raise CameraError(
                f"Camera index {self._camera_index} out of range — "
                f"{n} camera(s) detected."
            )
        self.cam = cam_list[self._camera_index]
        cam_list.Clear()
        self.cam.Init()

        node_map = self.cam.GetNodeMap()

        # Continuous acquisition
        acq_mode = PySpin.CEnumerationPtr(node_map.GetNode("AcquisitionMode"))
        if PySpin.IsWritable(acq_mode):
            entry = acq_mode.GetEntryByName("Continuous")
            if PySpin.IsReadable(entry):
                acq_mode.SetIntValue(entry.GetValue())

        # Disable auto-exposure so set() controls exposure directly
        try:
            exp_auto = PySpin.CEnumerationPtr(node_map.GetNode("ExposureAuto"))
            if PySpin.IsWritable(exp_auto):
                off_entry = exp_auto.GetEntryByName("Off")
                if PySpin.IsReadable(off_entry):
                    exp_auto.SetIntValue(off_entry.GetValue())
        except Exception:
            pass

        self.cam.BeginAcquisition()

    def _close(self) -> None:
        try:
            self.cam.EndAcquisition()
        except Exception:
            pass
        try:
            self.cam.DeInit()
        except Exception:
            pass
        try:
            del self.cam
        except Exception:
            pass
        if self._system is not None:
            try:
                self._system.ReleaseInstance()
            except Exception:
                pass
            self._system = None

    def _set(self, parameter: Parameter, value) -> bool:
        import PySpin
        _NODE_MAP: dict = {
            Parameter.FRAME_RATE: ("AcquisitionFrameRate", "float"),
            Parameter.EXPOSURE:   ("ExposureTime",          "float"),
            Parameter.GAIN:       ("Gain",                  "float"),
            Parameter.WIDTH:      ("Width",                 "int"),
            Parameter.HEIGHT:     ("Height",                "int"),
            Parameter.X_OFFSET:   ("OffsetX",               "int"),
            Parameter.Y_OFFSET:   ("OffsetY",               "int"),
        }
        if parameter not in _NODE_MAP:
            return False
        node_name, kind = _NODE_MAP[parameter]
        node_map = self.cam.GetNodeMap()
        node = node_map.GetNode(node_name)
        if not PySpin.IsWritable(node):
            return False
        if kind == "float":
            PySpin.CFloatPtr(node).SetValue(float(value))
        else:
            PySpin.CIntegerPtr(node).SetValue(int(value))
        return True

    def _watch(self, x_off: int, width: int, y_off: int, height: int) -> bool:
        # OffsetX/Y must be zeroed before Width/Height on some cameras, so set
        # offsets first then dimensions.
        ok = True
        ok &= self._set(Parameter.X_OFFSET, x_off)
        ok &= self._set(Parameter.Y_OFFSET, y_off)
        ok &= self._set(Parameter.WIDTH, width)
        ok &= self._set(Parameter.HEIGHT, height)
        return ok

    def _reset_watch_window(self) -> None:
        import PySpin
        nm = self.cam.GetNodeMap()
        # Zero offsets first, then maximise dimensions.
        for node_name in ("OffsetX", "OffsetY"):
            node = nm.GetNode(node_name)
            if PySpin.IsWritable(node):
                PySpin.CIntegerPtr(node).SetValue(0)
        for node_name in ("Width", "Height"):
            node = nm.GetNode(node_name)
            if PySpin.IsWritable(node):
                ptr = PySpin.CIntegerPtr(node)
                ptr.SetValue(ptr.GetMax())

    def drain_stale(self) -> None:
        """Discard accumulated SDK ring-buffer frames without processing them.

        Call this before a preview read (not during recording) to ensure the next
        GetNextImage returns a freshly captured frame rather than an old one.
        """
        import PySpin
        while True:
            try:
                img = self.cam.GetNextImage(0)   # 0 ms = non-blocking poll
                img.Release()
            except PySpin.SpinnakerException:
                break

    def _read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        import PySpin
        try:
            image_result = self.cam.GetNextImage(1000)
        except PySpin.SpinnakerException:
            return False, None

        if image_result.IsIncomplete():
            image_result.Release()
            return False, None

        # Convert to BGR8 for consistency with all other backends.
        # Fall back to Mono8→replicated-BGR on sensors that don't support BGR8.
        try:
            converted = image_result.Convert(PySpin.PixelFormat_BGR8, PySpin.HQ_LINEAR)
            frame: np.ndarray = converted.GetNDArray().copy()
        except PySpin.SpinnakerException:
            converted = image_result.Convert(PySpin.PixelFormat_Mono8, PySpin.HQ_LINEAR)
            mono: np.ndarray = converted.GetNDArray().copy()
            frame = np.stack([mono, mono, mono], axis=-1)

        image_result.Release()
        return True, frame
