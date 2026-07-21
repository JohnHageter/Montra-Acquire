from PySide6.QtCore import QObject, Signal


class Logger(QObject):
    log_signal = Signal(str, str)  # message, level


logger = Logger()
