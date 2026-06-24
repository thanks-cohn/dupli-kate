from functools import lru_cache

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage


@lru_cache(maxsize=500)
def load_thumbnail(path: str, size: int) -> QImage:
    image = QImage(path)
    if image.isNull():
        return image
    return image.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
