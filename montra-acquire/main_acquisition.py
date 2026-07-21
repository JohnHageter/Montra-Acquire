import sys
from PySide6.QtWidgets import QApplication
from montra_acquire.ui.acquisition_window import AcquisitionWindow

def main() -> None:
    app = QApplication(sys.argv)
    win = AcquisitionWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
