from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDoubleSpinBox, QSpinBox


class _DragMixin:
    """
    Mixin for QAbstractSpinBox subclasses.
    • Ignores scroll-wheel (value only changes via click-drag or arrow keys).
    • Click and drag left/right to decrease/increase value at 4px per step.
    """

    _drag_start_x: int = 0
    _drag_start_val: float = 0.0
    _dragging: bool = False
    _PX_PER_STEP: int = 4

    def wheelEvent(self, event):
        event.ignore()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_start_x = event.position().toPoint().x()
            self._drag_start_val = self.value()
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging and (event.buttons() & Qt.MouseButton.LeftButton):
            dx = event.position().toPoint().x() - self._drag_start_x
            steps = dx / self._PX_PER_STEP
            self.setValue(self._drag_start_val + steps * self.singleStep())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self.unsetCursor()
        super().mouseReleaseEvent(event)


class DragSpinBox(_DragMixin, QSpinBox):
    """QSpinBox with scroll-wheel ignored; click-drag horizontally to change value."""


class DragDoubleSpinBox(_DragMixin, QDoubleSpinBox):
    """QDoubleSpinBox with scroll-wheel ignored; click-drag horizontally to change value."""
