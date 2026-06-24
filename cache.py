from __future__ import annotations

from collections import OrderedDict
from threading import RLock

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage


class ThumbnailCache:
    def __init__(self, max_items: int = 500):
        self.max_items = max_items
        self._items: OrderedDict[tuple[str, int], QImage] = OrderedDict()
        self._lock = RLock()

    def get(self, path: str, size: int) -> QImage:
        key = (path, size)
        with self._lock:
            image = self._items.get(key)
            if image is not None:
                self._items.move_to_end(key)
                return image
        image = QImage(path)
        if not image.isNull():
            image = image.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        with self._lock:
            self._items[key] = image
            self._items.move_to_end(key)
            while len(self._items) > self.max_items:
                self._items.popitem(last=False)
        return image


thumbnail_cache = ThumbnailCache(500)
