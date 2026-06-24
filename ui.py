from __future__ import annotations

import math
import os
import subprocess
from datetime import datetime

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from cache import thumbnail_cache
from export import export_csv, export_jsonl, export_sqlite
from models import Asset, HashGroup
from scanner import ScanWorker, sha256_file

PAGE_SIZE = 50
SMALL_THUMBNAIL = 160


class ThumbnailSignals(QObject):
    loaded = Signal(str, int, QImage)


class ThumbnailJob(QRunnable):
    def __init__(self, path: str, size: int):
        super().__init__()
        self.path = path
        self.size = size
        self.signals = ThumbnailSignals()

    def run(self):
        self.signals.loaded.emit(
            self.path, self.size, thumbnail_cache.get(self.path, self.size)
        )


class PathTree(QWidget):
    def __init__(self, asset: Asset):
        super().__init__()
        self.asset = asset
        self.expanded = False
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        self.arrow = QPushButton("▶")
        self.arrow.setFixedWidth(28)
        self.arrow.clicked.connect(self.toggle)
        self.path_label = QLabel(asset.path)
        self.path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        top.addWidget(self.arrow)
        top.addWidget(self.path_label, 1)
        root.addLayout(top)
        self.details = QWidget()
        detail_layout = QVBoxLayout(self.details)
        detail_layout.setContentsMargins(28, 0, 0, 0)
        for depth, part in enumerate(asset.path_parts):
            detail_layout.addWidget(QLabel(f"{'  ' * depth}{part}"))
        self.details.hide()
        root.addWidget(self.details)

    def toggle(self):
        self.expanded = not self.expanded
        self.arrow.setText("▼" if self.expanded else "▶")
        self.details.setVisible(self.expanded)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            subprocess.Popen(["xdg-open", os.path.dirname(self.asset.path)])
        elif event.button() == Qt.MouseButton.RightButton:
            QGuiApplication.clipboard().setText(self.asset.path)


class ThumbnailLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


class Card(QFrame):
    request_thumbnail = Signal(str, int, object)

    def __init__(self, thumb_path: str):
        super().__init__()
        self.thumb_path = thumb_path
        self.thumb_size = SMALL_THUMBNAIL
        self.expanded = False
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "QFrame { border: 1px solid #777; border-radius: 6px; } QLabel { border: 0; }"
        )
        self.preview = ThumbnailLabel("Loading preview…")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setFixedSize(SMALL_THUMBNAIL, SMALL_THUMBNAIL)
        self.preview.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.preview.clicked.connect(self.toggle_preview)

    def showEvent(self, event):
        super().showEvent(event)
        self.request_thumbnail.emit(self.thumb_path, self.thumb_size, self)

    def toggle_preview(self):
        self.expanded = not self.expanded
        self.thumb_size = 700 if self.expanded else SMALL_THUMBNAIL
        self.preview.setFixedSize(self.thumb_size, self.thumb_size)

        self.request_thumbnail.emit(self.thumb_path, self.thumb_size, self)

    def set_thumbnail(self, image: QImage):
        if image.isNull():
            self.preview.setText("Preview\nUnavailable")
            return

        pix = QPixmap.fromImage(image)

        pix = pix.scaled(
            self.preview.width(),
            self.preview.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        self.preview.setPixmap(pix)
        self.preview.setText("")
        self.preview.repaint()


class DuplicateCard(Card):
    def __init__(self, group: HashGroup):
        super().__init__(group.thumbnail_path)

        layout = QHBoxLayout(self)

        left = QVBoxLayout()

        title = QLabel(f"SHA256: {group.hash}")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")

        left.addWidget(title)

        left.addWidget(
            QLabel(
                f"Duplicate count: {group.duplicate_count}   "
                f"Size: {group.size:,} bytes"
            )
        )

        for asset in group.assets:
            left.addWidget(PathTree(asset))

        left.addStretch()

        layout.addLayout(left, 1)

        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(
            self.preview,
            0,
            Qt.AlignmentFlag.AlignTop,
        )


class AssetCard(Card):
    def __init__(self, asset: Asset):
        super().__init__(asset.path)

        layout = QHBoxLayout(self)

        left = QVBoxLayout()

        title = QLabel(asset.filename)

        title.setStyleSheet("font-weight: bold; font-size: 14px;")

        left.addWidget(title)

        left.addWidget(
            QLabel(
                f"Size: {asset.size:,} bytes   "
                f"Modified: {format_time(asset.modified_time)}"
            )
        )

        left.addWidget(PathTree(asset))

        left.addStretch()

        layout.addLayout(left, 1)

        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(
            self.preview,
            0,
            Qt.AlignmentFlag.AlignTop,
        )


def format_time(value: float) -> str:
    return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S") if value else ""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CloneTree")
        self.resize(1200, 800)
        self.mode = "duplicates"
        self.items: list[HashGroup] | list[Asset] = []
        self.filtered: list[HashGroup] | list[Asset] = []
        self.page = 0
        self.worker: ScanWorker | None = None
        self.pool = QThreadPool.globalInstance()
        self.cards: list[Card] = []
        self._progressive_since_render = 0

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        top = QHBoxLayout()
        self.duplicates = QPushButton("Scan Duplicates")
        self.explore = QPushButton("Explore")
        self.snapshot = QPushButton("Snapshot / Export")
        self.search = QLineEdit(placeholderText="Search filename, path, or hash prefix")
        self.sort = QComboBox()
        self.sort.addItems(["Duplicate count", "Filename", "Size", "Modified date"])
        for widget in (
            self.duplicates,
            self.explore,
            self.snapshot,
            self.search,
            QLabel("Sort:"),
            self.sort,
        ):
            top.addWidget(widget, 1 if widget is self.search else 0)
        layout.addLayout(top)
        self.status = QLabel(
            "Choose a folder to begin. Left-click a path to open its folder. Right-click a path to copy it."
        )
        layout.addWidget(self.status)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.container = QWidget()
        self.card_layout = QVBoxLayout(self.container)
        self.card_layout.addStretch()
        self.scroll.setWidget(self.container)
        layout.addWidget(self.scroll, 1)
        bottom = QHBoxLayout()
        self.prev = QPushButton("Previous Page")
        self.page_label = QLabel("Page 0 / 0")
        self.next = QPushButton("Next Page")
        bottom.addStretch()
        bottom.addWidget(self.prev)
        bottom.addWidget(self.page_label)
        bottom.addWidget(self.next)
        bottom.addStretch()
        layout.addLayout(bottom)

        self.duplicates.clicked.connect(lambda: self.start_scan("duplicates"))
        self.explore.clicked.connect(lambda: self.start_scan("explore"))
        self.snapshot.clicked.connect(self.save_export)
        self.search.textChanged.connect(self.apply_filter)
        self.sort.currentTextChanged.connect(self.apply_filter)
        self.prev.clicked.connect(lambda: self.change_page(-1))
        self.next.clicked.connect(lambda: self.change_page(1))

    def start_scan(self, mode: str):
        root = QFileDialog.getExistingDirectory(
            self, "Choose Directory", os.path.expanduser("~")
        )
        if not root:
            return
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(1000)
        self.mode = mode
        self.items = []
        self.filtered = []
        self.page = 0
        self.render_page()
        self.status.setText(f"Scanning {root}…")
        self.worker = ScanWorker(root, mode)
        self.worker.asset_found.connect(self.add_progressive_item)
        self.worker.group_found.connect(self.add_progressive_item)
        self.worker.progress.connect(self.show_progress)
        self.worker.finished.connect(self.scan_finished)
        self.worker.failed.connect(
            lambda text: QMessageBox.critical(self, "Scan failed", text)
        )
        self.worker.start()

    def add_progressive_item(self, item: object):
        self.items.append(item)

        #
        # Explore mode:
        # Don't keep rebuilding the page while scanning.
        # Just collect assets and let scan_finished()
        # render the first 50 once scanning completes.
        #
        if self.mode == "explore":
            return

        #
        # Duplicate mode:
        # Progressively reveal duplicate groups.
        #
        self._progressive_since_render += 1

        if (
            len(self.items) == 1
            or self._progressive_since_render >= 25
        ):
            self._progressive_since_render = 0
            self.apply_filter(keep_page=True)

    def show_progress(self, scanned: int, groups: int, path: str, elapsed: float):
        label = (
            "duplicate groups found" if self.mode == "duplicates" else "assets found"
        )
        found = groups if self.mode == "duplicates" else len(self.items)
        self.status.setText(
            f"Files scanned: {scanned:,} | {label}: {found:,} | Current file: {path} | Elapsed: {elapsed:.1f}s"
        )

    def scan_finished(self, items: object):
        self.items = list(items)
        self.apply_filter()
        self.status.setText(
            f"Scan complete. Showing {len(self.filtered):,} {self.mode} results."
        )

    def apply_filter(self, keep_page: bool = False):
        text = self.search.text().casefold()
        data = list(self.items)
        if text:
            data = [item for item in data if self.matches(item, text)]
        key = self.sort.currentText()
        reverse = key != "Filename"
        data.sort(key=lambda item: self.sort_value(item, key), reverse=reverse)
        self.filtered = data
        if not keep_page:
            self.page = 0
        self.render_page()

    def matches(self, item: HashGroup | Asset, text: str) -> bool:
        if isinstance(item, HashGroup):
            return item.hash.casefold().startswith(text) or any(
                text in a.filename.casefold() or text in a.path.casefold()
                for a in item.assets
            )
        return (
            text in item.filename.casefold()
            or text in item.path.casefold()
            or item.hash.casefold().startswith(text)
        )

    def sort_value(self, item: HashGroup | Asset, key: str):
        if key == "Filename":
            return item.filename.casefold()
        if key == "Size":
            return item.size
        if key == "Modified date":
            return item.modified_time
        return (
            (
                item.duplicate_count
                if isinstance(item, HashGroup)
                else item.duplicate_count
            ),
            item.size,
        )

    def render_page(self):
        while self.card_layout.count() > 1:
            child = self.card_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.cards = []
        pages = max(1, math.ceil(len(self.filtered) / PAGE_SIZE))
        self.page = min(self.page, pages - 1)
        start = self.page * PAGE_SIZE
        for item in self.filtered[start : start + PAGE_SIZE]:
            card = (
                DuplicateCard(item) if isinstance(item, HashGroup) else AssetCard(item)
            )
            card.request_thumbnail.connect(self.load_thumbnail)
            self.cards.append(card)
            self.card_layout.insertWidget(self.card_layout.count() - 1, card)
        visible_page = self.page + 1 if self.filtered else 0
        total_pages = pages if self.filtered else 0
        self.page_label.setText(
            f"Page {visible_page} / {total_pages} ({len(self.filtered):,} results)"
        )
        self.prev.setEnabled(self.page > 0)
        self.next.setEnabled(bool(self.filtered) and self.page < pages - 1)

    def change_page(self, delta: int):
        self.page += delta
        self.render_page()
        self.scroll.verticalScrollBar().setValue(0)

    def load_thumbnail(self, path: str, size: int, card: Card):
        try:
            image = thumbnail_cache.get(path, size)

            if image.isNull():
                print("NULL IMAGE", path)
                return

            card.set_thumbnail(image)

        except Exception as e:
            print("THUMB ERROR", e)

    def thumbnail_loaded(
        self,
        path: str,
        size: int,
        image: QImage,
        card: Card,
    ):
        print(
            "THUMBNAIL",
            path,
            size,
            image.isNull(),
            card in self.cards,
        )

        if card in self.cards and card.thumb_path == path and card.thumb_size == size:
            print("SETTING PIXMAP")
            card.set_thumbnail(image)
        else:
            print("REJECTED")

    def save_export(self):
        filters = "JSONL (*.jsonl);;CSV (*.csv);;SQLite (*.sqlite)"

        path, selected = QFileDialog.getSaveFileName(
            self,
            "Snapshot / Export",
            f"{self.mode}_snapshot.jsonl",
            filters,
        )

        if not path:
            return

        assets = self.assets_for_export()

        if selected.startswith("CSV") or path.endswith(".csv"):
            export_csv(path, assets)

        elif selected.startswith("SQLite") or path.endswith((".sqlite", ".db")):
            export_sqlite(path, assets)

        else:
            export_jsonl(path, assets)

        self.status.setText(f"Exported {len(assets):,} assets to {path}")

    def assets_for_export(self) -> list[Asset]:
        assets: list[Asset] = []

        for item in self.filtered:
            assets.extend(item.assets if isinstance(item, HashGroup) else [item])

        for index, asset in enumerate(
            [a for a in assets if not a.hash],
            1,
        ):
            try:
                asset.hash = sha256_file(asset.path)

            except OSError:
                asset.hash = ""

            if index % 25 == 0:
                self.status.setText(f"Hashing for export: {index:,}")
                QGuiApplication.processEvents()

        return assets

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(1000)

        super().closeEvent(event)
