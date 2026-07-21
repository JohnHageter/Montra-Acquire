import html as _html_mod

from PySide6.QtWidgets import (
    QDockWidget,
    QWidget,
    QVBoxLayout,
    QTextEdit,
    QPushButton,
    QHBoxLayout,
)
from PySide6.QtCore import Qt, QDateTime
from montra_acquire.ui.utils.logger import logger


class ConsoleDock(QDockWidget):
    def __init__(self, parent=None):
        super().__init__("Console", parent)

        self.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.TopDockWidgetArea
        )

        self._verbose: bool = False

        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.console)

        controls = QHBoxLayout()
        controls.addStretch()
        self.clear_btn = QPushButton("Clear")
        controls.addWidget(self.clear_btn)
        layout.addLayout(controls)

        self.setWidget(container)

        self.clear_btn.clicked.connect(self.console.clear)
        logger.log_signal.connect(self.log)

    def set_verbose(self, verbose: bool) -> None:
        self._verbose = verbose

    def log(self, message: str, level: str = "INFO") -> None:
        if level == "INFO" and not self._verbose:
            return
        timestamp = QDateTime.currentDateTime().toString("HH:mm:ss")
        safe = _html_mod.escape(message)
        prefix = f"[{timestamp}] [{level}] "
        safe_prefix = _html_mod.escape(prefix)
        if level == "ERROR":
            line = f'<b style="color:#ff5555;">{safe_prefix}{safe}</b>'
        elif level == "WARN":
            line = f'<span style="color:#ffbb33;">{safe_prefix}{safe}</span>'
        elif level == "SCRIPT":
            line = f'<span style="color:#56c8d8;">{safe_prefix}{safe}</span>'
        else:
            line = f'{safe_prefix}{safe}'
        self.console.append(line)
