from typing import Dict, Optional, Tuple, Type, Union, overload
from typing_extensions import Literal

import cv2
import numpy as np

from ids_peak import ids_peak as peak
from ids_peak.exceptions import TimeoutException as _IDSTimeout
from ids_peak_ipl import ids_peak_ipl as peak_ipl

from montra.io.Camera import (
    Camera,
    CameraError,
    InvalidStateError,
    Parameter,
)


CameraValue = Union[int, float]

_NODE_REGISTRY: Dict[str, Type[peak.Node]] = {
    "AcquisitionFrameRate": peak.FloatNode,
    "AcquisitionMode":      peak.EnumerationNode,
    "AcquisitionStart":     peak.CommandNode,
    "AcquisitionStop":      peak.CommandNode,
    "ExposureAuto":         peak.EnumerationNode,
    "ExposureMode":         peak.EnumerationNode,
    "ExposureTime":         peak.FloatNode,
    "Gain":                 peak.FloatNode,
    "GainAuto":             peak.EnumerationNode,
    "GainSelector":         peak.EnumerationNode,
    "OffsetX":              peak.IntegerNode,
    "OffsetY":              peak.IntegerNode,
    "PixelFormat":          peak.EnumerationNode,
    "Width":                peak.IntegerNode,
    "Height":               peak.IntegerNode,
    "TLParamsLocked":       peak.IntegerNode,
    "UserSetSelector":      peak.EnumerationNode,
    "UserSetLoad":          peak.CommandNode,
}

_NODETYPE_TO_CLASS: Dict[int, Type[peak.Node]] = {
    peak.NodeType_Integer:     peak.IntegerNode,
    peak.NodeType_Float:       peak.FloatNode,
    peak.NodeType_Enumeration: peak.EnumerationNode,
    peak.NodeType_Command:     peak.CommandNode,
    peak.NodeType_Boolean:     peak.BooleanNode,
    peak.NodeType_String:      peak.StringNode,
}


class IDSCamera(Camera):
    """IDS Peak SDK camera backend (uEye+/Peak series).

    Continuous-acquisition model: the SDK streams frames into a fixed ring buffer.
    WaitForFinishedBuffer always returns the *oldest* finished buffer, so if the
    software reads slower than the camera captures, the preview drifts behind reality.

    drain_stale() discards accumulated buffers before a preview read so the next
    WaitForFinishedBuffer call returns a freshly captured frame.  drain_stale() is
    skipped during recording so every hardware frame is captured.

    is_blocking = True: WaitForFinishedBuffer holds the camera thread for up to one
    hardware frame interval.  CameraWorker restarts its timer at _BLOCKING_POLL_MS
    after each read instead of letting it run freely.
    """

    is_blocking: bool = True

    def __init__(self, index: int = 0) -> None:
        super().__init__()

        peak.Library.Initialize()

        self._index          = index
        self._device_manager = peak.DeviceManager.Instance()

        self._cam:            Optional[peak.Device]       = None
        self._remote_device:  Optional[peak.RemoteDevice] = None
        self._remote_map:     Optional[peak.NodeMap]      = None
        self._datastream:     Optional[peak.DataStream]   = None

        self._continuous:    bool                          = False
        self._latest_frame:  Optional[np.ndarray]          = None

        # Set up in _open() after reading PixelFormat from the camera
        self._is_color:            bool                               = False
        self._ipl_converter:       Optional[peak_ipl.ImageConverter]  = None
        self._output_pixel_format: Optional[peak_ipl.PixelFormat]     = None


    def _open(self) -> None:
        self._device_manager.Update()
        devices = self._device_manager.Devices()

        if devices.empty():
            raise CameraError("No IDS Peak camera detected")

        self._cam           = devices[self._index].OpenDevice(peak.DeviceAccessType_Control)
        self._remote_device = self._cam.RemoteDevice()
        self._remote_map    = self._remote_device.NodeMaps()[0]

        # Stop any leftover acquisition from a previous session
        try:
            acq_stop = self._remote_map.FindNode("AcquisitionStop")  # type: ignore[union-attr]
            if acq_stop.IsWriteable():  # type: ignore[attr-defined]
                acq_stop.Execute()          # type: ignore[attr-defined]
                acq_stop.WaitUntilDone()    # type: ignore[attr-defined]
        except Exception:
            pass

        # Load factory defaults so we start from a known state
        try:
            userset = self._find_node("UserSetSelector")
            if userset.IsWriteable():  # type: ignore[attr-defined]
                userset.SetCurrentEntry("Default")  # type: ignore[attr-defined]
                self._find_node("UserSetLoad").Execute()        # type: ignore[attr-defined]
                self._find_node("UserSetLoad").WaitUntilDone()  # type: ignore[attr-defined]
        except Exception:
            pass

        # Disable auto-exposure and auto-gain for manual control
        for name in ("ExposureAuto", "GainAuto"):
            try:
                node = self._find_node(name)
                if node.IsAvailable() and node.IsWriteable():  # type: ignore[attr-defined]
                    node.SetCurrentEntry("Off")                 # type: ignore[attr-defined]
            except Exception:
                pass

        # Record the full-sensor extent as the initial watch window
        width  = self._find_node("Width").Maximum()   # type: ignore[attr-defined]
        height = self._find_node("Height").Maximum()  # type: ignore[attr-defined]
        self.watch_window = (0, width, 0, height)

        self._continuous   = False
        self._latest_frame = None

        # Detect pixel format and build an IPL converter for _read_frame
        self._setup_converter()

    def _setup_converter(self) -> None:
        """Read PixelFormat from the camera and prepare an ImageConverter."""
        assert self._remote_map is not None
        try:
            pf_node = self._remote_map.FindNode("PixelFormat")
            pf_str  = pf_node.CurrentEntry().SymbolicValue()  # type: ignore[attr-defined]
        except Exception:
            pf_str = "Mono8"

        self._is_color = any(s in pf_str for s in ("Bayer", "RGB", "BGR", "YUV"))
        target_name    = (
            peak_ipl.PixelFormatName_BGR8
            if self._is_color
            else peak_ipl.PixelFormatName_Mono8
        )
        self._output_pixel_format = peak_ipl.PixelFormat(target_name)
        self._ipl_converter       = peak_ipl.ImageConverter()

    def _close(self) -> None:
        if self._continuous:
            self._do_stop_stream()

        self._cam = None   # drop device reference; let the SDK clean up
        peak.Library.Close()


    @overload
    def _find_node(
        self, key: Literal["ExposureTime", "Gain", "AcquisitionFrameRate"]
    ) -> peak.FloatNode: ...

    @overload
    def _find_node(
        self, key: Literal["OffsetX", "OffsetY", "Width", "Height", "TLParamsLocked"]
    ) -> peak.IntegerNode: ...

    @overload
    def _find_node(
        self,
        key: Literal[
            "ExposureAuto", "ExposureMode", "GainSelector", "GainAuto",
            "PixelFormat", "AcquisitionMode", "UserSetSelector",
        ],
    ) -> peak.EnumerationNode: ...

    @overload
    def _find_node(
        self, key: Literal["AcquisitionStart", "AcquisitionStop", "UserSetLoad"]
    ) -> peak.CommandNode: ...

    @overload
    def _find_node(self, key: str) -> peak.Node: ...

    def _find_node(self, key: str) -> peak.Node:
        if not self._remote_map:
            raise InvalidStateError("Camera not open")

        node = self._remote_map.FindNode(key)

        expected_cls = _NODE_REGISTRY.get(key)
        runtime_cls  = _NODETYPE_TO_CLASS.get(node.Type())  # type: ignore[attr-defined]

        if expected_cls and runtime_cls and runtime_cls is not expected_cls:
            raise CameraError(
                f"Node '{key}' expected {expected_cls.__name__}, "
                f"but device reports {runtime_cls.__name__}"
            )

        return node


    def _set(self, parameter: Parameter, value: CameraValue) -> bool:
        was_streaming = self._continuous

        try:
            if was_streaming:
                self._do_stop_stream()

            if parameter == Parameter.EXPOSURE:
                node = self._find_node("ExposureTime")
                lo, hi = node.Minimum(), node.Maximum()  # type: ignore[attr-defined]
                node.SetValue(max(lo, min(hi, float(value))))  # type: ignore[attr-defined]
                return True

            if parameter == Parameter.GAIN:
                node = self._find_node("Gain")
                lo, hi = node.Minimum(), node.Maximum()  # type: ignore[attr-defined]
                node.SetValue(max(lo, min(hi, float(value))))  # type: ignore[attr-defined]
                return True

            if parameter == Parameter.FRAME_RATE:
                # Some cameras require this boolean before AcquisitionFrameRate is writable
                assert self._remote_map is not None
                try:
                    en = self._remote_map.FindNode("AcquisitionFrameRateEnable")
                    if en.IsAvailable() and en.IsWriteable():  # type: ignore[attr-defined]
                        en.SetValue(True)                      # type: ignore[attr-defined]
                except Exception:
                    pass
                node = self._find_node("AcquisitionFrameRate")
                lo, hi = node.Minimum(), node.Maximum()  # type: ignore[attr-defined]
                node.SetValue(max(lo, min(hi, float(value))))  # type: ignore[attr-defined]
                return True

            # Route individual ROI dimensions through _watch so constraints are applied
            assert self._remote_map is not None

            if parameter == Parameter.WIDTH:
                return self._watch(
                    int(self._remote_map.FindNode("OffsetX").Value()),  # type: ignore[attr-defined]
                    int(value),
                    int(self._remote_map.FindNode("OffsetY").Value()),  # type: ignore[attr-defined]
                    int(self._remote_map.FindNode("Height").Value()),   # type: ignore[attr-defined]
                )

            if parameter == Parameter.HEIGHT:
                return self._watch(
                    int(self._remote_map.FindNode("OffsetX").Value()),  # type: ignore[attr-defined]
                    int(self._remote_map.FindNode("Width").Value()),    # type: ignore[attr-defined]
                    int(self._remote_map.FindNode("OffsetY").Value()),  # type: ignore[attr-defined]
                    int(value),
                )

            if parameter == Parameter.X_OFFSET:
                return self._watch(
                    int(value),
                    int(self._remote_map.FindNode("Width").Value()),   # type: ignore[attr-defined]
                    int(self._remote_map.FindNode("OffsetY").Value()), # type: ignore[attr-defined]
                    int(self._remote_map.FindNode("Height").Value()),  # type: ignore[attr-defined]
                )

            if parameter == Parameter.Y_OFFSET:
                return self._watch(
                    int(self._remote_map.FindNode("OffsetX").Value()), # type: ignore[attr-defined]
                    int(self._remote_map.FindNode("Width").Value()),   # type: ignore[attr-defined]
                    int(value),
                    int(self._remote_map.FindNode("Height").Value()),  # type: ignore[attr-defined]
                )

            return False

        except Exception:
            return False

        finally:
            if was_streaming:
                try:
                    self._do_start_stream()
                except Exception:
                    pass


    def _apply_roi_constraints(
        self, x: int, y: int, w: int, h: int
    ) -> Tuple[int, int, int, int]:
        offx   = self._find_node("OffsetX")
        offy   = self._find_node("OffsetY")
        width  = self._find_node("Width")
        height = self._find_node("Height")

        xi = offx.Increment()    # type: ignore[attr-defined]
        yi = offy.Increment()    # type: ignore[attr-defined]
        wi = width.Increment()   # type: ignore[attr-defined]
        hi = height.Increment()  # type: ignore[attr-defined]

        x = (x // xi) * xi
        y = (y // yi) * yi
        w = (w // wi) * wi
        h = (h // hi) * hi

        return x, y, w, h

    def _watch(self, x_off: int, width: int, y_off: int, height: int) -> bool:
        try:
            was_streaming = self._continuous
            if was_streaming:
                self._do_stop_stream()

            x, y, w, h = self._apply_roi_constraints(x_off, y_off, width, height)
            self._find_node("Width").SetValue(w)    # type: ignore[attr-defined]
            self._find_node("Height").SetValue(h)   # type: ignore[attr-defined]
            self._find_node("OffsetX").SetValue(x)  # type: ignore[attr-defined]
            self._find_node("OffsetY").SetValue(y)  # type: ignore[attr-defined]

            self.watch_window = (x, w, y, h)
            return True

        except Exception as exc:
            print(f"[IDSCamera] ROI set failed: {exc}")
            return False

        finally:
            if was_streaming:
                try:
                    self._do_start_stream()
                except Exception:
                    pass

    def _reset_watch_window(self) -> None:
        if not self._remote_map:
            return
        w = self._find_node("Width").Maximum()   # type: ignore[attr-defined]
        h = self._find_node("Height").Maximum()  # type: ignore[attr-defined]
        self._watch(0, w, 0, h)


    def _prepare_datastream(self) -> None:
        """Open a fresh datastream and fill its buffer pool."""
        assert self._cam is not None
        self._datastream = self._cam.DataStreams()[0].OpenDataStream()
        assert self._remote_map is not None
        payload     = self._remote_map.FindNode("PayloadSize").Value()  # type: ignore[attr-defined]
        min_buffers = self._datastream.NumBuffersAnnouncedMinRequired()  # type: ignore[attr-defined]

        for _ in range(min_buffers * 5):
            buf = self._datastream.AllocAndAnnounceBuffer(payload)  # type: ignore[attr-defined]
            self._datastream.QueueBuffer(buf)                       # type: ignore[attr-defined]

    def _do_start_stream(self) -> None:
        # Always (re-)allocate buffers — PayloadSize may have changed if ROI changed
        self._prepare_datastream()
        assert self._datastream is not None

        self._find_node("TLParamsLocked").SetValue(1)              # type: ignore[attr-defined]
        self._datastream.StartAcquisition()                         # type: ignore[attr-defined]
        self._find_node("AcquisitionStart").Execute()               # type: ignore[attr-defined]
        self._find_node("AcquisitionStart").WaitUntilDone()         # type: ignore[attr-defined]
        self._continuous = True

    def _do_stop_stream(self) -> None:
        if not self._continuous:
            return
        assert self._datastream is not None

        self._find_node("AcquisitionStop").Execute()               # type: ignore[attr-defined]
        self._find_node("AcquisitionStop").WaitUntilDone()         # type: ignore[attr-defined]
        self._datastream.KillWait()                                 # type: ignore[attr-defined]
        self._datastream.StopAcquisition(peak.AcquisitionStopMode_Default)  # type: ignore[attr-defined]
        self._datastream.Flush(peak.DataStreamFlushMode_DiscardAll)         # type: ignore[attr-defined]
        self._find_node("TLParamsLocked").SetValue(0)              # type: ignore[attr-defined]
        self._continuous = False
        self._datastream = None    # discard; _prepare_datastream rebuilds on next start


    def _convert_buffer(self, buffer) -> np.ndarray:  # type: ignore[type-arg]
        """Convert a finished acquisition buffer to a BGR uint8 frame."""
        assert self._ipl_converter is not None
        assert self._output_pixel_format is not None

        ipl_image = peak_ipl.Image.CreateFromSizeAndBuffer(
            buffer.PixelFormat(),   # type: ignore[attr-defined]
            buffer.BasePtr(),       # type: ignore[attr-defined]
            buffer.Size(),          # type: ignore[attr-defined]
            buffer.Width(),         # type: ignore[attr-defined]
            buffer.Height(),        # type: ignore[attr-defined]
        )
        converted = self._ipl_converter.Convert(ipl_image, self._output_pixel_format)  # type: ignore[attr-defined]

        if self._is_color:
            # ImageConverter produced BGR8 — get as (H, W, 3)
            return np.ascontiguousarray(converted.get_numpy_3D(), dtype=np.uint8)  # type: ignore[attr-defined]
        else:
            # Mono8 — get as (H, W) then promote to BGR
            return cv2.cvtColor(
                np.ascontiguousarray(converted.get_numpy_2D(), dtype=np.uint8),  # type: ignore[attr-defined]
                cv2.COLOR_GRAY2BGR,
            )

    def drain_stale(self) -> None:
        """Discard any accumulated SDK buffers without processing them.

        The IDS SDK acquires frames continuously into a fixed ring buffer.
        WaitForFinishedBuffer always returns the *oldest* pending buffer, so if
        software reads slower than the camera produces, the preview drifts behind
        reality.  Call this before a preview read (not during recording) to
        re-queue stale buffers and force the next read to wait for a fresh frame.
        """
        if not self._continuous or self._datastream is None:
            return
        while True:
            try:
                buf = self._datastream.WaitForFinishedBuffer(0)  # type: ignore[attr-defined]
                self._datastream.QueueBuffer(buf)                 # type: ignore[attr-defined]
            except _IDSTimeout:
                break
            except Exception:
                break

    def _read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        if not self._continuous:
            self._do_start_stream()
        assert self._datastream is not None

        try:
            buffer = self._datastream.WaitForFinishedBuffer(1000)  # type: ignore[attr-defined]
        except _IDSTimeout:
            return False, None
        except Exception:
            return False, None

        # Guarantee buffer is requeued even if conversion raises
        try:
            frame = self._convert_buffer(buffer)
            self._latest_frame = frame
            return True, frame
        finally:
            self._datastream.QueueBuffer(buffer)  # type: ignore[attr-defined]
