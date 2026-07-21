"""Full Acquisition tab widget.

Owns:
  • CameraWorker   — camera I/O in a background thread
  • AcquisitionWorker — script-engine execution in a background thread
  • DAQInterface   — lazily created when first needed

Key-press events received while a script is running are forwarded to
ScriptContext.key_event / .last_key so that WAITKEY commands unblock.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import QMetaObject, QPoint, QRect, QThread, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QFont, QKeyEvent, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from montra_acquire.daq import make_daq
from montra_acquire.script_engine import ScriptContext
from montra.app_paths import AppPaths
from montra_acquire.ui.script_help_dialog import ScriptHelpDialog
from montra_acquire.ui.utils.camera_preview_label import CameraPreviewLabel
from montra_acquire.ui.utils.common import cv_image_to_qpixmap
from montra_acquire.ui.workers.acquisition_worker import AcquisitionWorker
from montra_acquire.ui.workers.camera_worker import CameraWorker
from montra_acquire.ui.script_highlighter import ScriptHighlighter


# ── Thread-safe camera proxy ──────────────────────────────────────────────────

class _CameraProxy:
    """Routes ScriptEngine camera calls through Qt signals → camera thread."""

    def __init__(self, worker: CameraWorker, tab: "AcquisitionTab") -> None:
        self._worker = worker
        self._tab    = tab

    @property
    def software_fps(self) -> float:
        return self._worker.software_fps   # plain attribute read, GIL-safe

    @property
    def last_recording_path(self) -> Optional[str]:
        return self._worker.last_recording_path

    def open_camera(self, backend: str, index: int = 0) -> None:
        self._tab._sig_open_camera_idx.emit(backend, index)

    def close_camera(self) -> None:
        self._tab._sig_close_camera.emit()

    def set_parameter(self, name: str, value) -> None:
        self._tab._sig_set_param.emit(name, value)

    def set_watch_window(self, x: int, y: int, w: int, h: int) -> None:
        self._tab._sig_set_watch.emit(QRect(x, y, w, h))

    def start_recording(self, path: str, fps: float) -> None:
        self._tab._sig_start_recording.emit(path, fps)

    def stop_recording(self) -> None:
        self._tab._sig_stop_recording.emit()

    def snap_image(self) -> None:
        self._tab._sig_snap.emit()

    @property
    def watch_rect(self):
        return self._tab._preview.get_watch_rect()

    def snap_to_file(self, path: str, done_event=None) -> None:
        self._tab._sig_snap_to_file.emit(path, done_event)

    def capture_background(self, frames: int, blur_k: int, path: str, done_event=None) -> None:
        self._tab._sig_capture_bg.emit(frames, blur_k, path, done_event)


# ── Main tab widget ───────────────────────────────────────────────────────────

class AcquisitionTab(QWidget):
    """Acquisition tab: live camera preview + controls + protocol script runner."""

    log = Signal(str, str)   # message, level ("INFO" | "WARN" | "ERROR")

    # ── Signals to camera worker (queued, cross-thread) ───────────────────────
    _sig_open_camera_idx = Signal(str, int)
    _sig_close_camera    = Signal()
    _sig_start_stream    = Signal(float)
    _sig_stop_stream     = Signal()
    _sig_snap            = Signal()
    _sig_snap_to_file    = Signal(str, object)
    _sig_capture_bg      = Signal(int, int, str, object)
    _sig_set_param       = Signal(str, object)
    _sig_set_watch       = Signal(QRect)
    _sig_reset_watch     = Signal()
    _sig_start_recording    = Signal(str, float)
    _sig_stop_recording     = Signal()
    _sig_enumerate_cameras  = Signal(str)

    # ── Signal to acquisition worker ─────────────────────────────────────────
    _sig_run_script = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._daq:              Optional[object]           = None
        self._script_ctx:       Optional[ScriptContext]    = None
        self._help_dialog:      Optional[ScriptHelpDialog] = None
        self._latest_raw_frame: Optional[Any]               = None   # frame buffer for lag fix
        self._slow_mode:        bool                       = False  # preview paused during scripts

        # Camera worker — init_timer must run inside the camera thread, so connect
        # to started rather than using QTimer.singleShot from the main thread.
        self._cam_thread = QThread()
        self._cam_worker = CameraWorker()
        self._cam_worker.moveToThread(self._cam_thread)
        self._cam_thread.started.connect(self._cam_worker.init_timer)
        self._cam_thread.start()

        # Script-execution worker
        self._acq_thread = QThread()
        self._acq_worker = AcquisitionWorker()
        self._acq_worker.moveToThread(self._acq_thread)
        self._acq_thread.start()

        self._setup_ui()
        self._connect_signals()
        QTimer.singleShot(0, self._scan_cameras)

    # ── UI construction ───────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        # Output directory bar
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Output dir:"))
        self._output_dir_edit = QLineEdit()
        self._output_dir_edit.setPlaceholderText("Directory for recorded files…")
        out_row.addWidget(self._output_dir_edit)
        browse_btn = QPushButton("…")
        browse_btn.setFixedWidth(28)
        browse_btn.clicked.connect(self._browse_output)
        out_row.addWidget(browse_btn)
        root.addLayout(out_row)
        root.addWidget(self._build_status_bar())

        self._preview = CameraPreviewLabel()
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setStyleSheet("background-color: black;")
        self._preview.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._preview.setMinimumWidth(200)

        # Script section (left) | live preview (centre) | controls (right)
        main_split = QSplitter(Qt.Orientation.Horizontal)
        main_split.setChildrenCollapsible(False)
        main_split.addWidget(self._build_script_section())
        main_split.addWidget(self._preview)
        main_split.addWidget(self._build_controls_panel())
        main_split.setSizes([340, 600, 260])

        root.addWidget(main_split)

    def _build_status_bar(self) -> QWidget:
        """Narrow row of LED-style pills showing live system state."""
        bar = QWidget()
        bar.setFixedHeight(24)
        row = QHBoxLayout(bar)
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(6)

        def _pill(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setFixedHeight(20)
            lbl.setMinimumWidth(80)
            lbl.setStyleSheet(
                "border-radius: 4px; padding: 0 6px;"
                "background-color: #555; color: #ccc; font-size: 11px;"
            )
            return lbl

        self._pill_cam    = _pill("CAM  ○")
        self._pill_daq    = _pill("DAQ  ○")
        self._pill_script = _pill("SCRIPT  ○")
        self._pill_exp    = _pill("EXP  ○")

        for p in (self._pill_cam, self._pill_daq, self._pill_script, self._pill_exp):
            row.addWidget(p)
        row.addStretch()
        return bar

    def _set_pill(self, pill: QLabel, active: bool, text: str,
                  color: str = "#4a9") -> None:
        """Update a status pill's text and background colour."""
        if active:
            pill.setText(text)
            pill.setStyleSheet(
                f"border-radius: 4px; padding: 0 6px;"
                f"background-color: {color}; color: #fff; font-size: 11px; font-weight: bold;"
            )
        else:
            pill.setText(text)
            pill.setStyleSheet(
                "border-radius: 4px; padding: 0 6px;"
                "background-color: #555; color: #ccc; font-size: 11px;"
            )

    def _build_controls_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        container.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 2px 5px; max-height: 22px; }"
        )
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)
        layout.addWidget(self._build_camera_group())
        layout.addWidget(self._build_watch_group())
        layout.addWidget(self._build_daq_group())
        layout.addStretch()

        scroll.setWidget(container)
        return scroll

    def _build_camera_group(self) -> QGroupBox:
        box = QGroupBox("Camera")
        layout = QVBoxLayout(box)
        layout.setSpacing(4)
        layout.setContentsMargins(6, 10, 6, 6)

        index_row = QHBoxLayout()
        index_row.addWidget(QLabel("Camera:"))
        self._cam_index_combo = QComboBox()
        self._cam_index_combo.addItem("Test:0: Test Camera")
        self._cam_index_combo.setMinimumWidth(150)
        index_row.addWidget(self._cam_index_combo)
        self._cam_scan_btn = QPushButton("Scan")
        index_row.addWidget(self._cam_scan_btn)
        index_row.addStretch()
        layout.addLayout(index_row)

        open_row = QHBoxLayout()
        self._open_btn  = QPushButton("Open")
        self._close_btn = QPushButton("Close")
        self._close_btn.setEnabled(False)
        open_row.addWidget(self._open_btn)
        open_row.addWidget(self._close_btn)
        open_row.addStretch()
        layout.addLayout(open_row)

        fps_row = QHBoxLayout()
        fps_row.addWidget(QLabel("FPS:"))
        self._fps_spin = QDoubleSpinBox()
        self._fps_spin.setRange(1.0, 500.0)
        self._fps_spin.setValue(25.0)
        self._fps_spin.setDecimals(1)
        self._fps_spin.setEnabled(False)
        fps_row.addWidget(self._fps_spin)
        fps_row.addStretch()
        layout.addLayout(fps_row)

        exp_row = QHBoxLayout()
        exp_row.addWidget(QLabel("Exposure:"))
        self._exp_spin = QDoubleSpinBox()
        self._exp_spin.setRange(10.0, 1_000_000.0)
        self._exp_spin.setValue(10_000.0)
        self._exp_spin.setDecimals(0)
        self._exp_spin.setSingleStep(500.0)
        self._exp_spin.setEnabled(False)
        exp_row.addWidget(self._exp_spin)
        exp_row.addStretch()
        layout.addLayout(exp_row)

        gain_row = QHBoxLayout()
        gain_row.addWidget(QLabel("Gain:"))
        self._gain_spin = QDoubleSpinBox()
        self._gain_spin.setRange(0.0, 100.0)
        self._gain_spin.setValue(1.0)
        self._gain_spin.setDecimals(2)
        self._gain_spin.setEnabled(False)
        gain_row.addWidget(self._gain_spin)
        gain_row.addStretch()
        layout.addLayout(gain_row)

        stream_row = QHBoxLayout()
        self._live_btn = QPushButton("Live")
        self._live_btn.setCheckable(True)
        self._live_btn.setEnabled(False)
        self._snap_btn = QPushButton("Snap")
        self._snap_btn.setEnabled(False)
        stream_row.addWidget(self._live_btn)
        stream_row.addWidget(self._snap_btn)
        stream_row.addStretch()
        layout.addLayout(stream_row)

        exp_row = QHBoxLayout()
        self._exp_overlay_btn = QPushButton("Exp Overlay")
        self._exp_overlay_btn.setCheckable(True)
        self._exp_overlay_btn.setEnabled(False)
        exp_row.addWidget(self._exp_overlay_btn)
        exp_row.addStretch()
        layout.addLayout(exp_row)

        return box

    def _build_watch_group(self) -> QGroupBox:
        box = QGroupBox("Watch Window")
        layout = QVBoxLayout(box)
        layout.setSpacing(4)
        layout.setContentsMargins(6, 10, 6, 6)

        btn_row = QHBoxLayout()
        self._draw_watch_btn  = QPushButton("Draw")
        self._reset_watch_btn = QPushButton("Reset")
        self._copy_watch_btn  = QPushButton("Copy WATCH")
        self._draw_watch_btn.setEnabled(False)
        self._reset_watch_btn.setEnabled(False)
        self._copy_watch_btn.setEnabled(False)
        btn_row.addWidget(self._draw_watch_btn)
        btn_row.addWidget(self._reset_watch_btn)
        btn_row.addWidget(self._copy_watch_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        aspect_row = QHBoxLayout()
        aspect_row.addWidget(QLabel("Aspect:"))
        self._watch_aspect = QComboBox()
        self._watch_aspect.addItems(["Free", "1:1", "4:3", "16:9"])
        self._watch_aspect.setEnabled(False)
        aspect_row.addWidget(self._watch_aspect)
        aspect_row.addStretch()
        layout.addLayout(aspect_row)

        self._watch_dim_label = QLabel("-- × --")
        layout.addWidget(self._watch_dim_label)

        return box

    def _build_daq_group(self) -> QGroupBox:
        box = QGroupBox("DAQ")
        layout = QVBoxLayout(box)
        layout.setSpacing(4)
        layout.setContentsMargins(6, 10, 6, 6)

        dev_row = QHBoxLayout()
        dev_row.addWidget(QLabel("Device:"))
        self._daq_device = QLineEdit()
        self._daq_device.setPlaceholderText("Dev1")
        dev_row.addWidget(self._daq_device)
        layout.addLayout(dev_row)

        btn_row = QHBoxLayout()
        self._daq_connect_btn = QPushButton("Connect")
        self._daq_release_btn = QPushButton("Release")
        btn_row.addWidget(self._daq_connect_btn)
        btn_row.addWidget(self._daq_release_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._daq_status = QLabel("Not connected")
        layout.addWidget(self._daq_status)

        # Pin toggle grid — populated dynamically after connect
        pins_label = QLabel("Digital Output Pins:")
        layout.addWidget(pins_label)

        self._daq_pin_widget = QWidget()
        self._daq_pin_grid   = QGridLayout(self._daq_pin_widget)
        self._daq_pin_grid.setSpacing(3)
        self._daq_pin_grid.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._daq_pin_widget)

        self._daq_pin_buttons: dict[str, QPushButton] = {}

        return box

    def _build_script_section(self) -> QWidget:
        widget = QWidget()
        h_layout = QHBoxLayout(widget)
        h_layout.setContentsMargins(0, 0, 0, 0)
        h_layout.setSpacing(4)

        # Left: editor + log
        editor_layout = QVBoxLayout()
        editor_layout.addWidget(QLabel("Script (.acq):"))
        self._script_editor = QPlainTextEdit()
        self._script_editor.setFont(QFont("Courier New", 10))
        self._highlighter = ScriptHighlighter(self._script_editor.document())
        self._script_editor.setPlaceholderText(
            "# Acquisition protocol\n"
            "# SET fps = 30\n"
            "# RECORD 30\n"
            "# WAITKEY space\n"
            "# REPEAT 5:\n"
            "#   DELAY 1\n"
            "#   RECORD 10\n"
            "# END\n"
        )
        editor_layout.addWidget(self._script_editor)

        h_layout.addLayout(editor_layout)

        # Right: action buttons
        btn_layout = QVBoxLayout()
        btn_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._run_btn         = QPushButton("Run")
        self._stop_btn        = QPushButton("Stop")
        self._load_script_btn = QPushButton("Load…")
        self._save_script_btn = QPushButton("Save…")
        self._help_btn        = QPushButton("Help")
        self._stop_btn.setEnabled(False)
        for btn in (self._run_btn, self._stop_btn, self._load_script_btn,
                    self._save_script_btn, self._help_btn):
            btn_layout.addWidget(btn)
        btn_layout.addStretch()
        h_layout.addLayout(btn_layout)

        return widget

    # ── Signal wiring ─────────────────────────────────────────────────────────

    def _connect_signals(self) -> None:
        # Camera worker → UI
        # Frames feed a rolling buffer; a QTimer flushes it at ≤60 Hz to avoid
        # accumulating stale frames in the Qt event queue (the main source of lag).
        # DirectConnection: _store_raw_frame runs in the camera thread (just an
        # attribute assignment — GIL-safe) so no events accumulate in the Qt queue.
        self._cam_worker.frame_ready.connect(
            self._store_raw_frame, Qt.ConnectionType.DirectConnection
        )
        self._cam_worker.camera_opened.connect(self._on_camera_opened)
        self._cam_worker.camera_closed.connect(self._on_camera_closed)
        self._cam_worker.live_started.connect(self._on_live_started)
        self._cam_worker.live_stopped.connect(self._on_live_stopped)
        self._cam_worker.camera_watch_window_updated.connect(self._on_watch_updated)
        self._cam_worker.camera_watch_window_reset.connect(self._on_watch_reset)
        self._cam_worker.camera_stats_updated.connect(self._on_stats_updated)
        self._cam_worker.recording_started.connect(
            lambda _: self._set_pill(self._pill_cam, True, "REC  ●", "#c44")
        )
        self._cam_worker.recording_finished.connect(
            lambda _: self._set_pill(
                self._pill_cam, self._cam_worker.streaming, "CAM  ●", "#4a9"
            )
        )
        self._cam_worker.recording_error.connect(
            lambda msg: self._append_log(f"[Recording ERROR] {msg}", "ERROR")
        )
        self._cam_worker.snap_saved.connect(
            lambda p: self._append_log(f"[Snapshot] saved {os.path.basename(p)}")
        )
        self._cam_worker.bg_captured.connect(
            lambda p: self._append_log(f"[Background] saved {os.path.basename(p)}")
        )

        # Frame flush timer — decouples display rate from camera frame rate
        self._frame_timer = QTimer(self)
        self._frame_timer.setInterval(16)   # ~60 Hz
        self._frame_timer.timeout.connect(self._flush_frame)
        self._frame_timer.start()

        # UI → camera worker (all cross-thread via signals)
        self._sig_open_camera_idx.connect(self._cam_worker.open_camera_indexed)
        self._sig_close_camera.connect(self._cam_worker.close_camera)
        self._sig_start_stream.connect(self._cam_worker.start_stream)
        self._sig_stop_stream.connect(self._cam_worker.stop_stream)
        self._sig_snap.connect(self._cam_worker.snap_image)
        self._sig_snap_to_file.connect(self._cam_worker.snap_to_file)
        self._sig_capture_bg.connect(self._cam_worker.capture_background)
        self._sig_set_param.connect(self._cam_worker.set_parameter)
        self._sig_set_watch.connect(self._cam_worker.set_watch_window)
        self._sig_reset_watch.connect(self._cam_worker.reset_watch_window)
        self._sig_start_recording.connect(self._cam_worker.start_recording)
        self._sig_stop_recording.connect(self._cam_worker.stop_recording)
        self._sig_enumerate_cameras.connect(self._cam_worker.enumerate_cameras)
        self._cam_worker.saturation_stats.connect(self._on_saturation_stats)
        self._cam_worker.cameras_enumerated.connect(self._on_cameras_enumerated)

        # Camera control buttons
        self._open_btn.clicked.connect(self._open_camera)
        self._close_btn.clicked.connect(lambda: self._sig_close_camera.emit())
        self._cam_scan_btn.clicked.connect(self._scan_cameras)
        self._exp_overlay_btn.toggled.connect(self._preview.set_exposure_overlay)
        self._live_btn.clicked.connect(self._toggle_live)
        self._snap_btn.clicked.connect(lambda: self._sig_snap.emit())
        self._fps_spin.valueChanged.connect(
            lambda v: self._sig_set_param.emit("fps", v)
        )
        self._exp_spin.valueChanged.connect(
            lambda v: self._sig_set_param.emit("exposure", v)
        )
        self._gain_spin.valueChanged.connect(
            lambda v: self._sig_set_param.emit("gain", v)
        )

        # Watch window — drawing in the preview is visual-only; only scripts set the
        # actual camera watch window via _sig_set_watch / WATCH script command.
        self._draw_watch_btn.clicked.connect(self._begin_watch_draw)
        self._reset_watch_btn.clicked.connect(self._reset_watch_overlay)
        self._copy_watch_btn.clicked.connect(self._copy_watch_command)
        self._preview.watch_window_drawn.connect(self._on_watch_drawn)

        # DAQ
        self._daq_connect_btn.clicked.connect(self._connect_daq)
        self._daq_release_btn.clicked.connect(self._release_daq)

        # Script runner
        self._run_btn.clicked.connect(self._run_script)
        self._stop_btn.clicked.connect(self._stop_script)
        self._load_script_btn.clicked.connect(self._load_script_file)
        self._save_script_btn.clicked.connect(self._save_script_file)
        self._help_btn.clicked.connect(self._show_help)

        # Acquisition worker → UI (auto-queued since different threads)
        self._sig_run_script.connect(self._acq_worker.run)
        self._acq_worker.progress.connect(lambda msg: self._append_log(msg, "SCRIPT"))
        self._acq_worker.finished.connect(self._on_script_done)
        self._acq_worker.aborted.connect(self._on_script_done)
        self._acq_worker.error.connect(self._on_script_error)

    # ── Camera handlers ───────────────────────────────────────────────────────

    @Slot()
    def _on_camera_opened(self) -> None:
        self._open_btn.setEnabled(False)
        self._close_btn.setEnabled(True)
        self._live_btn.setEnabled(True)
        self._snap_btn.setEnabled(True)
        # Don't re-enable camera parameter spinboxes if a script is running —
        # _run_script() disabled them and _on_script_done() will restore them.
        script_running = self._script_ctx is not None
        self._fps_spin.setEnabled(not script_running)
        self._exp_spin.setEnabled(not script_running)
        self._gain_spin.setEnabled(not script_running)
        self._draw_watch_btn.setEnabled(True)
        self._watch_aspect.setEnabled(True)
        self._exp_overlay_btn.setEnabled(True)
        self._set_pill(self._pill_cam, True, "CAM  ●", "#4a9")

    @Slot()
    def _on_camera_closed(self) -> None:
        self._open_btn.setEnabled(True)
        self._close_btn.setEnabled(False)
        self._live_btn.setEnabled(False)
        self._snap_btn.setEnabled(False)
        self._fps_spin.setEnabled(False)
        self._exp_spin.setEnabled(False)
        self._gain_spin.setEnabled(False)
        self._draw_watch_btn.setEnabled(False)
        self._reset_watch_btn.setEnabled(False)
        self._copy_watch_btn.setEnabled(False)
        self._watch_aspect.setEnabled(False)
        self._exp_overlay_btn.setEnabled(False)
        self._exp_overlay_btn.setChecked(False)
        self._set_pill(self._pill_cam, False, "CAM  ○")

    def _open_camera(self) -> None:
        text = self._cam_index_combo.currentText()
        try:
            parts = text.split(":")
            camera_type = parts[0].strip()
            idx = int(parts[1].strip())
        except (ValueError, IndexError):
            camera_type = "Test"
            idx = 0
        self._sig_open_camera_idx.emit(camera_type, idx)

    def _scan_cameras(self) -> None:
        self._cam_scan_btn.setEnabled(False)
        self._cam_index_combo.clear()
        self._cam_index_combo.addItem("Scanning…")
        self._sig_enumerate_cameras.emit("ALL")

    @Slot(list)
    def _on_cameras_enumerated(self, results: list) -> None:
        self._cam_scan_btn.setEnabled(True)
        self._cam_index_combo.clear()
        for r in results:
            self._cam_index_combo.addItem(r)

    @Slot(float, float)
    def _on_saturation_stats(self, over: float, under: float) -> None:
        total = over + under
        text  = f"EXP  ↑{over:.1f}% ↓{under:.1f}%"
        color = "#a44" if total > 5 else ("#a84" if total > 1 else "#555")
        self._set_pill(self._pill_exp, total > 1, text, color)
        if self._exp_overlay_btn.isChecked() and self._latest_raw_frame is not None:
            self._preview.update_exposure_overlay(self._latest_raw_frame)

    def _toggle_live(self) -> None:
        if self._live_btn.isChecked():
            self._sig_start_stream.emit(self._fps_spin.value())
        else:
            self._sig_stop_stream.emit()

    @Slot()
    def _on_live_started(self) -> None:
        self._live_btn.setText("Stop")
        self._preview.set_hud_visible(True)
        self._set_pill(self._pill_cam, True, "CAM  ●", "#4a9")

    @Slot()
    def _on_live_stopped(self) -> None:
        self._live_btn.setText("Live")
        self._live_btn.setChecked(False)
        self._preview.set_hud_visible(False)
        self._set_pill(self._pill_cam, True, "CAM  ●", "#666")

    @Slot(QRect)
    def _on_watch_updated(self, rect: QRect) -> None:
        """Camera watch window was set by a script — update origin, labels, and overlay."""
        if rect.isNull():
            self._watch_dim_label.setText("-- × --")
            self._reset_watch_btn.setEnabled(False)
            self._copy_watch_btn.setEnabled(False)
            self._preview.set_watch_text("")
            self._preview.set_watch_origin(QPoint(0, 0))
            self._preview.set_watch_rect(None)
        else:
            self._watch_dim_label.setText(
                f"WATCH  {rect.x()}  {rect.width()}  {rect.y()}  {rect.height()}"
            )
            self._reset_watch_btn.setEnabled(True)
            self._copy_watch_btn.setEnabled(True)
            self._preview.set_watch_text(
                f"({rect.x()},{rect.y()}) {rect.width()}×{rect.height()}"
            )
            self._preview.set_watch_origin(QPoint(rect.x(), rect.y()))
            self._preview.set_watch_rect(rect)

    @Slot()
    def _on_watch_reset(self) -> None:
        """Camera watch window was reset — clear labels, origin, and overlay."""
        self._watch_dim_label.setText("-- × --")
        self._reset_watch_btn.setEnabled(False)
        self._copy_watch_btn.setEnabled(False)
        self._preview.set_watch_text("")
        self._preview.set_watch_origin(QPoint(0, 0))
        self._preview.set_watch_rect(None)
        self._preview.setPixmap(QPixmap())

    @Slot(QRect)
    def _on_watch_drawn(self, rect: QRect) -> None:
        """Preview watch rect drawn/moved/resized or cleared — update labels only."""
        if rect.isNull() or rect.isEmpty():
            self._watch_dim_label.setText("-- × --")
            self._reset_watch_btn.setEnabled(False)
            self._copy_watch_btn.setEnabled(False)
            self._preview.set_watch_text("")
        else:
            self._watch_dim_label.setText(
                f"WATCH  {rect.x()}  {rect.width()}  {rect.y()}  {rect.height()}"
            )
            self._reset_watch_btn.setEnabled(True)
            self._copy_watch_btn.setEnabled(True)
            self._preview.set_watch_text(
                f"({rect.x()},{rect.y()}) {rect.width()}×{rect.height()}"
            )

    def _reset_watch_overlay(self) -> None:
        """Clear the watch window overlay in the preview (does not touch the camera)."""
        self._preview.clear_watch_rect()

    def _copy_watch_command(self) -> None:
        """Copy the WATCH command for the current overlay rect to the clipboard."""
        from PySide6.QtWidgets import QApplication
        rect = self._preview.get_watch_rect()
        if rect is not None and not rect.isNull():
            cmd = f"WATCH {rect.x()} {rect.width()} {rect.y()} {rect.height()}"
            QApplication.clipboard().setText(cmd)

    @Slot(float, int, int)
    def _on_stats_updated(self, fps: float, dropped: int, disconnects: int) -> None:
        self._preview.update_hud(fps, dropped, disconnects)

    def _begin_watch_draw(self) -> None:
        text = self._watch_aspect.currentText()
        aspect = None
        if text != "Free":
            w, h = map(int, text.split(":"))
            aspect = w / h
        self._preview.begin_watch_selection(aspect)

    # ── DAQ handlers ──────────────────────────────────────────────────────────

    def _connect_daq(self) -> None:
        device = self._daq_device.text().strip()
        if not device:
            self._append_log("DAQ: enter a device name (e.g. Dev1)", "WARN")
            return
        try:
            if self._daq:
                self._daq.close()
            self._daq = make_daq(device, log_fn=self._append_log)
            self._daq_status.setText(type(self._daq).__name__)
            self._populate_daq_pins(device)
            self._set_pill(self._pill_daq, True, "DAQ  ●", "#4a9")
        except Exception as exc:
            self._daq_status.setText("Error")
            self._append_log(f"DAQ error: {exc}", "ERROR")
            self._set_pill(self._pill_daq, False, "DAQ  ○")

    def _release_daq(self) -> None:
        if self._daq:
            try:
                self._daq.close()
            except Exception:
                pass
            self._daq = None
            self._daq_status.setText("Not connected")
        self._clear_daq_pins()
        self._set_pill(self._pill_daq, False, "DAQ  ○")

    def _populate_daq_pins(self, device: str) -> None:
        """Build a grid of toggle buttons for every digital output line on *device*."""
        self._clear_daq_pins()

        lines: list[str] = []
        if device:
            try:
                import nidaqmx.system as _sys
                dev_obj = _sys.Device(device)
                lines = [ln.name for ln in dev_obj.do_lines]
            except Exception:
                pass

        # Fall back to a standard port0/line0-7 layout when hardware query fails
        if not lines:
            lines = [f"{device}/port0/line{i}" if device else f"port0/line{i}"
                     for i in range(8)]

        cols = 4
        for idx, full_name in enumerate(lines):
            # Show only the short portion after the device prefix for readability
            short = full_name.split("/", 1)[1] if "/" in full_name else full_name
            btn = QPushButton(short)
            btn.setCheckable(True)
            btn.setFixedHeight(24)
            btn.setToolTip(full_name)
            btn.clicked.connect(lambda checked, ch=full_name, b=btn: self._toggle_daq_pin(ch, b))
            row, col = divmod(idx, cols)
            self._daq_pin_grid.addWidget(btn, row, col)
            self._daq_pin_buttons[full_name] = btn

    def _clear_daq_pins(self) -> None:
        """Remove all pin toggle buttons from the grid."""
        for btn in self._daq_pin_buttons.values():
            self._daq_pin_grid.removeWidget(btn)
            btn.deleteLater()
        self._daq_pin_buttons.clear()

    def _toggle_daq_pin(self, channel: str, btn: QPushButton) -> None:
        """Set a digital output line high or low based on button checked state."""
        if not self._daq:
            btn.setChecked(False)
            return
        value = btn.isChecked()
        try:
            self._daq.digital_out(channel, value)
        except Exception as exc:
            self._append_log(f"DAQ pin error ({channel}): {exc}")
            btn.setChecked(not value)  # revert on failure

    # ── Script handlers ───────────────────────────────────────────────────────

    def _run_script(self) -> None:
        text = self._script_editor.toPlainText().strip()
        if not text:
            self._append_log("No script to run.")
            return

        proxy = _CameraProxy(self._cam_worker, self)
        cam_sz = self._cam_worker.frame_size  # (w, h) or None
        ctx = ScriptContext(
            camera_worker=proxy,
            daq=self._daq,
            app_paths=AppPaths,
            output_dir=self._output_dir_edit.text().strip() or ".",
            waitkey_callback=self._on_waitkey_started,
            camera_fps=float(self._fps_spin.value()),
            camera_exposure=float(self._exp_spin.value()),
            camera_gain=float(self._gain_spin.value()),
            camera_width=int(cam_sz[0]) if cam_sz else 0,
            camera_height=int(cam_sz[1]) if cam_sz else 0,
        )
        self._script_ctx = ctx

        self._run_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._append_log("Script started.")

        # Disable camera spinboxes to prevent mid-script parameter changes
        for w in (self._fps_spin, self._exp_spin, self._gain_spin):
            w.setEnabled(False)

        # Slow-computer mode: stop the frame-display timer so cv_image_to_qpixmap
        # and setPixmap don't compete with the camera / recording pipeline for CPU.
        if self._slow_mode:
            self._frame_timer.stop()
            self._preview.setPixmap(QPixmap())

        self._set_pill(self._pill_script, True, "SCRIPT  ●", "#f90")
        self._sig_run_script.emit(text, ctx)

    def _stop_script(self) -> None:
        # Direct call — abort only sets threading.Events, fully thread-safe.
        self._acq_worker.abort()

    @Slot()
    def _on_script_done(self) -> None:
        self._run_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._script_ctx = None
        self._set_pill(self._pill_script, False, "SCRIPT  ○")
        for w in (self._fps_spin, self._exp_spin, self._gain_spin):
            w.setEnabled(True)
        if self._slow_mode:
            self._frame_timer.start()

    @Slot(str)
    def _on_script_error(self, msg: str) -> None:
        self._append_log(f"ERROR: {msg}", "ERROR")
        self._run_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._script_ctx = None
        self._set_pill(self._pill_script, False, "SCRIPT  ○")
        for w in (self._fps_spin, self._exp_spin, self._gain_spin):
            w.setEnabled(True)
        if self._slow_mode:
            self._frame_timer.start()

    def _load_script_file(self) -> None:
        try:
            start = str(AppPaths.scripts_dir)
        except Exception:
            start = ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Script", start, "Acquisition scripts (*.acq);;All files (*)"
        )
        if path:
            try:
                self._script_editor.setPlainText(Path(path).read_text(encoding="utf-8"))
            except Exception as exc:
                self._append_log(f"Load error: {exc}")

    def _save_script_file(self) -> None:
        try:
            start = str(AppPaths.scripts_dir)
        except Exception:
            start = ""
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Script", start, "Acquisition scripts (*.acq);;All files (*)"
        )
        if path:
            try:
                Path(path).write_text(
                    self._script_editor.toPlainText(), encoding="utf-8"
                )
            except Exception as exc:
                self._append_log(f"Save error: {exc}")

    def _browse_output(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "Select output directory", self._output_dir_edit.text()
        )
        if d:
            self._output_dir_edit.setText(d)

    @Slot(bool)
    def set_slow_mode(self, enabled: bool) -> None:
        """Pause the live preview while a script is running to free CPU."""
        self._slow_mode = enabled

    def _append_log(self, msg: str, level: str = "INFO") -> None:
        self.log.emit(msg, level)

    # ── WAITKEY focus + key-press forwarding ─────────────────────────────────

    def _on_waitkey_started(self) -> None:
        """Called from the script thread when WAITKEY begins — grabs focus via the UI thread."""
        QMetaObject.invokeMethod(self, "_grab_focus", Qt.ConnectionType.QueuedConnection)

    @Slot()
    def _grab_focus(self) -> None:
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.activateWindow()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._script_ctx is not None:
            _SPECIAL = {
                Qt.Key.Key_Space:  " ",
                Qt.Key.Key_Return: "\r",
                Qt.Key.Key_Enter:  "\r",
                Qt.Key.Key_Escape: "\x1b",
            }
            key = event.key()
            if key in _SPECIAL:
                self._script_ctx.last_key = _SPECIAL[key]
            else:
                text = event.text()
                self._script_ctx.last_key = text.lower() if text else ""
            self._script_ctx.key_event.set()
        super().keyPressEvent(event)

    # ── Help dialog ───────────────────────────────────────────────────────────

    def _show_help(self) -> None:
        if self._help_dialog is None:
            self._help_dialog = ScriptHelpDialog(self)
        self._help_dialog.show()
        self._help_dialog.raise_()
        self._help_dialog.activateWindow()

    @Slot(object)
    def _store_raw_frame(self, frame) -> None:
        """Store the latest raw frame; the flush timer converts it to a pixmap at ≤60 Hz."""
        self._latest_raw_frame = frame

    def _flush_frame(self) -> None:
        """Called by the 60 Hz timer — renders the most recent raw frame, dropping stale ones."""
        if self._latest_raw_frame is not None:
            self._preview.setPixmap(cv_image_to_qpixmap(self._latest_raw_frame))
            self._latest_raw_frame = None

    # ── Settings persistence properties (used by AcquisitionWindow only) ─────
    # These expose the minimal UI state that needs to survive app restarts.
    # AcquisitionWindow reads/writes these instead of accessing private widgets
    # directly, so changes to the widget layout don't break the window.

    @property
    def output_dir(self) -> str:
        return self._output_dir_edit.text()

    @output_dir.setter
    def output_dir(self, v: str) -> None:
        self._output_dir_edit.setText(v)

    @property
    def camera_type(self) -> str:
        text = self._cam_index_combo.currentText()
        try:
            return text.split(":")[0].strip()
        except (ValueError, IndexError):
            return "Test"

    @camera_type.setter
    def camera_type(self, v: str) -> None:
        prefix = v.strip() + ":"
        for i in range(self._cam_index_combo.count()):
            if self._cam_index_combo.itemText(i).startswith(prefix):
                self._cam_index_combo.setCurrentIndex(i)
                return

    @property
    def fps(self) -> float:
        return self._fps_spin.value()

    @fps.setter
    def fps(self, v: float) -> None:
        self._fps_spin.setValue(v)

    @property
    def exposure(self) -> float:
        return self._exp_spin.value()

    @exposure.setter
    def exposure(self, v: float) -> None:
        self._exp_spin.setValue(v)

    @property
    def gain(self) -> float:
        return self._gain_spin.value()

    @gain.setter
    def gain(self, v: float) -> None:
        self._gain_spin.setValue(v)

    @property
    def script_content(self) -> str:
        return self._script_editor.toPlainText()

    @script_content.setter
    def script_content(self, v: str) -> None:
        self._script_editor.setPlainText(v)

    @property
    def daq_device(self) -> str:
        return self._daq_device.text()

    @daq_device.setter
    def daq_device(self, v: str) -> None:
        self._daq_device.setText(v)

    def set_watch_rect(self, x: int, y: int, w: int, h: int) -> None:
        from PySide6.QtCore import QRect
        rect = QRect(x, y, w, h)
        self._sig_set_watch.emit(rect)

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def shutdown(self) -> None:
        """Stop threads cleanly. Call from the application's aboutToQuit."""
        self._acq_worker.abort()
        self._acq_thread.quit()
        self._acq_thread.wait(2000)
        self._sig_stop_stream.emit()
        self._sig_close_camera.emit()
        self._cam_thread.quit()
        self._cam_thread.wait(2000)
        if self._daq:
            try:
                self._daq.close()
            except Exception:
                pass
