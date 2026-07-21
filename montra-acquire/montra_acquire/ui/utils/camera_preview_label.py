from __future__ import annotations

import copy
from typing import List, Optional, Tuple

import cv2
import numpy as np

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import (
    QColor, QFont, QImage, QPainter, QPen, QPixmap, QPolygon,
)
from PySide6.QtWidgets import QLabel

from montra.tracker.roi import ROI, ROIShape

# Distinct colours for up to 8 ROIs
_ROI_COLOURS = [
    QColor(80,  120, 255),   # blue
    QColor(80,  220, 80),    # green
    QColor(255, 160, 40),    # orange
    QColor(220, 60,  220),   # magenta
    QColor(60,  220, 220),   # cyan
    QColor(220, 220, 60),    # yellow
    QColor(220, 80,  80),    # red
    QColor(160, 255, 160),   # light green
]

_HANDLE_SIZE = 8   # px side length of resize handles
_HANDLE_HIT  = 8   # px hit-test radius for handles


class CameraPreviewLabel(QLabel):
    # Watch-window signals
    watch_window_drawn      = Signal(QRect)   # frame-coord rect
    watch_window_draw_state = Signal(str)

    # Tracking ROI signals — carries List[ROI]
    tracking_roi_drawn    = Signal(object)   # single newly-drawn ROI
    tracking_rois_changed = Signal(list)     # full List[ROI] in full-sensor coords

    # Track interaction signals
    track_clicked      = Signal(int)   # track_id when user clicks on a track bbox
    track_deselect     = Signal()      # emitted when user clicks on empty space
    roi_selection_changed = Signal(int)  # selected ROI index (-1 for deselect)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

        self.pixmap: Optional[QPixmap] = None
        self.overlay_rect: Optional[QRect] = None

        # Watch-window draw state
        self.selection_mode: bool          = False
        self.drawing:        bool          = False
        self.start_point:    Optional[QPoint] = None
        self.end_point:      Optional[QPoint] = None
        self.locked_aspect_ratio: Optional[float] = None

        # ROI drawing state
        self._roi_drawing_mode:  bool      = False
        self._roi_shape:         ROIShape  = ROIShape.RECT
        self._roi_square_mode:   bool      = False   # constrain RECT draws to square (w==h)
        self._roi_aspect_ratio:  Optional[float] = None
        self._polygon_pts:       List[QPoint] = []   # label-coord vertices in progress

        # ROI select/edit state
        self._roi_select_mode:   bool          = False
        self._selected_roi_idx:  Optional[int] = None
        self._drag_mode:         Optional[str] = None  # "move" | "handle"
        self._drag_handle_idx:   Optional[int] = None
        self._drag_start_label:  Optional[QPoint] = None
        self._drag_roi_snap:     Optional[ROI] = None  # deep copy at drag start
        self._clipboard_roi:     Optional[ROI] = None

        # Persistent tracking ROIs in full-sensor coordinates
        self._tracking_rois: List[ROI] = []

        # Live track bounding boxes for click-to-select (label coords after conversion)
        self._track_bboxes: List[Tuple[int, int, int, int, int]] = []

        # HUD state
        self._hud_visible:     bool  = False
        self._hud_fps:         float = 0.0
        self._hud_dropped:     int   = 0
        self._hud_disconnects: int   = 0
        self._hud_watch:       str   = ""

        # Exposure overlay state
        self._exposure_overlay: bool                  = False
        self._exp_over_mask:    Optional[np.ndarray]  = None   # uint8 bool mask (H, W)
        self._exp_under_mask:   Optional[np.ndarray]  = None

        # Watch-window coordinate offset — full-sensor origin of the current watch window.
        self._watch_origin: QPoint = QPoint(0, 0)

        # Watch rect visual overlay (full-sensor coords, visual-only — NOT sent to camera)
        self._watch_rect:        Optional[QRect]  = None
        self._watch_drag_handle: Optional[int]    = None  # handle index (0-7) or None=body
        self._watch_drag_start:  Optional[QPoint] = None  # label coord where drag began
        self._watch_drag_snap:   Optional[QRect]  = None  # _watch_rect at drag start

        # Zoom / pan state
        self._zoom: float        = 1.0
        self._pan:  QPoint       = QPoint(0, 0)
        self._pan_start:  Optional[QPoint] = None
        self._pan_origin: QPoint = QPoint(0, 0)

    # ── Public setters ────────────────────────────────────────────────────────

    def setPixmap(self, pixmap: QPixmap) -> None:
        self.pixmap = pixmap
        self.update()

    def set_overlay(self, rect: QRect) -> None:
        self.overlay_rect = rect
        self.update()

    def set_hud_visible(self, visible: bool) -> None:
        self._hud_visible = visible
        self.update()

    def update_hud(self, fps: float, dropped: int, disconnects: int) -> None:
        self._hud_fps         = fps
        self._hud_dropped     = dropped
        self._hud_disconnects = disconnects
        self.update()

    def set_watch_text(self, text: str) -> None:
        self._hud_watch = text
        self.update()

    def set_watch_origin(self, origin: QPoint) -> None:
        """Record the full-sensor offset of the current watch window."""
        self._watch_origin = origin

    def get_watch_rect(self) -> Optional[QRect]:
        return self._watch_rect

    def set_watch_rect(self, rect: Optional[QRect]) -> None:
        """Display a watch-window reference overlay in full-sensor coordinates.

        The rect is shown with handles for interactive move/resize.  It is purely
        visual — no camera command is issued.  Pass None to hide the overlay.
        """
        self._watch_rect = rect if (rect and not rect.isNull()) else None
        self.update()

    def clear_watch_rect(self) -> None:
        """Remove the watch-window overlay and emit watch_window_drawn(QRect())."""
        self._watch_rect = None
        self._watch_drag_handle = None
        self._watch_drag_start  = None
        self._watch_drag_snap   = None
        self.watch_window_drawn.emit(QRect())
        self.update()

    def set_exposure_overlay(self, enabled: bool) -> None:
        self._exposure_overlay = enabled
        if not enabled:
            self._exp_over_mask = self._exp_under_mask = None
        self.update()

    def update_exposure_overlay(self, frame: np.ndarray) -> None:
        """Recompute over/under masks from a BGR or grayscale frame."""
        if not self._exposure_overlay:
            return
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        self._exp_over_mask  = (gray >= 250).astype(np.uint8)
        self._exp_under_mask = (gray <= 5).astype(np.uint8)
        self.update()

    # ── Watch-window drawing ──────────────────────────────────────────────────

    def begin_watch_selection(self, aspect_ratio: Optional[float]) -> None:
        self.selection_mode       = True
        self._roi_drawing_mode    = False
        self._roi_select_mode     = False
        self.locked_aspect_ratio  = aspect_ratio
        self.drawing              = False
        self.start_point          = None
        self.end_point            = None
        self.set_overlay(QRect())
        self.setCursor(Qt.CursorShape.CrossCursor)

    # ── Tracking ROI drawing ──────────────────────────────────────────────────

    def begin_roi_drawing(self) -> None:
        """Enter ROI drawing mode using the current _roi_shape."""
        self.selection_mode    = False
        self._roi_select_mode  = False
        self._roi_drawing_mode = True
        self.drawing           = False
        self.start_point       = None
        self.end_point         = None
        self._polygon_pts      = []
        self.set_overlay(QRect())
        self.setCursor(Qt.CursorShape.CrossCursor)

    def end_drawing_mode(self) -> None:
        """Exit ROI drawing mode and restore the default cursor."""
        self._roi_drawing_mode = False
        self._roi_select_mode  = False
        self.drawing           = False
        self._polygon_pts      = []
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def set_roi_shape(self, shape: ROIShape) -> None:
        self._roi_shape = shape
        if shape != ROIShape.RECT:
            self._roi_square_mode = False

    def set_roi_square(self, enabled: bool) -> None:
        """Constrain the next RECT draw so width == height (square)."""
        self._roi_square_mode = enabled
        if enabled:
            self._roi_shape = ROIShape.RECT

    def set_roi_aspect(self, ratio: Optional[float]) -> None:
        self._roi_aspect_ratio = ratio

    def set_tracking_rois(self, rois: List[ROI]) -> None:
        """Replace displayed ROIs without emitting a signal (used on load)."""
        self._tracking_rois = list(rois)
        self.update()

    def clear_tracking_rois(self) -> None:
        self._tracking_rois = []
        self._selected_roi_idx = None
        self.tracking_rois_changed.emit([])
        self.update()

        self.update()

    def set_selected_roi(self, idx: int) -> None:
        self._selected_roi_idx = idx if 0 <= idx < len(self._tracking_rois) else None
        self.update()

    def _delete_selected(self) -> None:
        if self._selected_roi_idx is not None:
            self._tracking_rois.pop(self._selected_roi_idx)
            for i, r in enumerate(self._tracking_rois):
                r.id = i
            self._selected_roi_idx = None
            self.roi_selection_changed.emit(-1)
            self.tracking_rois_changed.emit(list(self._tracking_rois))
            self.update()

    # ── Mouse events ─────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:
        pos = event.position().toPoint()

        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_start  = pos
            self._pan_origin = QPoint(self._pan)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return

        # ── Polygon drawing: click adds a vertex ─────────────────────────────
        if self._roi_drawing_mode and self._roi_shape == ROIShape.POLYGON:
            self._polygon_pts.append(pos)
            self.end_point = pos
            self.update()
            return

        # ── ROI select mode: check handles then bodies ────────────────────────
        if self._roi_select_mode:
            if self._selected_roi_idx is not None:
                handle = self._hit_test_handles(pos, self._selected_roi_idx)
                if handle is not None:
                    kind, hidx = handle
                    self._drag_mode      = "handle"
                    self._drag_handle_idx = hidx
                    self._drag_start_label = pos
                    self._drag_roi_snap  = copy.deepcopy(self._tracking_rois[self._selected_roi_idx])
                    return

            hit = self._hit_test_roi(pos)
            if hit is not None:
                self._selected_roi_idx = hit
                self._drag_mode        = "move"
                self._drag_start_label = pos
                self._drag_roi_snap    = copy.deepcopy(self._tracking_rois[hit])
                self.roi_selection_changed.emit(hit)
            else:
                self._selected_roi_idx = None
                self._drag_mode        = None
                self.roi_selection_changed.emit(-1)
            self.update()
            return

        # ── Watch rect: handle drag or body move ──────────────────────────────
        if self._watch_rect is not None and not self.selection_mode and not self._roi_drawing_mode:
            handle = self._watch_hit_handle(pos)
            lr = self._watch_rect_label()
            if handle is not None or lr.contains(pos):
                self._watch_drag_handle = handle  # None means body drag
                self._watch_drag_start  = pos
                self._watch_drag_snap   = QRect(self._watch_rect)
                return

        # ── Watch/ROI draw modes ──────────────────────────────────────────────
        if self.selection_mode or self._roi_drawing_mode:
            self.start_point = pos
            self.end_point   = pos
            self.drawing     = True
            if self.selection_mode:
                self.watch_window_draw_state.emit("Drawing")

    def mouseMoveEvent(self, event) -> None:
        pos = event.position().toPoint()

        if event.buttons() & Qt.MouseButton.MiddleButton and self._pan_start is not None:
            delta = pos - self._pan_start
            self._pan = self._pan_origin + delta
            self.update()
            return

        # ── Polygon: update cursor position for the closing-line preview ──────
        if self._roi_drawing_mode and self._roi_shape == ROIShape.POLYGON:
            self.end_point = pos
            self.update()
            return

        # ── Watch rect drag ────────────────────────────────────────────────────
        if self._watch_drag_start is not None and self._watch_drag_snap is not None:
            self._apply_watch_drag(pos)
            self.update()
            return

        # ── ROI drag (move or handle) ─────────────────────────────────────────
        if self._roi_select_mode and self._drag_mode and self._drag_start_label and self._drag_roi_snap:
            delta = pos - self._drag_start_label
            self._apply_drag(delta)
            self.update()
            return

        if not self.drawing or not self.start_point:
            return

        self.end_point = pos
        rect = QRect(self.start_point, pos).normalized()

        if self.selection_mode and self.locked_aspect_ratio:
            rect.setHeight(int(rect.width() / self.locked_aspect_ratio))
        elif self._roi_drawing_mode:
            if self._roi_aspect_ratio:
                rect.setHeight(int(rect.width() / self._roi_aspect_ratio))
            elif self._roi_shape == ROIShape.CIRCLE or self._roi_square_mode:
                rect.setHeight(rect.width())   # inscribed circle or square → square bounding box

        self.overlay_rect = rect
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        pos = event.position().toPoint()

        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_start = None
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return

        # ── Watch rect drag release ───────────────────────────────────────────
        if self._watch_drag_start is not None:
            self._watch_drag_handle = None
            self._watch_drag_start  = None
            self._watch_drag_snap   = None
            if self._watch_rect is not None:
                self.watch_window_drawn.emit(self._watch_rect)
            self.update()
            return

        # ── ROI drag release ──────────────────────────────────────────────────
        if self._roi_select_mode and self._drag_mode:
            self._drag_mode       = None
            self._drag_handle_idx = None
            self._drag_start_label = None
            self._drag_roi_snap   = None
            self.tracking_rois_changed.emit(list(self._tracking_rois))
            self.update()
            return

        # ── Polygon mode: mouse release does nothing (vertex on click) ─────────
        if self._roi_drawing_mode and self._roi_shape == ROIShape.POLYGON:
            return

        # ── Handle non-draw modes ─────────────────────────────────────────────
        if not self.drawing:
            if not self.selection_mode and not self._roi_drawing_mode and not self._roi_select_mode:
                hit = False
                for bx, by, bw, bh, tid in self._track_bboxes:
                    if (bx <= pos.x() <= bx + bw) and (by <= pos.y() <= by + bh):
                        self.track_clicked.emit(tid)
                        hit = True
                        break
                if not hit:
                    self.track_deselect.emit()
            return

        self.drawing = False
        if not (self.start_point and self.end_point):
            return

        rect = QRect(self.start_point, self.end_point).normalized()

        if self.selection_mode:
            if self.locked_aspect_ratio:
                rect.setHeight(int(rect.width() / self.locked_aspect_ratio))
            # Use unclamped corner conversion (no intersected() clamp) so the
            # stored rect reflects exactly where the user drew, not the nearest
            # image boundary.  _label_pt_to_frame_pt converts without clamping.
            frame_rect = self._label_rect_to_frame_rect_unclamped(rect)
            self.selection_mode = False
            self.watch_window_draw_state.emit("Idle")
            self._watch_rect = frame_rect if (frame_rect and not frame_rect.isEmpty()) else None
            self.watch_window_drawn.emit(frame_rect if self._watch_rect else QRect())
            self.set_overlay(QRect())
            self.unsetCursor()

        elif self._roi_drawing_mode:
            # Apply shape-specific constraint
            if self._roi_aspect_ratio:
                rect.setHeight(int(rect.width() / self._roi_aspect_ratio))
            elif self._roi_shape == ROIShape.CIRCLE or self._roi_square_mode:
                rect.setHeight(rect.width())

            if rect.width() > 4 and rect.height() > 4:
                frame_rect = self.label_rect_to_frame_rect(rect)
                n = len(self._tracking_rois)
                # "square" is RECT with equal dimensions, not a distinct shape type
                shape = self._roi_shape if self._roi_shape != ROIShape.CIRCLE else ROIShape.CIRCLE
                new_roi = ROI(
                    id=n, name=f"roi_{n+1}",
                    x=frame_rect.x(), y=frame_rect.y(),
                    w=frame_rect.width(), h=frame_rect.height(),
                    shape=shape,
                )
                self._tracking_rois.append(new_roi)
                self.tracking_roi_drawn.emit(new_roi)
                self.tracking_rois_changed.emit(list(self._tracking_rois))

            self._roi_drawing_mode = False
            self.set_overlay(QRect())
            self.unsetCursor()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            # Polygon: close on double-click (if ≥3 vertices)
            if self._roi_drawing_mode and self._roi_shape == ROIShape.POLYGON:
                # Remove the last point (it was added by the first click of the dbl-click)
                if self._polygon_pts:
                    self._polygon_pts.pop()
                self._finish_polygon()
                return
            # ROI hit-test: select or deselect; exit drawing mode
            pos = event.position().toPoint()
            hit = self._hit_test_roi(pos)
            if hit is not None:
                if self._selected_roi_idx == hit:
                    self._selected_roi_idx = None
                    self.roi_selection_changed.emit(-1)
                else:
                    self._selected_roi_idx = hit
                    self.roi_selection_changed.emit(hit)
                if self._roi_drawing_mode:
                    self.end_drawing_mode()
                self.update()
                return
            # No ROI hit: reset zoom
            self._zoom = 1.0
            self._pan  = QPoint(0, 0)
            self.update()

    def wheelEvent(self, event) -> None:
        if self.pixmap is None:
            return
        factor   = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        old_zoom = self._zoom
        new_zoom = max(1.0, min(self._zoom * factor, 20.0))
        if new_zoom == old_zoom:
            return

        if new_zoom == 1.0:
            self._pan = QPoint(0, 0)
        else:
            cursor = event.position().toPoint()
            dw, dh, ox, oy = self._img_params()
            if dw > 0 and dh > 0:
                fx = (cursor.x() - ox) / dw
                fy = (cursor.y() - oy) / dh
            else:
                fx, fy = 0.5, 0.5

            pw, ph = self.pixmap.width(), self.pixmap.height()
            ww, wh = self.width(), self.height()
            scale = min(ww / pw, wh / ph) if pw > 0 and ph > 0 else 1.0
            fit_w = int(pw * scale)
            fit_h = int(ph * scale)
            new_dw = int(fit_w * new_zoom)
            new_dh = int(fit_h * new_zoom)
            new_ox = cursor.x() - fx * new_dw
            new_oy = cursor.y() - fy * new_dh
            self._pan = QPoint(
                int(new_ox - (ww - new_dw) // 2),
                int(new_oy - (wh - new_dh) // 2),
            )

        self._zoom = new_zoom
        self.update()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        mod = event.modifiers()

        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._delete_selected()

        elif key == Qt.Key.Key_Escape:
            if self._polygon_pts:
                self._polygon_pts = []
                self._roi_drawing_mode = False
                self.unsetCursor()
            self._selected_roi_idx = None
            self.update()

        elif key == Qt.Key.Key_C and (mod & Qt.KeyboardModifier.ControlModifier):
            if self._selected_roi_idx is not None:
                self._clipboard_roi = copy.deepcopy(self._tracking_rois[self._selected_roi_idx])

        elif key == Qt.Key.Key_V and (mod & Qt.KeyboardModifier.ControlModifier):
            if self._clipboard_roi is not None:
                pasted = copy.deepcopy(self._clipboard_roi)
                pasted.id   = len(self._tracking_rois)
                pasted.name = f"roi_{pasted.id + 1}"
                pasted.x   += 20
                pasted.y   += 20
                if pasted.polygon:
                    pasted.polygon = [(px + 20, py + 20) for px, py in pasted.polygon]
                self._tracking_rois.append(pasted)
                self._selected_roi_idx = len(self._tracking_rois) - 1
                self.tracking_rois_changed.emit(list(self._tracking_rois))
                self.update()

        else:
            super().keyPressEvent(event)

    # ── Polygon helper ────────────────────────────────────────────────────────

    def _finish_polygon(self) -> None:
        """Close the in-progress polygon and add it as a new ROI."""
        if len(self._polygon_pts) < 3:
            self._polygon_pts = []
            self._roi_drawing_mode = False
            self.unsetCursor()
            self.update()
            return

        # Convert label-coord vertices to full-sensor frame coords
        verts: List[Tuple[int, int]] = []
        for lp in self._polygon_pts:
            fr = self.label_rect_to_frame_rect(QRect(lp, lp + QPoint(1, 1)))
            verts.append((fr.x(), fr.y()))

        n = len(self._tracking_rois)
        new_roi = ROI.from_polygon(roi_id=n, name=f"roi_{n+1}", polygon=verts)
        self._tracking_rois.append(new_roi)
        self.tracking_roi_drawn.emit(new_roi)
        self.tracking_rois_changed.emit(list(self._tracking_rois))

        self._polygon_pts = []
        self._roi_drawing_mode = False
        self.unsetCursor()
        self.update()

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        hud_anchor_x, hud_anchor_y = 0, 0

        if self.pixmap and self.pixmap.width() > 0:
            dw, dh, ox, oy = self._img_params()
            if dw > 0 and dh > 0:
                dest_x = max(0, ox)
                dest_y = max(0, oy)
                dest_r = min(self.width(),  ox + dw)
                dest_b = min(self.height(), oy + dh)
                dest_w = dest_r - dest_x
                dest_h = dest_b - dest_y
                if dest_w > 0 and dest_h > 0:
                    pw = self.pixmap.width()
                    ph = self.pixmap.height()
                    sx = pw / dw
                    sy = ph / dh
                    src = QRect(
                        int((dest_x - ox) * sx),
                        int((dest_y - oy) * sy),
                        int(dest_w * sx),
                        int(dest_h * sy),
                    )
                    painter.drawPixmap(QRect(dest_x, dest_y, dest_w, dest_h),
                                       self.pixmap, src)

            hud_anchor_x = max(0, ox)
            hud_anchor_y = max(0, oy)

        # ── Tracking ROI overlay ──────────────────────────────────────────────
        if self._tracking_rois and self.pixmap and self.pixmap.width() > 0:
            font = QFont("Helvetica", 8)
            painter.setFont(font)
            fm = painter.fontMetrics()

            for i, r in enumerate(self._tracking_rois):
                colour = _ROI_COLOURS[i % len(_ROI_COLOURS)]
                selected = (i == self._selected_roi_idx)
                pen = QPen(colour, 2,
                           Qt.PenStyle.DashLine if selected else Qt.PenStyle.SolidLine)
                painter.setPen(pen)

                # pixmap-relative bounding box
                pixmap_rect = QRect(
                    r.x - self._watch_origin.x(),
                    r.y - self._watch_origin.y(),
                    r.w, r.h,
                )
                label_rect = self._frame_rect_to_label_rect(pixmap_rect)

                if r.shape == ROIShape.CIRCLE:
                    painter.drawEllipse(label_rect)
                elif r.shape == ROIShape.POLYGON and r.polygon:
                    pts = QPolygon([
                        self._sensor_pt_to_label_pt(px, py)
                        for px, py in r.polygon
                    ])
                    painter.drawPolygon(pts)
                else:
                    painter.drawRect(label_rect)

                painter.setPen(colour)
                painter.drawText(
                    label_rect.x() + 3,
                    label_rect.y() + fm.ascent() + 2,
                    r.name,
                )

            # Draw resize handles for selected ROI
            if self._roi_select_mode and self._selected_roi_idx is not None:
                idx = self._selected_roi_idx
                if idx < len(self._tracking_rois):
                    self._paint_handles(painter, self._tracking_rois[idx])

        # ── In-progress polygon overlay ───────────────────────────────────────
        if self._roi_drawing_mode and self._roi_shape == ROIShape.POLYGON and self._polygon_pts:
            painter.setPen(QPen(QColor(255, 140, 0), 1, Qt.PenStyle.DashLine))
            for j in range(len(self._polygon_pts) - 1):
                painter.drawLine(self._polygon_pts[j], self._polygon_pts[j + 1])
            # Line from last vertex to cursor
            if self.end_point:
                painter.drawLine(self._polygon_pts[-1], self.end_point)
            # Closing line from cursor to first vertex (ghost)
            if self.end_point and len(self._polygon_pts) >= 2:
                painter.setPen(QPen(QColor(255, 140, 0, 100), 1, Qt.PenStyle.DotLine))
                painter.drawLine(self.end_point, self._polygon_pts[0])
            # Draw vertex dots
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 140, 0))
            for pt in self._polygon_pts:
                painter.drawEllipse(pt, 3, 3)
            painter.setBrush(Qt.BrushStyle.NoBrush)

        # ── Exposure overlay ──────────────────────────────────────────────────
        if (self._exposure_overlay
                and self.pixmap and self.pixmap.width() > 0
                and (self._exp_over_mask is not None or self._exp_under_mask is not None)):
            dw, dh, ox, oy = self._img_params()
            if dw > 0 and dh > 0:
                for mask, r, g, b, a in (
                    (self._exp_over_mask,  220, 30, 30, 140),   # red — overexposed
                    (self._exp_under_mask, 30, 80, 220, 140),   # blue — underexposed
                ):
                    if mask is None:
                        continue
                    disp = cv2.resize(mask, (dw, dh), interpolation=cv2.INTER_NEAREST)
                    rgba = np.zeros((dh, dw, 4), dtype=np.uint8)
                    rgba[disp > 0] = [r, g, b, a]
                    qi = QImage(
                        rgba.data, dw, dh, dw * 4,
                        QImage.Format.Format_RGBA8888,
                    )
                    painter.drawImage(QPoint(ox, oy), qi)

        # ── HUD overlay ───────────────────────────────────────────────────────
        if self._hud_visible:
            font = QFont("Courier New", 9)
            painter.setFont(font)
            fm = painter.fontMetrics()

            lines = [
                f"FPS  {self._hud_fps:5.1f}",
                f"DROP {self._hud_dropped}",
                f"DISC {self._hud_disconnects}",
                f"WW   {self._hud_watch}" if self._hud_watch else "WW   full sensor",
            ]

            max_w  = max(fm.horizontalAdvance(line) for line in lines)
            line_h = fm.height()
            pad    = 6
            hud_w  = max_w + pad * 2
            hud_h  = line_h * len(lines) + pad * 2
            margin = 10

            painter.fillRect(
                QRect(hud_anchor_x + margin, hud_anchor_y + margin, hud_w, hud_h),
                QColor(0, 0, 0, 170),
            )
            painter.setPen(QColor(0, 230, 0))
            for i, line in enumerate(lines):
                y = hud_anchor_y + margin + pad + fm.ascent() + line_h * i
                painter.drawText(hud_anchor_x + margin + pad, y, line)

        # ── Watch-window / ROI draw selection ─────────────────────────────────
        if self.overlay_rect is not None and not self.overlay_rect.isNull():
            colour = QColor(255, 140, 0) if self._roi_drawing_mode else QColor(0, 255, 0)
            pen = QPen(colour, 2, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            if self._roi_drawing_mode and self._roi_shape == ROIShape.CIRCLE:
                painter.drawEllipse(self.overlay_rect)
            else:
                painter.drawRect(self.overlay_rect)

        # ── Watch rect visual overlay with resize handles ─────────────────────
        if self._watch_rect is not None and not self._watch_rect.isNull() and self.pixmap:
            lr = self._watch_rect_label()
            if not lr.isNull():
                painter.setPen(QPen(QColor(0, 255, 80), 2, Qt.PenStyle.SolidLine))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(lr)
                # Draw 8 resize handles
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(0, 230, 80))
                for hpt in self._watch_handle_pts(lr):
                    painter.drawRect(hpt.x() - 4, hpt.y() - 4, 8, 8)

        painter.end()

    # ── Handle painting ───────────────────────────────────────────────────────

    def _paint_handles(self, painter: QPainter, r: ROI) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 200))
        hs = _HANDLE_SIZE

        pixmap_rect = QRect(
            r.x - self._watch_origin.x(),
            r.y - self._watch_origin.y(),
            r.w, r.h,
        )
        lr = self._frame_rect_to_label_rect(pixmap_rect)

        if r.shape == ROIShape.POLYGON and r.polygon:
            for px, py in r.polygon:
                lp = self._sensor_pt_to_label_pt(px, py)
                painter.drawRect(lp.x() - hs//2, lp.y() - hs//2, hs, hs)
        elif r.shape == ROIShape.CIRCLE:
            # Center handle
            cx = lr.x() + lr.width()  // 2
            cy = lr.y() + lr.height() // 2
            painter.drawRect(cx - hs//2, cy - hs//2, hs, hs)
            # Radius handle on right edge
            rx = lr.x() + lr.width()
            painter.drawRect(rx - hs//2, cy - hs//2, hs, hs)
        else:
            # 8 handles: 4 corners + 4 edge midpoints
            pts = self._rect_handle_points(lr)
            for pt in pts:
                painter.drawRect(pt.x() - hs//2, pt.y() - hs//2, hs, hs)

        painter.setBrush(Qt.BrushStyle.NoBrush)

    @staticmethod
    def _rect_handle_points(lr: QRect) -> List[QPoint]:
        """8 handle points for a rectangle (corners + edge midpoints)."""
        x0, y0 = lr.x(), lr.y()
        x1, y1 = lr.right(), lr.bottom()
        mx, my = (x0 + x1) // 2, (y0 + y1) // 2
        return [
            QPoint(x0, y0), QPoint(mx, y0), QPoint(x1, y0),
            QPoint(x1, my),
            QPoint(x1, y1), QPoint(mx, y1), QPoint(x0, y1),
            QPoint(x0, my),
        ]

    # ── Hit-testing ───────────────────────────────────────────────────────────

    def _hit_test_roi(self, label_pos: QPoint) -> Optional[int]:
        """Return topmost ROI index whose painted area contains label_pos, or None."""
        for i in range(len(self._tracking_rois) - 1, -1, -1):
            r = self._tracking_rois[i]
            pixmap_rect = QRect(
                r.x - self._watch_origin.x(),
                r.y - self._watch_origin.y(),
                r.w, r.h,
            )
            lr = self._frame_rect_to_label_rect(pixmap_rect)
            if r.shape == ROIShape.POLYGON and r.polygon:
                pts = QPolygon([
                    self._sensor_pt_to_label_pt(px, py) for px, py in r.polygon
                ])
                if pts.containsPoint(label_pos, Qt.FillRule.OddEvenFill):
                    return i
            elif lr.contains(label_pos):
                return i
        return None

    def _hit_test_handles(
        self, label_pos: QPoint, idx: int
    ) -> Optional[Tuple[str, int]]:
        """Return (kind, handle_index) if label_pos is on a resize handle, else None."""
        r = self._tracking_rois[idx]
        pixmap_rect = QRect(
            r.x - self._watch_origin.x(),
            r.y - self._watch_origin.y(),
            r.w, r.h,
        )
        lr = self._frame_rect_to_label_rect(pixmap_rect)

        def near(pt: QPoint) -> bool:
            return (abs(label_pos.x() - pt.x()) <= _HANDLE_HIT and
                    abs(label_pos.y() - pt.y()) <= _HANDLE_HIT)

        if r.shape == ROIShape.POLYGON and r.polygon:
            for vi, (px, py) in enumerate(r.polygon):
                if near(self._sensor_pt_to_label_pt(px, py)):
                    return ("vertex", vi)
        elif r.shape == ROIShape.CIRCLE:
            cx = lr.x() + lr.width()  // 2
            cy = lr.y() + lr.height() // 2
            if near(QPoint(cx, cy)):
                return ("center", 0)
            if near(QPoint(lr.x() + lr.width(), cy)):
                return ("radius", 0)
        else:
            for hi, pt in enumerate(self._rect_handle_points(lr)):
                if near(pt):
                    return ("corner", hi)
        return None

    # ── Drag application ──────────────────────────────────────────────────────

    def _apply_drag(self, delta: QPoint) -> None:
        if self._selected_roi_idx is None or self._drag_roi_snap is None:
            return
        r     = self._tracking_rois[self._selected_roi_idx]
        snap  = self._drag_roi_snap
        # Convert delta (label pixels) to sensor pixels via scale factor
        dw, dh, _, _ = self._img_params()
        if not self.pixmap or dw == 0 or dh == 0:
            return
        sx = self.pixmap.width()  / dw
        sy = self.pixmap.height() / dh
        dx = int(delta.x() * sx)
        dy = int(delta.y() * sy)

        if self._drag_mode == "move":
            r.x = snap.x + dx
            r.y = snap.y + dy
            if r.polygon:
                r.polygon = [(snap.polygon[i][0] + dx, snap.polygon[i][1] + dy)
                             for i in range(len(snap.polygon))]

        elif self._drag_mode == "handle":
            hidx = self._drag_handle_idx
            if r.shape == ROIShape.POLYGON and r.polygon and hidx is not None:
                vx, vy = snap.polygon[hidx]
                r.polygon = list(snap.polygon)
                r.polygon[hidx] = (vx + dx, vy + dy)
                # Recompute bounding box
                xs = [p[0] for p in r.polygon]
                ys = [p[1] for p in r.polygon]
                r.x, r.y = min(xs), min(ys)
                r.w, r.h = max(xs) - r.x, max(ys) - r.y

            elif r.shape == ROIShape.CIRCLE:
                if hidx == 0:  # center
                    r.x = snap.x + dx
                    r.y = snap.y + dy
                else:  # radius edge
                    new_w = max(10, snap.w + dx * 2)
                    r.x = snap.x + (snap.w - new_w) // 2
                    r.y = snap.y + (snap.w - new_w) // 2
                    r.w = r.h = new_w

            else:
                # Corner/edge handle drag for RECT
                # Handle indices follow _rect_handle_points order:
                # 0=TL, 1=TM, 2=TR, 3=MR, 4=BR, 5=BM, 6=BL, 7=ML
                x0, y0 = snap.x, snap.y
                x1, y1 = snap.x + snap.w, snap.y + snap.h
                if hidx in (0, 6, 7):   x0 = snap.x + dx
                if hidx in (2, 3, 4):   x1 = snap.x + snap.w + dx
                if hidx in (0, 1, 2):   y0 = snap.y + dy
                if hidx in (4, 5, 6):   y1 = snap.y + snap.h + dy
                if x1 > x0 + 4 and y1 > y0 + 4:
                    r.x, r.y = x0, y0
                    r.w, r.h = x1 - x0, y1 - y0

    # ── Coordinate helpers ────────────────────────────────────────────────────

    def _label_rect_to_frame_rect_unclamped(self, rect: QRect) -> QRect:
        """Convert a label rect to full-sensor coords WITHOUT clamping to image bounds.

        Unlike label_rect_to_frame_rect (which intersects with the image area first),
        this converts corners directly so the result preserves the drawn position even
        when the rubber-band starts in the letterbox area.
        """
        if not self.pixmap:
            return QRect()
        dw, dh, ox, oy = self._img_params()
        if dw == 0 or dh == 0:
            return QRect()
        sx = self.pixmap.width()  / dw
        sy = self.pixmap.height() / dh
        return QRect(
            int((rect.x()      - ox) * sx) + self._watch_origin.x(),
            int((rect.y()      - oy) * sy) + self._watch_origin.y(),
            int(rect.width()         * sx),
            int(rect.height()        * sy),
        )

    def _img_params(self) -> Tuple[int, int, int, int]:
        """Return (display_w, display_h, origin_x, origin_y) for current zoom/pan."""
        if not self.pixmap:
            return 0, 0, 0, 0
        pw, ph = self.pixmap.width(), self.pixmap.height()
        if pw == 0 or ph == 0:
            return 0, 0, 0, 0
        ww, wh = self.width(), self.height()
        scale = min(ww / pw, wh / ph)
        fit_w = int(pw * scale)
        fit_h = int(ph * scale)
        dw = int(fit_w * self._zoom)
        dh = int(fit_h * self._zoom)
        ox = (ww - dw) // 2 + self._pan.x()
        oy = (wh - dh) // 2 + self._pan.y()
        return dw, dh, ox, oy

    def label_rect_to_frame_rect(self, rect: QRect) -> QRect:
        """Convert a label (widget) rectangle to full-sensor pixel coordinates."""
        if not self.pixmap:
            return QRect()
        dw, dh, ox, oy = self._img_params()
        if dw == 0 or dh == 0:
            return QRect()
        clamped = rect.intersected(QRect(ox, oy, dw, dh))
        pw = self.pixmap.width()
        ph = self.pixmap.height()
        sx = pw / dw
        sy = ph / dh
        return QRect(
            int((clamped.x() - ox) * sx) + self._watch_origin.x(),
            int((clamped.y() - oy) * sy) + self._watch_origin.y(),
            int(clamped.width()  * sx),
            int(clamped.height() * sy),
        )

    def _frame_rect_to_label_rect(self, rect: QRect) -> QRect:
        """Convert a pixmap (watch-window-relative) rectangle to label coordinates."""
        if not self.pixmap:
            return QRect()
        dw, dh, ox, oy = self._img_params()
        if dw == 0 or dh == 0:
            return QRect()
        pw = self.pixmap.width()
        ph = self.pixmap.height()
        sx = dw / pw
        sy = dh / ph
        return QRect(
            int(rect.x() * sx) + ox,
            int(rect.y() * sy) + oy,
            int(rect.width()  * sx),
            int(rect.height() * sy),
        )

    def _sensor_pt_to_label_pt(self, sensor_x: int, sensor_y: int) -> QPoint:
        """Convert full-sensor pixel coordinates to label (widget) coordinates."""
        pixmap_x = sensor_x - self._watch_origin.x()
        pixmap_y = sensor_y - self._watch_origin.y()
        lr = self._frame_rect_to_label_rect(QRect(pixmap_x, pixmap_y, 1, 1))
        return lr.topLeft()

    # ── Watch rect helpers ────────────────────────────────────────────────────

    def _watch_rect_label(self) -> QRect:
        """Return _watch_rect converted to label (widget) coordinates."""
        if self._watch_rect is None or self._watch_rect.isNull() or not self.pixmap:
            return QRect()
        pixmap_rect = QRect(
            self._watch_rect.x() - self._watch_origin.x(),
            self._watch_rect.y() - self._watch_origin.y(),
            self._watch_rect.width(), self._watch_rect.height(),
        )
        return self._frame_rect_to_label_rect(pixmap_rect)

    def _watch_handle_pts(self, lr: QRect) -> List[QPoint]:
        """8 handle positions (TL TC TR ML MR BL BC BR) for a label rect."""
        cx = lr.center().x()
        cy = lr.center().y()
        return [
            lr.topLeft(),                    QPoint(cx, lr.top()),    lr.topRight(),
            QPoint(lr.left(), cy),                                     QPoint(lr.right(), cy),
            lr.bottomLeft(),                 QPoint(cx, lr.bottom()), lr.bottomRight(),
        ]

    def _watch_hit_handle(self, pos: QPoint) -> Optional[int]:
        """Return handle index (0-7) if pos is within hit radius, else None."""
        lr = self._watch_rect_label()
        if lr.isNull():
            return None
        for i, hpt in enumerate(self._watch_handle_pts(lr)):
            if abs(pos.x() - hpt.x()) <= 8 and abs(pos.y() - hpt.y()) <= 8:
                return i
        return None

    def _apply_watch_drag(self, pos: QPoint) -> None:
        """Update _watch_rect based on current drag position."""
        if self._watch_drag_snap is None or self._watch_drag_start is None:
            return
        dw, dh, _, _ = self._img_params()
        if not self.pixmap or dw == 0 or dh == 0:
            return
        # Scale label-pixel delta to full-sensor pixel delta
        sx = self.pixmap.width()  / dw
        sy = self.pixmap.height() / dh
        delta = pos - self._watch_drag_start
        dx = int(delta.x() * sx)
        dy = int(delta.y() * sy)

        snap = self._watch_drag_snap
        x0, y0, w0, h0 = snap.x(), snap.y(), snap.width(), snap.height()

        h = self._watch_drag_handle
        if h is None:
            # Body drag — move
            self._watch_rect = QRect(x0 + dx, y0 + dy, w0, h0)
        else:
            # Handle drag — resize; handle order: TL=0 TC=1 TR=2 ML=3 MR=4 BL=5 BC=6 BR=7
            left, top, right, bot = x0, y0, x0 + w0, y0 + h0
            if h in (0, 3, 5):   left  = min(x0 + dx, right - 4)
            if h in (2, 4, 7):   right = max(x0 + w0 + dx, left + 4)
            if h in (0, 1, 2):   top   = min(y0 + dy, bot  - 4)
            if h in (5, 6, 7):   bot   = max(y0 + h0 + dy, top  + 4)
            self._watch_rect = QRect(left, top, right - left, bot - top)

