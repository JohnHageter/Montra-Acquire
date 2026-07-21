"""Camera I/O worker.

Owns the camera object and runs in a dedicated QThread.  All camera lifecycle
calls (open, close, set_parameter, watch window) and the frame-read loop are
driven by Qt signals from the main/acquisition thread.

Frame-read loop strategy:
  Blocking cameras (IDS, FLIR) — camera.read() holds the thread for up to one
  hardware frame interval.  The timer is stopped before the read and restarted at
  _BLOCKING_POLL_MS after it returns, so cycle time ≈ hardware_frame_interval + 5 ms.

  Non-blocking cameras (OpenCV, Test) — camera.read() returns in <1 ms.  The timer
  runs continuously so the effective polling rate equals exactly 1000/software_fps ms.
  The _reading flag prevents re-entrant calls on the rare tick that overlaps.

Software FPS:
  set_parameter("fps") is intercepted here and never forwarded to the hardware.  The
  camera always free-runs; the timer interval controls how often the software samples
  the most recent frame.  Intentional under-sampling (e.g. requesting 10 fps from a
  30 fps camera) does not count as dropped frames.

Signals emitted:
  frame_ready(np.ndarray)     — new BGR frame for preview / tracking
  camera_opened()             — camera opened successfully
  camera_closed()             — camera closed
  live_started()              — streaming started
  live_stopped()              — streaming stopped
  recording_started(str)      — path chosen for the output video
  recording_finished(int)     — frame count written
  recording_error(str)        — VideoWriter could not be opened
  snap_saved(str)             — path of the snapshot PNG
  bg_captured(str)            — path of the background PNG
  camera_stats_updated(float, int, int) — (actual_fps, dropped_frames, disconnects)
"""

import datetime
import os
import time
import zlib
from collections import deque
from typing import Deque, Optional

import cv2
import numpy as np
from PySide6.QtCore import QObject, QRect, Qt, Signal, Slot, QTimer

from montra.io.Camera import Camera, Parameter
from montra.io.FLIRCamera import FLIRCamera
from montra.io.IDSCamera import IDSCamera
from montra.io.OpenCVCamera import OpenCVCamera
from montra.io.TestCamera import TestCamera
from montra_acquire.ui.utils.logger import logger


# For cameras whose read() blocks (e.g. IDS WaitForFinishedBuffer), the timer
# only needs to fire faster than one frame interval — the blocking call itself
# throttles to hardware fps.  5 ms gives ~200 Hz polling so the cycle time is
# (hardware_frame_interval + 5 ms) ≈ hardware fps, rather than 2× the interval
# that results from using 1000/fps ms.
_BLOCKING_POLL_MS = 5

_NAME_TO_PARAM = {
    "exposure":   Parameter.EXPOSURE,
    "gain":       Parameter.GAIN,
    "fps":        Parameter.FRAME_RATE,
    "frame_rate": Parameter.FRAME_RATE,
    "width":      Parameter.WIDTH,
    "height":     Parameter.HEIGHT,
    "x_offset":   Parameter.X_OFFSET,
    "y_offset":   Parameter.Y_OFFSET,
}


class CameraWorker(QObject):
    frame_ready                  = Signal(object)
    camera_opened                = Signal()
    camera_closed                = Signal()
    live_started                 = Signal()
    live_stopped                 = Signal()
    camera_watch_window_reset    = Signal()
    camera_watch_window_updated  = Signal(QRect)
    recording_started            = Signal(str)   # output path
    recording_finished           = Signal(int)   # frame count written
    recording_error              = Signal(str)
    snap_saved                   = Signal(str)   # path to saved PNG
    bg_captured                  = Signal(str)   # path to saved background PNG
    # (actual_fps, cumulative_read_failures, cumulative_disconnects)
    camera_stats_updated         = Signal(float, int, int)
    # (over_pct, under_pct) — fraction of pixels at or above 250 / at or below 5
    saturation_stats             = Signal(float, float)
    cameras_enumerated           = Signal(list)  # List[str]: "index: description"
    video_timestamps_ready       = Signal(list)  # List[list] rows for H5 export

    def __init__(self):
        super().__init__()
        self.camera: Optional[Camera] = None
        self.streaming: bool = False
        self.software_fps: float = 30.0
        self._camera_is_blocking: bool = False   # True for IDS/FLIR (WaitForFinishedBuffer)
        self.timer: Optional[QTimer] = None
        self.last_frame: Optional[np.ndarray] = None

        self._writer: Optional[cv2.VideoWriter] = None
        self._record_frame_count: int = 0
        self._recording_owns_stream: bool = False  # True when RECORD started the stream
        self.last_recording_path: Optional[str] = None  # actual path chosen by start_recording
        self.last_writer_fps: float = 0.0            # fps VideoWriter was actually opened with
        self.last_record_frame_count: int = 0        # frames written in the most recent recording
        self._writer_size: Optional[tuple] = None  # (h, w) VideoWriter was opened with

        self._video_timestamp_rows: list                       = []
        self._record_start_mono:  float                      = 0.0
        self._record_start_utc:   Optional[datetime.datetime] = None
        self._record_next_write_time: float                  = 0.0   # target-advance gate

        # ── Per-stream stats (reset on start_stream) ──────────────────────────
        self._last_frame_sig:       Optional[int]  = None   # CRC32 of middle row
        self._frame_timestamps:     Deque[float]   = deque(maxlen=60)
        self._dropped_frames:       int            = 0      # cumulative deficit frames
        self._disconnect_count:     int            = 0      # failure-streak transitions
        self._was_getting_frames:   bool           = True   # for disconnect detection
        self._last_stats_time:      float          = 0.0
        self._frames_in_window:     int            = 0      # unique frames since last stats emit
        self._reading:              bool           = False  # re-entrancy guard for _read_frame

    # ── Public read-only properties ───────────────────────────────────────────

    @property
    def frame_size(self) -> Optional[tuple]:
        """Return (width, height) of the most recent frame, or None if unknown."""
        if self.last_frame is not None:
            h, w = self.last_frame.shape[:2]
            return (w, h)
        if self._writer_size is not None:
            h, w = self._writer_size
            return (w, h)
        return None

    # ── Initialisation (must run inside the camera thread) ───────────────────

    @Slot()
    def init_timer(self):
        self.timer = QTimer()
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._read_frame)

    # ── Camera lifecycle ──────────────────────────────────────────────────────

    @Slot(str)
    def open_camera(self, camera_type: str):
        try:
            if camera_type == "OpenCV":
                self.camera = OpenCVCamera()
            elif camera_type == "IDS":
                self.camera = IDSCamera()
            elif camera_type == "FLIR":
                if not FLIRCamera.is_available():
                    logger.log_signal.emit(
                        "FLIR camera unavailable: Spinnaker SDK (PySpin) not installed", "ERROR"
                    )
                    return
                self.camera = FLIRCamera()
            elif camera_type == "Test":
                self.camera = TestCamera()
            else:
                logger.log_signal.emit(f"Unknown camera type: {camera_type}", "ERROR")
                return

            self.camera.open()
            self._camera_is_blocking = self.camera.is_blocking
            self.camera_opened.emit()
            logger.log_signal.emit(f"{camera_type} camera opened", "INFO")
        except Exception as e:
            logger.log_signal.emit(f"Failed to open camera: {e}", "ERROR")
            self.camera = None
            self._camera_is_blocking = False

    @Slot()
    def close_camera(self):
        self.stop_stream()
        if self.camera:
            self.camera.close()
            self.camera = None
            self._camera_is_blocking = False
            self.camera_closed.emit()
            logger.log_signal.emit("Camera closed", "INFO")

    @Slot()
    def snap_image(self):
        if self.camera:
            ret, frame, _ = self.camera.read()
            if ret and frame is not None:
                self.last_frame = frame
                self.frame_ready.emit(frame.copy())
                logger.log_signal.emit("Snap taken", "INFO")
            else:
                logger.log_signal.emit("Snap failed: no frame", "WARNING")
        else:
            logger.log_signal.emit("Snap failed: camera not open", "ERROR")

    @Slot(float)
    def start_stream(self, fps: float):
        if not self.camera:
            logger.log_signal.emit("Cannot start stream: camera not open", "ERROR")
            return
        self.software_fps = fps
        self.streaming = True

        # Reset per-stream stats
        self._last_frame_sig    = None
        self._frame_timestamps.clear()
        self._dropped_frames    = 0
        self._disconnect_count  = 0
        self._was_getting_frames = True
        self._last_stats_time   = 0.0
        self._frames_in_window  = 0

        if self.timer:
            interval = _BLOCKING_POLL_MS if self._camera_is_blocking else int(1000 / fps)
            self.timer.start(interval)
        self.live_started.emit()
        logger.log_signal.emit(f"Live stream started at {fps} FPS", "INFO")

    @Slot()
    def stop_stream(self):
        self.streaming = False
        if self.timer:
            self.timer.stop()
        self.live_stopped.emit()
        logger.log_signal.emit("Live stream stopped", "INFO")

    # ── Parameter / watch window ──────────────────────────────────────────────

    @Slot(str, object)
    def set_parameter(self, name: str, value):
        if not self.camera:
            return
        param = _NAME_TO_PARAM.get(name.lower())
        if param is None:
            logger.log_signal.emit(f"Unknown camera parameter: {name}", "WARNING")
            return

        if param == Parameter.FRAME_RATE:
            fps = float(value)
            self.software_fps = fps
            if self.timer and not self._camera_is_blocking:
                self.timer.setInterval(int(1000 / fps))
            # For blocking cameras (IDS/FLIR) the hardware frame rate gates how
            # fast frames arrive, so forward the requested fps to the hardware
            # so the camera delivers frames at (approximately) software_fps.
            if self._camera_is_blocking and self.camera:
                try:
                    ok = self.camera.set(Parameter.FRAME_RATE, fps)
                    if not ok:
                        logger.log_signal.emit(
                            "Hardware fps not supported by this camera", "WARN"
                        )
                except Exception as exc:
                    logger.log_signal.emit(f"Failed to set hardware fps: {exc}", "WARN")
            logger.log_signal.emit(f"Software FPS set to {fps:.1f}", "INFO")
            return

        try:
            ok = self.camera.set(param, value)
            if ok:
                logger.log_signal.emit(f"{name} set to {value}", "INFO")
            else:
                logger.log_signal.emit(f"{name} not supported by this camera", "WARNING")
        except Exception as e:
            logger.log_signal.emit(f"Failed to set {name}: {e}", "ERROR")

    @Slot(QRect)
    def set_watch_window(self, rect: QRect):
        if not self.camera:
            return
        self._last_frame_sig = None   # force next frame to be treated as new
        self.last_frame = None        # force start_recording() to read fresh post-watch dims
        if rect.isNull():
            self.camera.watch(None, None, None, None)
            self.camera_watch_window_reset.emit()
            self.camera_watch_window_updated.emit(QRect())
        else:
            ok = self.camera.watch(rect.x(), rect.width(), rect.y(), rect.height())
            if ok:
                self.camera_watch_window_updated.emit(rect)

    @Slot()
    def reset_watch_window(self):
        if not self.camera:
            return
        self._last_frame_sig = None
        self.camera.watch(None, None, None, None)
        logger.log_signal.emit("Watch window reset", "INFO")
        self.camera_watch_window_updated.emit(QRect())
        self.camera_watch_window_reset.emit()

    # ── Script-accessible camera management ───────────────────────────────────

    @Slot(str, int)
    def open_camera_indexed(self, camera_type: str, index: int):
        """Open a camera by type and device index. Stops any existing stream/camera first."""
        self.stop_stream()
        if self.camera:
            self.camera.close()
            self.camera = None
        try:
            if camera_type == "OpenCV":
                try:
                    self.camera = OpenCVCamera(index)
                except TypeError:
                    self.camera = OpenCVCamera()
            elif camera_type == "IDS":
                try:
                    self.camera = IDSCamera(index)
                except TypeError:
                    self.camera = IDSCamera()
            elif camera_type == "FLIR":
                if not FLIRCamera.is_available():
                    logger.log_signal.emit(
                        "FLIR camera unavailable: Spinnaker SDK (PySpin) not installed", "ERROR"
                    )
                    return
                self.camera = FLIRCamera(index)
            elif camera_type == "Test":
                self.camera = TestCamera()
            else:
                logger.log_signal.emit(f"Unknown camera type: {camera_type}", "ERROR")
                return
            self.camera.open()
            self._camera_is_blocking = self.camera.is_blocking
            self.camera_opened.emit()
            logger.log_signal.emit(f"{camera_type}[{index}] camera opened", "INFO")
        except Exception as e:
            logger.log_signal.emit(f"Failed to open camera: {e}", "ERROR")
            self.camera = None
            self._camera_is_blocking = False

    def grab_frame(self) -> Optional[np.ndarray]:
        """Read and return one frame without affecting the live stream.

        Returns the most-recent frame if the stream is already running (avoids
        a duplicate camera.read() call), otherwise reads directly from the camera.
        Always returns a copy so the caller owns the array.
        """
        if self.streaming and self.last_frame is not None:
            return self.last_frame.copy()
        if self.camera:
            try:
                ret, frame, _ = self.camera.read()
                if ret and frame is not None:
                    self.last_frame = frame
                    return frame.copy()
            except Exception as exc:
                logger.log_signal.emit(f"grab_frame error: {exc}", "ERROR")
        return None

    @Slot(str, object)
    def snap_to_file(self, path: str, done_event=None):
        """Save the current frame (or read one) as a PNG at *path*."""
        frame = None
        if self.last_frame is not None:
            frame = self.last_frame.copy()
        elif self.camera:
            try:
                ret, f, _ = self.camera.read()
                if ret and f is not None:
                    frame = f
            except Exception:
                pass

        if frame is None:
            logger.log_signal.emit("Snapshot: no frame available", "ERROR")
            if done_event is not None:
                done_event.set()
            return

        try:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            cv2.imwrite(path, frame)
            logger.log_signal.emit(f"Snapshot → {path}", "INFO")
            self.snap_saved.emit(path)
        except Exception as exc:
            logger.log_signal.emit(f"Snapshot save error: {exc}", "ERROR")

        if done_event is not None:
            done_event.set()

    @Slot(int, int, str, object)
    def capture_background(self, frames: int, blur_k: int, path: str, done_event=None):
        """Capture *frames* frames, compute their mean, optionally blur, and save as PNG."""
        if not self.camera:
            logger.log_signal.emit("BG capture: no camera open", "ERROR")
            if done_event is not None:
                done_event.set()
            return

        collected = []
        for _ in range(frames):
            try:
                ret, frame, _ = self.camera.read()
                if ret and frame is not None:
                    collected.append(frame.astype(np.float32))
            except Exception:
                pass

        if not collected:
            logger.log_signal.emit("BG capture: no frames collected", "ERROR")
            if done_event is not None:
                done_event.set()
            return

        bg = np.mean(collected, axis=0).astype(np.uint8)
        if blur_k > 1:
            ksize = blur_k if blur_k % 2 == 1 else blur_k + 1
            bg = cv2.GaussianBlur(bg, (ksize, ksize), 0)

        try:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            cv2.imwrite(path, bg)
            logger.log_signal.emit(
                f"Background captured ({len(collected)} frames, blur={blur_k}) → {path}", "INFO"
            )
            self.bg_captured.emit(path)
        except Exception as exc:
            logger.log_signal.emit(f"BG capture save error: {exc}", "ERROR")

        if done_event is not None:
            done_event.set()

    # ── Recording ─────────────────────────────────────────────────────────────

    @Slot(str, float)
    def start_recording(self, output_path: str, fps: float):
        if self._writer is not None:
            self._writer.release()

        # If the camera isn't streaming yet, start it now so _read_frame fires.
        self._recording_owns_stream = False
        if not self.streaming:
            self._recording_owns_stream = True
            self.start_stream(fps)

        if self.last_frame is None and self.camera:
            # Stream just started; read one frame directly to learn the frame dimensions.
            try:
                ret, frame, _ = self.camera.read()
                if ret and frame is not None:
                    self.last_frame = frame
            except Exception:
                pass

        if self.last_frame is None:
            logger.log_signal.emit("Cannot start recording: no frame size known yet", "ERROR")
            self.recording_error.emit("No frame available to determine size")
            if self._recording_owns_stream:
                self.stop_stream()
                self._recording_owns_stream = False
            return

        h, w = self.last_frame.shape[:2]

        # For blocking cameras (IDS, FLIR) the timer runs at _BLOCKING_POLL_MS
        # regardless of software_fps, so _compute_actual_fps() returns hardware fps.
        # We gate writes in _read_frame at software_fps, so VideoWriter must use fps.
        # For non-blocking cameras the timer already throttles to software_fps, so
        # measured fps ≈ software_fps; use measured to handle cameras that can't
        # reach the requested rate (e.g. requested 500 fps, hardware delivers 46).
        self._record_next_write_time = 0.0
        self._video_timestamp_rows   = []
        if self._camera_is_blocking:
            writer_fps = fps
        else:
            measured = self._compute_actual_fps()
            writer_fps = measured if measured >= 1.0 else fps
            if abs(writer_fps - fps) > 1.0:
                logger.log_signal.emit(
                    f"VideoWriter fps capped to measured {writer_fps:.1f} fps "
                    f"(requested {fps:.1f})", "INFO"
                )

        # Try MP4 codecs first (user preference), fall back to AVI if unavailable.
        base, _ = os.path.splitext(output_path)
        writer = None
        chosen_path = output_path
        for fourcc_str, ext in (("mp4v", ".mp4"), ("avc1", ".mp4"), ("XVID", ".avi"), ("MJPG", ".avi")):
            candidate_path = base + ext
            fourcc = cv2.VideoWriter_fourcc(*fourcc_str)
            w_try = cv2.VideoWriter(candidate_path, fourcc, writer_fps, (w, h))
            if w_try.isOpened():
                chosen_path = candidate_path
                writer = w_try
                logger.log_signal.emit(f"VideoWriter codec={fourcc_str} fps={writer_fps:.1f} path={candidate_path}", "INFO")
                break
            w_try.release()

        if writer is None:
            msg = f"Failed to open VideoWriter for {output_path} (tried mp4v, avc1, XVID, MJPG)"
            logger.log_signal.emit(msg, "ERROR")
            self.recording_error.emit(msg)
            if self._recording_owns_stream:
                self.stop_stream()
                self._recording_owns_stream = False
            return

        self._writer = writer
        self._writer_size = (h, w)
        self._record_frame_count = 0
        self._last_frame_sig = None  # force next frame through dedup so recording starts immediately
        self.last_recording_path = chosen_path
        self.last_writer_fps = writer_fps
        self._record_start_mono = time.monotonic()
        self._record_start_utc  = datetime.datetime.now(datetime.timezone.utc)

        logger.log_signal.emit(f"Recording started → {chosen_path}", "INFO")
        self.recording_started.emit(chosen_path)

    @Slot()
    def stop_recording(self):
        if self._writer is not None:
            self._writer.release()
            self._writer = None
        self._writer_size = None
        rows = self._video_timestamp_rows
        self._video_timestamp_rows = []
        count = self._record_frame_count
        self.last_record_frame_count = count
        self._record_frame_count = 0
        logger.log_signal.emit(f"Recording stopped ({count} frames)", "INFO")
        self.video_timestamps_ready.emit(rows)
        self.recording_finished.emit(count)
        if self._recording_owns_stream:
            self._recording_owns_stream = False
            self.stop_stream()

    # ── Internal frame loop ───────────────────────────────────────────────────

    def _read_frame(self):
        if self._reading or not self.camera or not self.streaming:
            return
        self._reading = True

        # Blocking cameras (IDS, FLIR): stop the timer so that timer events don't
        # accumulate in the Qt event queue while camera.read() holds the thread for
        # a full frame interval (e.g. 22 ms at 46 fps).  The timer is restarted at
        # every exit point with _BLOCKING_POLL_MS so the next read fires quickly.
        #
        # Non-blocking cameras (OpenCV, Test): camera.read() returns in <1 ms, so
        # the timer is left running.  Stopping and restarting it here would add the
        # execution overhead to every cycle, making effective fps lower than requested
        # (e.g. 9 fps instead of 10 fps at poll_ms=100).  The _reading guard below
        # is sufficient to prevent re-entry on the rare tick that overlaps.
        if self._camera_is_blocking and self.timer:
            self.timer.stop()

        now = time.monotonic()

        # For cameras that buffer hardware frames internally (e.g. IDS Peak SDK),
        # discard accumulated stale buffers when previewing so the next read returns
        # a fresh frame.  Skip this during recording — every frame must be captured.
        if self._writer is None and hasattr(self.camera, 'drain_stale'):
            self.camera.drain_stale()

        try:
            ret, frame, _ = self.camera.read()
        except Exception as e:
            logger.log_signal.emit(f"Camera read error: {e}", "ERROR")
            self._reading = False
            if self._camera_is_blocking and self.streaming and self.timer:
                self.timer.start(_BLOCKING_POLL_MS)
            return

        if not ret or frame is None:
            if self._was_getting_frames:
                self._disconnect_count += 1
                self._was_getting_frames = False
            self._maybe_emit_stats(now)
            self._reading = False
            if self._camera_is_blocking and self.streaming and self.timer:
                self.timer.start(_BLOCKING_POLL_MS)
            return

        # ── Deduplicate ───────────────────────────────────────────────────────
        # Blocking cameras (IDS) only return when a genuinely new frame is in the
        # SDK buffer — dedup via CRC is unnecessary and wastes CPU on large frames.
        if not self._camera_is_blocking:
            sig = self._frame_sig(frame)
            if sig == self._last_frame_sig:
                self._maybe_emit_stats(now)
                self._reading = False
                return  # timer is still running — no restart needed
            self._last_frame_sig = sig

        # ── New unique frame ──────────────────────────────────────────────────
        self._was_getting_frames = True
        self._frames_in_window += 1
        self._frame_timestamps.append(now)
        self.last_frame = frame

        if self._writer is not None:
            # For blocking cameras (IDS/FLIR) the timer runs at _BLOCKING_POLL_MS
            # regardless of software_fps, so we gate writes here to hit software_fps.
            # Target-advance: advance the next-write target by min_interval after each
            # write (never reset to 'now') so the average write rate converges to
            # software_fps even when hardware frame intervals are coarser than
            # min_interval (e.g. 76 ms hardware vs 100 ms target → ~9.9 fps actual).
            write_now = True
            if self._camera_is_blocking:
                min_interval = 1.0 / max(self.software_fps, 1.0)
                if self._record_next_write_time == 0.0:
                    self._record_next_write_time = now + min_interval
                else:
                    write_now = now >= self._record_next_write_time
                if write_now:
                    self._record_next_write_time += min_interval
            if write_now:
                try:
                    write_frame = frame
                    if self._writer_size is not None:
                        wh, ww = self._writer_size
                        if frame.shape[:2] != (wh, ww):
                            write_frame = cv2.resize(frame, (ww, wh))
                    self._writer.write(write_frame)
                    self._record_frame_count += 1
                    elapsed_s = now - self._record_start_mono
                    utc_ts = self._record_start_utc + datetime.timedelta(seconds=elapsed_s)
                    self._video_timestamp_rows.append([
                        self._record_frame_count - 1,
                        elapsed_s * 1000.0,
                        utc_ts.isoformat(timespec="microseconds"),
                        now,
                    ])
                except Exception as exc:
                    logger.log_signal.emit(f"VideoWriter.write error: {exc}", "ERROR")
                    self._writer.release()
                    self._writer = None
                    self._writer_size = None

        # Saturation stats — cheap; two vectorised comparisons on the gray plane
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        over_pct  = float(np.mean(gray >= 250) * 100.0)
        under_pct = float(np.mean(gray <= 5)   * 100.0)
        self.saturation_stats.emit(over_pct, under_pct)

        # Blocking cameras return owned numpy arrays (np.ascontiguousarray inside
        # _convert_buffer) — a second .copy() is redundant and doubles allocation.
        # Non-blocking cameras may return a view into the SDK buffer, so copy there.
        emit_frame = frame if self._camera_is_blocking else frame.copy()
        self.frame_ready.emit(emit_frame)
        self._maybe_emit_stats(now)
        self._reading = False
        if self._camera_is_blocking and self.streaming and self.timer:
            self.timer.start(_BLOCKING_POLL_MS)

    @Slot(str)
    def enumerate_cameras(self, camera_type: str) -> None:
        """Scan for available cameras of *camera_type* and emit cameras_enumerated."""
        results: list = []
        try:
            if camera_type in ("ALL", "Test"):
                prefix = "Test:" if camera_type == "ALL" else ""
                results.append(f"{prefix}0: Test Camera")

            if camera_type in ("ALL", "OpenCV"):
                prefix = "OpenCV:" if camera_type == "ALL" else ""
                for i in range(10):
                    cap = cv2.VideoCapture(i)
                    if cap.isOpened():
                        results.append(f"{prefix}{i}: OpenCV Camera {i}")
                        cap.release()

            if camera_type in ("ALL", "IDS"):
                prefix = "IDS:" if camera_type == "ALL" else ""
                try:
                    from ids_peak import ids_peak as _ip
                    _ip.Library.Initialize()
                    dm = _ip.DeviceManager.Instance()
                    dm.Update()
                    for i, d in enumerate(dm.Devices()):
                        results.append(f"{prefix}{i}: {d.ModelName()} SN:{d.SerialNumber()}")
                except Exception:
                    pass  # IDS SDK not installed or no cameras

            if camera_type in ("ALL", "FLIR"):
                prefix = "FLIR:" if camera_type == "ALL" else ""
                try:
                    import PySpin as _ps
                    system   = _ps.System.GetInstance()
                    cam_list = system.GetCameras()
                    n = cam_list.GetSize()
                    for i in range(n):
                        results.append(f"{prefix}{i}: FLIR Camera {i}")
                    cam_list.Clear()
                    system.ReleaseInstance()
                except Exception:
                    pass  # FLIR SDK not installed or no cameras

            if not results:
                results = ["No cameras found"]

        except Exception as exc:
            results = [f"Enumerate error: {exc}"]

        self.cameras_enumerated.emit(results)

    @staticmethod
    def _frame_sig(frame: np.ndarray) -> int:
        """CRC32 of the middle row — fast proxy for frame identity."""
        mid = frame.shape[0] // 2
        return zlib.crc32(frame[mid].tobytes()) & 0xFFFFFFFF

    def _compute_actual_fps(self) -> float:
        if len(self._frame_timestamps) < 2:
            return 0.0
        elapsed = self._frame_timestamps[-1] - self._frame_timestamps[0]
        return (len(self._frame_timestamps) - 1) / elapsed if elapsed > 0 else 0.0

    def _maybe_emit_stats(self, now: float) -> None:
        if now - self._last_stats_time < 1.0:
            return
        elapsed = now - self._last_stats_time if self._last_stats_time > 0.0 else 1.0
        # Deficit: frames software expected to deliver vs frames actually received.
        expected = int(round(self.software_fps * elapsed))
        deficit = max(0, expected - self._frames_in_window)
        self._dropped_frames += deficit
        self._frames_in_window = 0
        # Emit software_fps (target rate) — not the measured hardware rate — so the
        # HUD shows the rate the recording/preview is running at, not the hardware fps.
        self.camera_stats_updated.emit(
            self.software_fps, self._dropped_frames, self._disconnect_count
        )
        self._last_stats_time = now
