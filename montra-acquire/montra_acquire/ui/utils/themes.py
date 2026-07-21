"""
UI theme stylesheets.

Usage
─────
from montra_acquire.ui.utils.themes import THEMES, apply_theme

apply_theme(app_or_widget, "Dark Blue")
"""

from __future__ import annotations

from typing import Dict

# ── Theme: Green / Black (default) ───────────────────────────────────────────

_GREEN_BLACK = """
QWidget {
    background-color: #000000;
    color: #CCFFCC;
    font-family: Helvetica, Arial, sans-serif;
}
QMainWindow, QDockWidget { background-color: #0A140A; }
QDockWidget::title { background-color: #000000; color: #88CC88; padding: 4px; border-bottom: 1px solid #000000; }
QDockWidget > QWidget { border: 1px solid #000000; }

QTabWidget::pane { border: 1px solid #000000; background-color: #000000; }
QTabBar::tab { background-color: #000000; color: #88CC88; border: 1px solid #000000; border-bottom: none; padding: 6px 16px; margin-right: 2px; }
QTabBar::tab:selected { background-color: #000000; color: #00FF66; border-top: 2px solid #00CC44; }
QTabBar::tab:hover:!selected { background-color: #000000; color: #AAFFAA; }

QPushButton { background-color: #000000; border: 1px solid #1A6A1A; padding: 5px 12px; border-radius: 4px; color: #AAFFAA; min-height: 22px; }
QPushButton:hover:!disabled { background-color: #000000; border: 1px solid #00CC44; color: #FFFFFF; }
QPushButton:pressed { background-color: #00882B; border: 2px solid #00FF66; color: #000000; padding: 4px 11px; }
QPushButton:checked { background-color: #005522; border: 2px solid #00CC44; color: #00FF88; }
QPushButton:checked:hover { background-color: #006622; border: 2px solid #00FF66; color: #FFFFFF; }
QPushButton:disabled { background-color: #000000; color: #2A5C2A; border: 1px solid #000000; }

QToolButton { background-color: #000000; border: 1px solid #000000; padding: 4px 8px; border-radius: 3px; color: #AAFFAA; }
QToolButton:hover { background-color: #000000; border: 1px solid #00CC44; color: #FFFFFF; }
QToolButton:pressed { background-color: #00882B; border: 2px solid #00FF66; color: #000000; }
QToolButton:checked { background-color: #005522; border: 2px solid #00CC44; color: #00FF88; }
QToolButton:disabled { background-color: #0A1A0A; color: #2A5C2A; border: 1px solid #000000; }

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background-color: #000000; border: 1px solid #000000; border-radius: 3px; padding: 1px 4px; min-height: 20px; color: #CCFFCC; selection-background-color: #00661A; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border: 1px solid #00CC44; }
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled { color: #2A5C2A; border: 1px solid #152015; }

QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 18px; border-left: 1px solid #000000; border-bottom: 1px solid #000000; background: #000000; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 18px; border-left: 1px solid #000000; border-top: 1px solid #000000; background: #000000; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { width: 0; height: 0; border-left: 4px solid transparent; border-right: 4px solid transparent; border-bottom: 5px solid #88CC88; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { width: 0; height: 0; border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 5px solid #88CC88; }

QComboBox::drop-down { width: 22px; border-left: 1px solid #000000; background: #000000; }
QComboBox::down-arrow { width: 0; height: 0; border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 5px solid #88CC88; }
QComboBox QAbstractItemView { background-color: #000000; border: 1px solid #000000; selection-background-color: #005522; color: #CCFFCC; }

QCheckBox { color: #AAFFAA; spacing: 6px; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #000000; background-color: #000000; border-radius: 2px; }
QCheckBox::indicator:checked { background-color: #00882B; border: 1px solid #00CC44; }
QCheckBox::indicator:hover { border: 1px solid #00CC44; }

QGroupBox { border: 1px solid #000000; border-radius: 4px; margin-top: 8px; padding-top: 4px; color: #88CC88; font-weight: bold; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 8px; padding: 0 4px; color: #00CC44; }

QScrollArea { border: none; background-color: transparent; }
QScrollBar:vertical { background: #000000; width: 10px; border: none; }
QScrollBar::handle:vertical { background: #000000; min-height: 20px; border-radius: 5px; }
QScrollBar::handle:vertical:hover { background: #00CC44; }
QScrollBar:horizontal { background: #000000; height: 10px; border: none; }
QScrollBar::handle:horizontal { background: #000000; min-width: 20px; border-radius: 5px; }
QScrollBar::handle:horizontal:hover { background: #00CC44; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }

QSplitter::handle { background-color: #000000; width: 3px; height: 3px; }
QSplitter::handle:hover { background-color: #00CC44; }

QSlider::groove:horizontal { background: #000000; height: 6px; border-radius: 3px; }
QSlider::handle:horizontal { background: #00CC44; width: 14px; height: 14px; margin: -4px 0; border-radius: 7px; border: 1px solid #00FF66; }
QSlider::handle:horizontal:hover { background: #00FF66; }

QProgressBar { background-color: #000000; border: 1px solid #000000; border-radius: 4px; text-align: center; color: #CCFFCC; height: 14px; }
QProgressBar::chunk { background-color: #00882B; border-radius: 3px; }

QListWidget, QTreeWidget, QTableWidget { background-color: #101F10; border: 1px solid #000000; alternate-background-color: #000000; color: #CCFFCC; gridline-color: #000000; selection-background-color: #005522; selection-color: #FFFFFF; }
QHeaderView::section { background-color: #000000; color: #88CC88; border: 1px solid #000000; padding: 4px; }

QLabel { color: #AAFFAA; background: transparent; }

QMenuBar { background-color: #0A140A; color: #AAFFAA; border-bottom: 1px solid #000000; }
QMenuBar::item:selected { background-color: #000000; }
QMenu { background-color: #000000; border: 1px solid #000000; color: #CCFFCC; }
QMenu::item:selected { background-color: #005522; }
QMenu::separator { height: 1px; background: #1A3A1A; margin: 2px 6px; }

QToolTip { background-color: #000000; color: #CCFFCC; border: 1px solid #00CC44; padding: 4px; }
QTextEdit, QPlainTextEdit { background-color: #000000; color: #88CC88; border: 1px solid #000000; font-family: "Courier New", monospace; }
QDialogButtonBox QPushButton { min-width: 70px; }
"""


# ── Theme: Dark Blue ──────────────────────────────────────────────────────────

_DARK_BLUE = """
QWidget {
    background-color: #0A0C14;
    color: #C8D8F8;
    font-family: Helvetica, Arial, sans-serif;
}
QMainWindow, QDockWidget { background-color: #0D1020; }
QDockWidget::title { background-color: #0A0C14; color: #7090C0; padding: 4px; border-bottom: 1px solid #1A2040; }
QDockWidget > QWidget { border: 1px solid #1A2040; }

QTabWidget::pane { border: 1px solid #1A2040; background-color: #0A0C14; }
QTabBar::tab { background-color: #0A0C14; color: #7090C0; border: 1px solid #1A2040; border-bottom: none; padding: 6px 16px; margin-right: 2px; }
QTabBar::tab:selected { background-color: #0A0C14; color: #4499FF; border-top: 2px solid #2266CC; }
QTabBar::tab:hover:!selected { background-color: #0D1020; color: #AAC8FF; }

QPushButton { background-color: #0A0C14; border: 1px solid #1E3A6A; padding: 5px 12px; border-radius: 4px; color: #AABCDF; min-height: 22px; }
QPushButton:hover:!disabled { background-color: #0D1020; border: 1px solid #2266CC; color: #FFFFFF; }
QPushButton:pressed { background-color: #1A3A8A; border: 2px solid #4499FF; color: #FFFFFF; padding: 4px 11px; }
QPushButton:checked { background-color: #102060; border: 2px solid #2266CC; color: #6699FF; }
QPushButton:disabled { background-color: #0A0C14; color: #2A3A5A; border: 1px solid #1A2040; }

QToolButton { background-color: #0A0C14; border: 1px solid #1A2040; padding: 4px 8px; border-radius: 3px; color: #AABCDF; }
QToolButton:hover { background-color: #0D1020; border: 1px solid #2266CC; color: #FFFFFF; }
QToolButton:pressed { background-color: #1A3A8A; border: 2px solid #4499FF; color: #FFFFFF; }
QToolButton:checked { background-color: #102060; border: 2px solid #2266CC; color: #6699FF; }
QToolButton:disabled { background-color: #0A0C14; color: #2A3A5A; border: 1px solid #1A2040; }

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background-color: #070910; border: 1px solid #1A2040; border-radius: 3px; padding: 1px 4px; min-height: 20px; color: #C8D8F8; selection-background-color: #1A3A8A; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border: 1px solid #2266CC; }
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled { color: #2A3A5A; }

QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 18px; border-left: 1px solid #1A2040; border-bottom: 1px solid #1A2040; background: #070910; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 18px; border-left: 1px solid #1A2040; border-top: 1px solid #1A2040; background: #070910; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { width: 0; height: 0; border-left: 4px solid transparent; border-right: 4px solid transparent; border-bottom: 5px solid #7090C0; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { width: 0; height: 0; border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 5px solid #7090C0; }

QComboBox::drop-down { width: 22px; border-left: 1px solid #1A2040; background: #070910; }
QComboBox::down-arrow { width: 0; height: 0; border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 5px solid #7090C0; }
QComboBox QAbstractItemView { background-color: #070910; border: 1px solid #1A2040; selection-background-color: #102060; color: #C8D8F8; }

QCheckBox { color: #AABCDF; spacing: 6px; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #1A2040; background-color: #070910; border-radius: 2px; }
QCheckBox::indicator:checked { background-color: #1A3A8A; border: 1px solid #2266CC; }
QCheckBox::indicator:hover { border: 1px solid #2266CC; }

QGroupBox { border: 1px solid #1A2040; border-radius: 4px; margin-top: 8px; padding-top: 4px; color: #7090C0; font-weight: bold; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 8px; padding: 0 4px; color: #2266CC; }

QScrollBar:vertical { background: #070910; width: 10px; border: none; }
QScrollBar::handle:vertical { background: #1A2040; min-height: 20px; border-radius: 5px; }
QScrollBar::handle:vertical:hover { background: #2266CC; }
QScrollBar:horizontal { background: #070910; height: 10px; border: none; }
QScrollBar::handle:horizontal { background: #1A2040; min-width: 20px; border-radius: 5px; }
QScrollBar::handle:horizontal:hover { background: #2266CC; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }

QSplitter::handle { background-color: #1A2040; }
QSplitter::handle:hover { background-color: #2266CC; }

QSlider::groove:horizontal { background: #1A2040; height: 6px; border-radius: 3px; }
QSlider::handle:horizontal { background: #2266CC; width: 14px; height: 14px; margin: -4px 0; border-radius: 7px; border: 1px solid #4499FF; }
QSlider::handle:horizontal:hover { background: #4499FF; }

QProgressBar { background-color: #070910; border: 1px solid #1A2040; border-radius: 4px; text-align: center; color: #C8D8F8; height: 14px; }
QProgressBar::chunk { background-color: #1A3A8A; border-radius: 3px; }

QListWidget, QTreeWidget, QTableWidget { background-color: #0A0E1C; border: 1px solid #1A2040; alternate-background-color: #070910; color: #C8D8F8; gridline-color: #1A2040; selection-background-color: #102060; selection-color: #FFFFFF; }
QHeaderView::section { background-color: #070910; color: #7090C0; border: 1px solid #1A2040; padding: 4px; }

QLabel { color: #AABCDF; background: transparent; }

QMenuBar { background-color: #0D1020; color: #AABCDF; border-bottom: 1px solid #1A2040; }
QMenuBar::item:selected { background-color: #102060; }
QMenu { background-color: #070910; border: 1px solid #1A2040; color: #C8D8F8; }
QMenu::item:selected { background-color: #102060; }
QMenu::separator { height: 1px; background: #1A2040; margin: 2px 6px; }

QToolTip { background-color: #070910; color: #C8D8F8; border: 1px solid #2266CC; padding: 4px; }
QTextEdit, QPlainTextEdit { background-color: #070910; color: #7090C0; border: 1px solid #1A2040; font-family: "Courier New", monospace; }
QDialogButtonBox QPushButton { min-width: 70px; }
"""


# ── Theme: Amber / Dark ───────────────────────────────────────────────────────

_AMBER_DARK = """
QWidget {
    background-color: #0C0800;
    color: #FFD080;
    font-family: Helvetica, Arial, sans-serif;
}
QMainWindow, QDockWidget { background-color: #100A00; }
QDockWidget::title { background-color: #0C0800; color: #CC9900; padding: 4px; border-bottom: 1px solid #2A1A00; }
QDockWidget > QWidget { border: 1px solid #2A1A00; }

QTabWidget::pane { border: 1px solid #2A1A00; background-color: #0C0800; }
QTabBar::tab { background-color: #0C0800; color: #CC9900; border: 1px solid #2A1A00; border-bottom: none; padding: 6px 16px; margin-right: 2px; }
QTabBar::tab:selected { background-color: #0C0800; color: #FFCC00; border-top: 2px solid #CC8800; }
QTabBar::tab:hover:!selected { background-color: #100A00; color: #FFDD88; }

QPushButton { background-color: #0C0800; border: 1px solid #4A2800; padding: 5px 12px; border-radius: 4px; color: #DDAA44; min-height: 22px; }
QPushButton:hover:!disabled { background-color: #100A00; border: 1px solid #CC8800; color: #FFFFFF; }
QPushButton:pressed { background-color: #8A5500; border: 2px solid #FFCC00; color: #000000; padding: 4px 11px; }
QPushButton:checked { background-color: #3A2200; border: 2px solid #CC8800; color: #FFCC44; }
QPushButton:disabled { background-color: #0C0800; color: #3A2A00; border: 1px solid #2A1A00; }

QToolButton { background-color: #0C0800; border: 1px solid #2A1A00; padding: 4px 8px; border-radius: 3px; color: #DDAA44; }
QToolButton:hover { background-color: #100A00; border: 1px solid #CC8800; color: #FFFFFF; }
QToolButton:pressed { background-color: #8A5500; border: 2px solid #FFCC00; color: #000000; }
QToolButton:checked { background-color: #3A2200; border: 2px solid #CC8800; color: #FFCC44; }
QToolButton:disabled { background-color: #0C0800; color: #3A2A00; border: 1px solid #2A1A00; }

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background-color: #080500; border: 1px solid #2A1A00; border-radius: 3px; padding: 1px 4px; min-height: 20px; color: #FFD080; selection-background-color: #4A2800; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border: 1px solid #CC8800; }
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled { color: #3A2A00; }

QSpinBox::up-button, QDoubleSpinBox::up-button { subcontrol-origin: border; subcontrol-position: top right; width: 18px; border-left: 1px solid #2A1A00; border-bottom: 1px solid #2A1A00; background: #080500; }
QSpinBox::down-button, QDoubleSpinBox::down-button { subcontrol-origin: border; subcontrol-position: bottom right; width: 18px; border-left: 1px solid #2A1A00; border-top: 1px solid #2A1A00; background: #080500; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { width: 0; height: 0; border-left: 4px solid transparent; border-right: 4px solid transparent; border-bottom: 5px solid #CC9900; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { width: 0; height: 0; border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 5px solid #CC9900; }

QComboBox::drop-down { width: 22px; border-left: 1px solid #2A1A00; background: #080500; }
QComboBox::down-arrow { width: 0; height: 0; border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 5px solid #CC9900; }
QComboBox QAbstractItemView { background-color: #080500; border: 1px solid #2A1A00; selection-background-color: #3A2200; color: #FFD080; }

QCheckBox { color: #DDAA44; spacing: 6px; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #2A1A00; background-color: #080500; border-radius: 2px; }
QCheckBox::indicator:checked { background-color: #8A5500; border: 1px solid #CC8800; }
QCheckBox::indicator:hover { border: 1px solid #CC8800; }

QGroupBox { border: 1px solid #2A1A00; border-radius: 4px; margin-top: 8px; padding-top: 4px; color: #CC9900; font-weight: bold; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 8px; padding: 0 4px; color: #CC8800; }

QScrollBar:vertical { background: #080500; width: 10px; border: none; }
QScrollBar::handle:vertical { background: #2A1A00; min-height: 20px; border-radius: 5px; }
QScrollBar::handle:vertical:hover { background: #CC8800; }
QScrollBar:horizontal { background: #080500; height: 10px; border: none; }
QScrollBar::handle:horizontal { background: #2A1A00; min-width: 20px; border-radius: 5px; }
QScrollBar::handle:horizontal:hover { background: #CC8800; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }

QSplitter::handle { background-color: #2A1A00; }
QSplitter::handle:hover { background-color: #CC8800; }

QSlider::groove:horizontal { background: #2A1A00; height: 6px; border-radius: 3px; }
QSlider::handle:horizontal { background: #CC8800; width: 14px; height: 14px; margin: -4px 0; border-radius: 7px; border: 1px solid #FFCC00; }

QProgressBar { background-color: #080500; border: 1px solid #2A1A00; border-radius: 4px; text-align: center; color: #FFD080; height: 14px; }
QProgressBar::chunk { background-color: #8A5500; border-radius: 3px; }

QListWidget, QTreeWidget, QTableWidget { background-color: #100800; border: 1px solid #2A1A00; alternate-background-color: #080500; color: #FFD080; gridline-color: #2A1A00; selection-background-color: #3A2200; selection-color: #FFFFFF; }
QHeaderView::section { background-color: #080500; color: #CC9900; border: 1px solid #2A1A00; padding: 4px; }

QLabel { color: #DDAA44; background: transparent; }

QMenuBar { background-color: #100A00; color: #DDAA44; border-bottom: 1px solid #2A1A00; }
QMenuBar::item:selected { background-color: #3A2200; }
QMenu { background-color: #080500; border: 1px solid #2A1A00; color: #FFD080; }
QMenu::item:selected { background-color: #3A2200; }
QMenu::separator { height: 1px; background: #2A1A00; margin: 2px 6px; }

QToolTip { background-color: #080500; color: #FFD080; border: 1px solid #CC8800; padding: 4px; }
QTextEdit, QPlainTextEdit { background-color: #080500; color: #CC9900; border: 1px solid #2A1A00; font-family: "Courier New", monospace; }
QDialogButtonBox QPushButton { min-width: 70px; }
"""


# ── Theme: Light ──────────────────────────────────────────────────────────────

_LIGHT = """
QWidget {
    background-color: #F5F5F5;
    color: #202020;
    font-family: Helvetica, Arial, sans-serif;
}
QMainWindow, QDockWidget { background-color: #ECECEC; }
QDockWidget::title { background-color: #DCDCDC; color: #404040; padding: 4px; border-bottom: 1px solid #AAAAAA; }
QDockWidget > QWidget { border: 1px solid #AAAAAA; }

QTabWidget::pane { border: 1px solid #AAAAAA; background-color: #F5F5F5; }
QTabBar::tab { background-color: #DCDCDC; color: #404040; border: 1px solid #AAAAAA; border-bottom: none; padding: 6px 16px; margin-right: 2px; }
QTabBar::tab:selected { background-color: #F5F5F5; color: #0055CC; border-top: 2px solid #0055CC; }
QTabBar::tab:hover:!selected { background-color: #ECECEC; }

QPushButton { background-color: #E0E0E0; border: 1px solid #AAAAAA; padding: 5px 12px; border-radius: 4px; color: #202020; min-height: 22px; }
QPushButton:hover:!disabled { background-color: #D0D8F0; border: 1px solid #0055CC; color: #0033AA; }
QPushButton:pressed { background-color: #0055CC; border: 2px solid #003399; color: #FFFFFF; padding: 4px 11px; }
QPushButton:checked { background-color: #C0D0F0; border: 2px solid #0055CC; color: #002288; }
QPushButton:disabled { background-color: #E8E8E8; color: #AAAAAA; border: 1px solid #CCCCCC; }

QToolButton { background-color: #E0E0E0; border: 1px solid #CCCCCC; padding: 4px 8px; border-radius: 3px; color: #202020; }
QToolButton:hover { background-color: #D0D8F0; border: 1px solid #0055CC; }
QToolButton:pressed { background-color: #0055CC; border: 2px solid #003399; color: #FFFFFF; }
QToolButton:checked { background-color: #C0D0F0; border: 2px solid #0055CC; color: #002288; }
QToolButton:disabled { background-color: #E8E8E8; color: #AAAAAA; border: 1px solid #CCCCCC; }

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background-color: #FFFFFF; border: 1px solid #AAAAAA; border-radius: 3px; padding: 1px 4px; min-height: 20px; color: #202020; selection-background-color: #C0D0F0; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border: 1px solid #0055CC; }
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled { background-color: #EEEEEE; color: #AAAAAA; }

QComboBox::drop-down { width: 22px; border-left: 1px solid #AAAAAA; background: #E0E0E0; }
QComboBox QAbstractItemView { background-color: #FFFFFF; border: 1px solid #AAAAAA; selection-background-color: #C0D0F0; color: #202020; }

QCheckBox { color: #202020; spacing: 6px; }
QCheckBox::indicator { width: 14px; height: 14px; border: 1px solid #AAAAAA; background-color: #FFFFFF; border-radius: 2px; }
QCheckBox::indicator:checked { background-color: #0055CC; border: 1px solid #003399; }

QGroupBox { border: 1px solid #AAAAAA; border-radius: 4px; margin-top: 8px; padding-top: 4px; color: #404040; font-weight: bold; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 8px; padding: 0 4px; color: #0055CC; }

QScrollBar:vertical { background: #ECECEC; width: 10px; border: none; }
QScrollBar::handle:vertical { background: #CCCCCC; min-height: 20px; border-radius: 5px; }
QScrollBar::handle:vertical:hover { background: #0055CC; }
QScrollBar:horizontal { background: #ECECEC; height: 10px; border: none; }
QScrollBar::handle:horizontal { background: #CCCCCC; min-width: 20px; border-radius: 5px; }
QScrollBar::handle:horizontal:hover { background: #0055CC; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }

QSplitter::handle { background-color: #CCCCCC; }
QSplitter::handle:hover { background-color: #0055CC; }

QSlider::groove:horizontal { background: #CCCCCC; height: 6px; border-radius: 3px; }
QSlider::handle:horizontal { background: #0055CC; width: 14px; height: 14px; margin: -4px 0; border-radius: 7px; border: 1px solid #003399; }

QProgressBar { background-color: #E0E0E0; border: 1px solid #AAAAAA; border-radius: 4px; text-align: center; color: #202020; height: 14px; }
QProgressBar::chunk { background-color: #0055CC; border-radius: 3px; }

QListWidget, QTreeWidget, QTableWidget { background-color: #FFFFFF; border: 1px solid #AAAAAA; alternate-background-color: #F5F5F5; color: #202020; gridline-color: #CCCCCC; selection-background-color: #C0D0F0; selection-color: #000000; }
QHeaderView::section { background-color: #E0E0E0; color: #404040; border: 1px solid #AAAAAA; padding: 4px; }

QLabel { color: #202020; background: transparent; }

QMenuBar { background-color: #ECECEC; color: #202020; border-bottom: 1px solid #AAAAAA; }
QMenuBar::item:selected { background-color: #D0D8F0; }
QMenu { background-color: #FFFFFF; border: 1px solid #AAAAAA; color: #202020; }
QMenu::item:selected { background-color: #C0D0F0; }
QMenu::separator { height: 1px; background: #CCCCCC; margin: 2px 6px; }

QToolTip { background-color: #FFFFCC; color: #202020; border: 1px solid #AAAAAA; padding: 4px; }
QTextEdit, QPlainTextEdit { background-color: #FFFFFF; color: #202020; border: 1px solid #AAAAAA; font-family: "Courier New", monospace; }
QDialogButtonBox QPushButton { min-width: 70px; }
"""


THEMES: Dict[str, str] = {
    "Green / Black": _GREEN_BLACK,
    "Dark Blue": _DARK_BLUE,
    "Amber / Dark": _AMBER_DARK,
    "Light": _LIGHT,
}

_DEFAULT_THEME = "Dark Blue"


def apply_theme(target, name: str) -> None:
    """Apply a named theme stylesheet to *target* (QApplication or any QWidget)."""
    ss = THEMES.get(name, THEMES[_DEFAULT_THEME])
    target.setStyleSheet(ss)
