from __future__ import annotations

import hashlib
import os
import time
from collections import defaultdict

from PySide6.QtCore import QThread, Signal

from models import Asset, HashGroup

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def is_image(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def asset_from_path(path: str, file_hash: str = "", duplicate_count: int = 1) -> Asset | None:
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return Asset(path, os.path.basename(path), stat.st_size, stat.st_mtime, file_hash, duplicate_count)


class ScanWorker(QThread):
    progress = Signal(int, int, str, float)
    asset_found = Signal(object)
    group_found = Signal(object)
    finished = Signal(object)
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
        groups_found = 0
        assets: list[Asset] = []
        groups: list[HashGroup] = []
        try:
            if self.mode == "explore":
                for path in self._walk_images():
                    if self._stop:
                        return
                    asset = asset_from_path(path)
                    scanned += 1
                    if asset:
                        assets.append(asset)
                        self.asset_found.emit(asset)
                    if scanned % 25 == 0:
                        self.progress.emit(scanned, groups_found, path, time.monotonic() - start)
                self.progress.emit(scanned, groups_found, "", time.monotonic() - start)
                self.finished.emit(assets)
                return

            by_size: dict[int, list[str]] = defaultdict(list)
            for path in self._walk_images():
                if self._stop:
                    return
                scanned += 1
                try:
                    by_size[os.path.getsize(path)].append(path)
                except OSError:
                    continue
                if scanned % 50 == 0:
                    candidates = sum(1 for paths in by_size.values() if len(paths) > 1)
                    self.progress.emit(scanned, candidates, path, time.monotonic() - start)

            for same_size in (paths for paths in by_size.values() if len(paths) > 1):
                by_hash: dict[str, list[str]] = defaultdict(list)
                for path in same_size:
                    if self._stop:
                        return
                    try:
                        by_hash[sha256_file(path)].append(path)
                    except OSError:
                        continue
                    self.progress.emit(scanned, groups_found, path, time.monotonic() - start)
                for file_hash, paths in by_hash.items():
                    if len(paths) < 2:
                        continue
                    group_assets = [asset for p in paths if (asset := asset_from_path(p, file_hash, len(paths)))]
                    if len(group_assets) < 2:
                        continue
                    group = HashGroup(file_hash, group_assets)
                    groups.append(group)
                    groups_found += 1
                    self.group_found.emit(group)
                    self.progress.emit(scanned, groups_found, paths[-1], time.monotonic() - start)
            self.progress.emit(scanned, groups_found, "", time.monotonic() - start)
            self.finished.emit(groups)
        except Exception as exc:
            self.failed.emit(str(exc))

    def _walk_images(self):
        for dirpath, dirnames, filenames in os.walk(self.root):
            if self._stop:
                return
            dirnames.sort()
            for filename in sorted(filenames):
                path = os.path.join(dirpath, filename)
                if is_image(path):
                    yield path
