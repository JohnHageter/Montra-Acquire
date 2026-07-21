from pathlib import Path

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import QApplication, QMainWindow, QSizePolicy

from montra.app_paths import AppPaths
from montra_acquire.ui.acquisition_tab import AcquisitionTab
from montra_acquire.ui.docking.console_dock import ConsoleDock
from montra_acquire.ui.utils.themes import THEMES, apply_theme

_DEFAULT_THEME = "Light"
_SETTINGS_ORG  = "PlanariaLab"
_SETTINGS_APP  = "Acquire"


class AcquisitionWindow(QMainWindow):
    """Standalone window for the acquisition workflow.

    Can be used independently (python main_acquisition.py) or composed into the
    combined launcher (python main.py).
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        AppPaths.init(Path(__file__).parent.parent.parent.parent)

        self.setWindowTitle("Planaria — Acquire")
        self.resize(1400, 900)
        self.setFont(QFont("Helvetica", 10))
        self._current_theme = _DEFAULT_THEME
        apply_theme(QApplication.instance(), _DEFAULT_THEME)

        # Console dock
        self.console_dock = ConsoleDock(self)
        self.console_dock.setObjectName("ConsoleDock")
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.console_dock)
        self.console_dock.widget().setMinimumHeight(150)
        self.console_dock.widget().setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

        # Central widget
        self.acq_tab = AcquisitionTab(self)
        # Route script-log messages to console; level is forwarded so WARN/ERROR are colored.
        self.acq_tab.log.connect(self.console_dock.log)
        self.setCentralWidget(self.acq_tab)

        self._build_menu_bar()
        self.statusBar().hide()

        QApplication.instance().aboutToQuit.connect(self.acq_tab.shutdown)

        self._restore_settings()

    def _build_menu_bar(self) -> None:
        mb = self.menuBar()

        file_menu = mb.addMenu("&File")
        act_exit = QAction("E&xit", self)
        act_exit.setShortcut("Ctrl+Q")
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)

        tools_menu = mb.addMenu("&Tools")

        self._act_verbose = QAction("Verbose Logging", self)
        self._act_verbose.setCheckable(True)
        self._act_verbose.setChecked(False)
        self._act_verbose.triggered.connect(self.console_dock.set_verbose)
        tools_menu.addAction(self._act_verbose)

        self._act_slow = QAction("Slow Computer Mode", self)
        self._act_slow.setCheckable(True)
        self._act_slow.setChecked(False)
        self._act_slow.setToolTip(
            "Pause the camera preview while a script is running to free CPU "
            "for recording and camera I/O."
        )
        self._act_slow.triggered.connect(self.acq_tab.set_slow_mode)
        tools_menu.addAction(self._act_slow)

        tools_menu.addSeparator()

        theme_menu = tools_menu.addMenu("Theme")
        for name in THEMES:
            act = QAction(name, self)
            act.setCheckable(True)
            act.setChecked(name == self._current_theme)
            act.triggered.connect(lambda checked, n=name: self._set_theme(n))
            theme_menu.addAction(act)
        self._theme_menu = theme_menu

    def _set_theme(self, name: str) -> None:
        self._current_theme = name
        self.setStyleSheet("")
        apply_theme(QApplication.instance(), name)
        for action in self._theme_menu.actions():
            action.setChecked(action.text() == name)

    def closeEvent(self, event) -> None:
        self._save_settings()
        super().closeEvent(event)

    def _save_settings(self) -> None:
        s = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        s.setValue("geometry",      self.saveGeometry())
        s.setValue("windowState",   self.saveState())
        s.setValue("theme",         self._current_theme)
        s.setValue("verbose",       self._act_verbose.isChecked())
        s.setValue("slowMode",      self._act_slow.isChecked())
        tab = self.acq_tab
        s.setValue("outputDir",     tab.output_dir)
        s.setValue("cameraType",    tab.camera_type)
        s.setValue("fps",           tab.fps)
        s.setValue("exposure",      tab.exposure)
        s.setValue("gain",          tab.gain)
        s.setValue("scriptContent", tab.script_content)
        s.setValue("daqDevice",     tab.daq_device)
        try:
            rect = tab._preview.get_watch_rect()
            if rect and not rect.isNull():
                s.setValue("watchRect", f"{rect.x()},{rect.y()},{rect.width()},{rect.height()}")
        except Exception:
            pass

    def _restore_settings(self) -> None:
        s = QSettings(_SETTINGS_ORG, _SETTINGS_APP)

        geom = s.value("geometry")
        if geom:
            self.restoreGeometry(geom)
        state = s.value("windowState")
        if state:
            self.restoreState(state)

        theme = s.value("theme", _DEFAULT_THEME)
        if theme and theme != self._current_theme:
            self._set_theme(theme)

        verbose = s.value("verbose", False, type=bool)
        self._act_verbose.setChecked(verbose)
        self.console_dock.set_verbose(verbose)

        slow = s.value("slowMode", False, type=bool)
        self._act_slow.setChecked(slow)
        self.acq_tab.set_slow_mode(slow)

        tab = self.acq_tab
        output_dir = s.value("outputDir", "")
        if output_dir:
            tab.output_dir = output_dir

        cam_type = s.value("cameraType", "")
        if cam_type:
            tab.camera_type = cam_type

        fps = s.value("fps", None)
        if fps is not None:
            tab.fps = float(fps)

        exposure = s.value("exposure", None)
        if exposure is not None:
            tab.exposure = float(exposure)

        gain = s.value("gain", None)
        if gain is not None:
            tab.gain = float(gain)

        script = s.value("scriptContent", "")
        if script:
            tab.script_content = script

        daq_device = s.value("daqDevice", "")
        if daq_device:
            tab.daq_device = daq_device

        try:
            watch_str = s.value("watchRect", "")
            if watch_str:
                x, y, w, h = (int(v) for v in watch_str.split(","))
                tab.set_watch_rect(x, y, w, h)
        except Exception:
            pass
