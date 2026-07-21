from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np


class ROIShape(str, Enum):
    RECT = "rect"
    CIRCLE = "circle"
    POLYGON = "polygon"


@dataclass
class ROI:
    """Rectangular, circular, or polygonal region of interest in full-frame pixel coords.

    For all shapes the bounding box (x, y, w, h) is always populated — it is the
    axis-aligned bounding box of the polygon for POLYGON shape.
    """

    id: int
    name: str
    x: int
    y: int
    w: int
    h: int
    shape: ROIShape = ROIShape.RECT
    polygon: Optional[List[Tuple[int, int]]] = None
    static_mask_zones: List[List[Tuple[int, int]]] = field(default_factory=list)

    def crop(self, frame: np.ndarray) -> np.ndarray:
        return frame[self.y : self.y + self.h, self.x : self.x + self.w]

    def crop_with_mask(self, frame: np.ndarray) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        """Return (crop, mask). Mask is None for RECT, binary uint8 for CIRCLE/POLYGON."""
        crop = self.crop(frame)
        if self.shape == ROIShape.CIRCLE:
            mask = np.zeros(crop.shape[:2], dtype=np.uint8)
            cx, cy = self.w // 2, self.h // 2
            r = min(self.w, self.h) // 2
            cv2.circle(mask, (cx, cy), r, 255, -1)
            return crop, mask
        if self.shape == ROIShape.POLYGON and self.polygon:
            mask = np.zeros(crop.shape[:2], dtype=np.uint8)
            pts = np.array(
                [(px - self.x, py - self.y) for px, py in self.polygon],
                dtype=np.int32,
            )
            cv2.fillPoly(mask, [pts], 255)
            return crop, mask
        return crop, None

    @classmethod
    def from_polygon(cls, roi_id: int, name: str,
                     polygon: List[Tuple[int, int]]) -> "ROI":
        """Construct an ROI from a polygon; bounding box is computed automatically."""
        xs = [p[0] for p in polygon]
        ys = [p[1] for p in polygon]
        x, y = min(xs), min(ys)
        w, h = max(xs) - x, max(ys) - y
        return cls(id=roi_id, name=name, x=x, y=y, w=max(w, 1), h=max(h, 1),
                   shape=ROIShape.POLYGON, polygon=polygon)

    def get_static_mask(self, h: int, w: int) -> Optional[np.ndarray]:
        """Return a binary uint8 mask (255=detect, 0=suppress) in ROI-local pixel coords.
        Returns None if no static mask zones are defined."""
        if not self.static_mask_zones:
            return None
        mask = np.ones((h, w), dtype=np.uint8) * 255
        for zone in self.static_mask_zones:
            if len(zone) < 3:
                continue
            pts = np.array(
                [(int(px) - self.x, int(py) - self.y) for px, py in zone],
                dtype=np.int32,
            )
            cv2.fillPoly(mask, [pts], 0)
        return mask

    def to_dict(self) -> dict:
        d = asdict(self)
        shape = self.shape
        d["shape"] = shape.value if isinstance(shape, ROIShape) else str(shape)
        return d


class ROIManager:
    """Owns a collection of ROIs and provides crop/save/load operations."""

    def __init__(self, rois: List[ROI]):
        if not rois:
            raise ValueError("ROIManager requires at least one ROI.")
        self.rois = rois

    @classmethod
    def from_full_frame(cls, frame: np.ndarray) -> "ROIManager":
        """Create a single ROI covering the entire frame."""
        h, w = frame.shape[:2]
        return cls([ROI(id=0, name="full_frame", x=0, y=0, w=w, h=h)])

    @classmethod
    def interactive_select(cls, frame: np.ndarray) -> "ROIManager":
        """
        Let the user draw rectangular ROIs with a mouse.

        Controls shown in the window:
          Left-drag  : draw a rectangle
          Enter      : confirm current rectangle and start another
          Backspace  : delete last confirmed rectangle
          F          : use the full frame as a single ROI (skips drawing)
          Escape / Q : finish and return all confirmed rectangles
        """
        rois: List[ROI] = []
        state = {"drawing": False, "start": None, "current": None, "confirmed": []}

        display = (
            cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR) if frame.ndim == 2 else frame.copy()
        )

        instructions = [
            "Left-drag: draw ROI",
            "Enter: confirm",
            "Backspace: delete last",
            "F: full frame",
            "Esc/Q: done",
        ]

        def _redraw():
            img = display.copy()
            for idx, r in enumerate(state["confirmed"]):
                cv2.rectangle(
                    img, (r[0], r[1]), (r[0] + r[2], r[1] + r[3]), (0, 200, 0), 2
                )
                cv2.putText(
                    img,
                    f"ROI {idx}",
                    (r[0] + 4, r[1] + 16),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 255, 0),
                    1,
                )
            if state["current"] is not None:
                x0, y0, x1, y1 = state["current"]
                cv2.rectangle(img, (x0, y0), (x1, y1), (0, 150, 255), 1)
            for i, txt in enumerate(instructions):
                cv2.putText(
                    img,
                    txt,
                    (8, 18 + i * 18),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    (200, 200, 0),
                    1,
                )
            cv2.imshow("Select ROIs", img)

        def _on_mouse(event, x, y, _flags, _param):
            if event == cv2.EVENT_LBUTTONDOWN:
                state["drawing"] = True
                state["start"] = (x, y)
                state["current"] = (x, y, x, y)
            elif event == cv2.EVENT_MOUSEMOVE and state["drawing"]:
                sx, sy = state["start"]
                state["current"] = (min(sx, x), min(sy, y), max(sx, x), max(sy, y))
                _redraw()
            elif event == cv2.EVENT_LBUTTONUP:
                state["drawing"] = False
                if state["current"] is not None:
                    x0, y0, x1, y1 = state["current"]
                    if (x1 - x0) > 4 and (y1 - y0) > 4:
                        state["confirmed"].append((x0, y0, x1 - x0, y1 - y0))
                    state["current"] = None
                _redraw()

        cv2.namedWindow("Select ROIs", cv2.WINDOW_NORMAL)
        cv2.setMouseCallback("Select ROIs", _on_mouse)
        _redraw()

        while True:
            key = cv2.waitKey(20) & 0xFF
            if key in (27, ord("q")):  # Esc or Q
                break
            if key == 13:  # Enter — confirm current rect (already appended on mouse-up)
                _redraw()
            if key == 8 and state["confirmed"]:  # Backspace
                state["confirmed"].pop()
                _redraw()
            if key == ord("f"):  # Full frame
                h, w = frame.shape[:2]
                state["confirmed"] = [(0, 0, w, h)]
                _redraw()
                break

        cv2.destroyWindow("Select ROIs")

        if not state["confirmed"]:
            print("[ROI] No ROIs drawn — defaulting to full frame.")
            h, w = frame.shape[:2]
            state["confirmed"] = [(0, 0, w, h)]

        rois = [
            ROI(id=i, name=f"roi_{i}", x=x, y=y, w=w, h=h)
            for i, (x, y, w, h) in enumerate(state["confirmed"])
        ]
        return cls(rois)

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump([r.to_dict() for r in self.rois], f, indent=2)
        print(f"[ROI] Saved {len(self.rois)} ROI(s) to {path}")

    @classmethod
    def load(cls, path: Path) -> "ROIManager":
        with open(path) as f:
            data = json.load(f)
        rois = []
        for d in data:
            if "shape" in d:
                d["shape"] = ROIShape(d["shape"])
            rois.append(ROI(**d))
        print(f"[ROI] Loaded {len(rois)} ROI(s) from {path}")
        return cls(rois)
