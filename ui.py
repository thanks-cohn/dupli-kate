import math
import os
import subprocess
from datetime import datetime

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPushButton, QTableView, QVBoxLayout, QWidget
)

from cache import load_thumbnail
from export import export_csv, export_jsonl, export_sqlite
from scanner import ScanWorker, sha256_file

PAGE_SIZE = 50


class AssetTableModel(QAbstractTableModel):
    headers = ["Filename", "Size", "Duplicates", "Modified", "Hash", "Path"]

    def __init__(self):
        super().__init__()
        self.assets = []

    def set_assets(self, assets):
        self.beginResetModel()
        self.assets = assets
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.assets)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.headers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        asset = self.assets[index.row()]
        col = index.column()
        if col == 0:
            return asset.filename
        if col == 1:
            return f"{asset.size:,}"
        if col == 2:
            return str(asset.duplicate_count)
        if col == 3:
            return datetime.fromtimestamp(asset.modified_time).strftime("%Y-%m-%d %H:%M")
        if col == 4:
            return asset.hash[:16] if asset.hash else ""
        return asset.path

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.headers[section]
        return None


class PreviewSignals(QObject):
    loaded = Signal(str, QImage)


class PreviewJob(QRunnable):
    def __init__(self, path, size):
        super().__init__()
        self.path = path
        self.size = size
        self.signals = PreviewSignals()

    def run(self):
        self.signals.loaded.emit(self.path, load_thumbnail(self.path, self.size))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CloneTree")
        self.resize(1200, 800)
        self.mode = "duplicates"
        self.assets = []
        self.filtered = []
        self.page = 0
        self.worker = None
        self.pool = QThreadPool.globalInstance()

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        top = QHBoxLayout()
        self.duplicates = QPushButton("Scan Duplicates")
        self.explore = QPushButton("Explore")
        self.search = QLineEdit(placeholderText="Search filename, path, or hash prefix")
        self.sort = QComboBox()
        self.sort.addItems(["Duplicate count", "Filename", "Size", "Modified date"])
        top.addWidget(self.duplicates)
        top.addWidget(self.explore)
        top.addWidget(self.search, 1)
        top.addWidget(QLabel("Sort:"))
        top.addWidget(self.sort)
        layout.addLayout(top)

        self.status = QLabel("Choose a folder to begin.")
        layout.addWidget(self.status)

        self.table = QTableView()
        self.model = AssetTableModel()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.doubleClicked.connect(self.open_folder)
        layout.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        self.prev = QPushButton("Previous Page")
        self.page_label = QLabel("Page 0 / 0")
        self.next = QPushButton("Next Page")
        self.preview = QPushButton("Click To Preview")
        self.preview_label = QLabel("[ Click To Preview ]")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(180, 180)
        self.copy = QPushButton("Copy Path")
        self.export_jsonl = QPushButton("Export JSONL")
        self.export_csv = QPushButton("Export CSV")
        self.export_sqlite = QPushButton("Export SQLite")
        for widget in (self.prev, self.page_label, self.next, self.preview, self.preview_label, self.copy,
                       self.export_jsonl, self.export_csv, self.export_sqlite):
            bottom.addWidget(widget)
        layout.addLayout(bottom)

        self.duplicates.clicked.connect(lambda: self.start_scan("duplicates"))
        self.explore.clicked.connect(lambda: self.start_scan("explore"))
        self.search.textChanged.connect(self.apply_filter)
        self.sort.currentTextChanged.connect(self.apply_filter)
        self.prev.clicked.connect(lambda: self.change_page(-1))
        self.next.clicked.connect(lambda: self.change_page(1))
        self.preview.clicked.connect(lambda: self.load_preview(180))
        self.preview_label.mousePressEvent = lambda event: self.load_preview(520)
        self.copy.clicked.connect(self.copy_path)
        self.export_jsonl.clicked.connect(lambda: self.save_export("jsonl"))
        self.export_csv.clicked.connect(lambda: self.save_export("csv"))
        self.export_sqlite.clicked.connect(lambda: self.save_export("sqlite"))

    def start_scan(self, mode):
        root = QFileDialog.getExistingDirectory(self, "Choose Directory", os.path.expanduser("~"))
        if not root:
            return
        if self.worker and self.worker.isRunning():
            self.worker.stop()
        self.mode = mode
        self.assets = []
        self.filtered = []
        self.page = 0
        self.render_page()
        self.status.setText(f"Scanning {root}...")
        self.worker = ScanWorker(root, mode)
        self.worker.progress.connect(self.show_progress)
        self.worker.finished.connect(self.scan_finished)
        self.worker.failed.connect(lambda text: QMessageBox.critical(self, "Scan failed", text))
        self.worker.start()

    def show_progress(self, scanned, groups, path, elapsed):
        label = "duplicate groups" if self.mode == "duplicates" else "size groups"
        self.status.setText(f"Files scanned: {scanned:,} | {label}: {groups:,} | Elapsed: {elapsed:.1f}s | {path}")

    def scan_finished(self, assets):
        self.assets = assets
        self.status.setText(f"Loaded {len(assets):,} assets in {self.mode} mode.")
        self.apply_filter()

    def apply_filter(self):
        text = self.search.text().casefold()
        if text:
            self.filtered = [a for a in self.assets if text in a.filename.casefold() or text in a.path.casefold() or a.hash.casefold().startswith(text)]
        else:
            self.filtered = list(self.assets)
        key = self.sort.currentText()
        if key == "Filename":
            self.filtered.sort(key=lambda a: a.filename.casefold())
        elif key == "Size":
            self.filtered.sort(key=lambda a: a.size, reverse=True)
        elif key == "Modified date":
            self.filtered.sort(key=lambda a: a.modified_time, reverse=True)
        else:
            self.filtered.sort(key=lambda a: (a.duplicate_count, a.size), reverse=True)
        self.page = 0
        self.render_page()

    def render_page(self):
        pages = max(1, math.ceil(len(self.filtered) / PAGE_SIZE))
        self.page = min(self.page, pages - 1)
        start = self.page * PAGE_SIZE
        self.model.set_assets(self.filtered[start:start + PAGE_SIZE])
        self.table.resizeColumnsToContents()
        self.page_label.setText(f"Page {self.page + 1 if self.filtered else 0} / {pages if self.filtered else 0}")
        self.prev.setEnabled(self.page > 0)
        self.next.setEnabled(self.page < pages - 1 and bool(self.filtered))
        self.preview_label.setText("[ Click To Preview ]")
        self.preview_label.setPixmap(QPixmap())

    def change_page(self, delta):
        self.page += delta
        self.render_page()

    def selected_asset(self):
        rows = self.table.selectionModel().selectedRows()
        return self.model.assets[rows[0].row()] if rows else None

    def load_preview(self, size):
        asset = self.selected_asset()
        if not asset:
            return
        self.preview_label.setText("Loading preview...")
        job = PreviewJob(asset.path, size)
        job.signals.loaded.connect(self.preview_loaded)
        self.pool.start(job)

    def preview_loaded(self, path, image):
        asset = self.selected_asset()
        if not asset or asset.path != path:
            return
        if image.isNull():
            self.preview_label.setText("Preview unavailable")
        else:
            self.preview_label.setPixmap(QPixmap.fromImage(image))

    def open_folder(self):
        asset = self.selected_asset()
        if asset:
            subprocess.Popen(["xdg-open", os.path.dirname(asset.path)])

    def copy_path(self):
        asset = self.selected_asset()
        if asset:
            QGuiApplication.clipboard().setText(asset.path)

    def save_export(self, kind):
        suffix = {"jsonl": "JSONL (*.jsonl)", "csv": "CSV (*.csv)", "sqlite": "SQLite (*.sqlite)"}[kind]
        path, _ = QFileDialog.getSaveFileName(self, "Export", f"{self.mode}.{kind}", suffix)
        if not path:
            return
        self.hash_for_export()
        funcs = {"jsonl": export_jsonl, "csv": export_csv, "sqlite": export_sqlite}
        funcs[kind](path, self.filtered)
        self.status.setText(f"Exported {len(self.filtered):,} assets to {path}")

    def hash_for_export(self):
        missing = [asset for asset in self.filtered if not asset.hash]
        for index, asset in enumerate(missing, 1):
            try:
                asset.hash = sha256_file(asset.path)
            except OSError:
                asset.hash = ""
            if index % 25 == 0:
                self.status.setText(f"Hashing for export: {index:,} / {len(missing):,}")
