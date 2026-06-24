import hashlib
import os
import time
from collections import defaultdict

from PySide6.QtCore import QThread, Signal

from models import Asset

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def is_image(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def asset_from_path(path: str, file_hash: str = "", duplicate_count: int = 1) -> Asset | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return Asset(file_hash, path, os.path.basename(path), st.st_size, st.st_mtime, duplicate_count)


class ScanWorker(QThread):
    progress = Signal(int, int, str, float)
    finished = Signal(list)
    failed = Signal(str)

    def __init__(self, root: str, mode: str):
        super().__init__()
        self.root = root
        self.mode = mode
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        start = time.monotonic()
        scanned = 0
        groups = 0
        try:
            if self.mode == "explore":
                assets = []
                for path in self._walk_images():
                    if self._stop:
                        return
                    asset = asset_from_path(path)
                    if asset:
                        assets.append(asset)
                    scanned += 1
                    if scanned % 100 == 0:
                        self.progress.emit(scanned, groups, path, time.monotonic() - start)
                self.progress.emit(scanned, groups, "", time.monotonic() - start)
                self.finished.emit(assets)
                return

            by_size = defaultdict(list)
            for path in self._walk_images():
                if self._stop:
                    return
                try:
                    by_size[os.path.getsize(path)].append(path)
                except OSError:
                    pass
                scanned += 1
                if scanned % 100 == 0:
                    candidates = sum(1 for v in by_size.values() if len(v) > 1)
                    self.progress.emit(scanned, candidates, path, time.monotonic() - start)

            by_hash = defaultdict(list)
            for paths in (v for v in by_size.values() if len(v) > 1):
                for path in paths:
                    if self._stop:
                        return
                    try:
                        by_hash[sha256_file(path)].append(path)
                    except OSError:
                        continue
                    self.progress.emit(scanned, groups, path, time.monotonic() - start)

            assets = []
            for file_hash, paths in by_hash.items():
                if len(paths) < 2:
                    continue
                groups += 1
                count = len(paths)
                for path in paths:
                    asset = asset_from_path(path, file_hash, count)
                    if asset:
                        assets.append(asset)
            self.progress.emit(scanned, groups, "", time.monotonic() - start)
            self.finished.emit(assets)
        except Exception as exc:
            self.failed.emit(str(exc))

    def _walk_images(self):
        for dirpath, _, filenames in os.walk(self.root):
            for name in filenames:
                path = os.path.join(dirpath, name)
                if is_image(path):
                    yield path
