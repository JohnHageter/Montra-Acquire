from PySide6.QtGui import QImage, QPixmap
import numpy as np


def cv_image_to_qpixmap(frame: np.ndarray) -> QPixmap:
    """Convert a grayscale or BGR numpy frame to a QPixmap.

    QImage can be constructed from a raw buffer pointer, so the numpy array
    must stay alive until QImage.copy() has made a deep copy of the pixels.
    """
    if frame.ndim == 2:
        buf = np.ascontiguousarray(frame)
        h, w = buf.shape
        qimg = QImage(buf.data, w, h, w, QImage.Format.Format_Grayscale8).copy()
    else:
        buf = np.ascontiguousarray(frame[..., ::-1])   # BGR → RGB, contiguous
        h, w, _ = buf.shape
        qimg = QImage(buf.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(qimg)
