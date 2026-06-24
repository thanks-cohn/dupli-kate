import os
import sys
import hashlib
import json
import subprocess
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QMainWindow,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QScrollArea,
    QFrame,
    QFileDialog,
)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while c := f.read(1024 * 1024):
            h.update(c)
    return h.hexdigest()


def scan_duplicates(root):
    hashes = {}

    for dp, _, files in os.walk(root):
        for fn in files:
            if os.path.splitext(fn)[1].lower() not in IMAGE_EXTENSIONS:
                continue

            p = os.path.join(dp, fn)

            try:
                h = sha256_file(p)
            except Exception:
                continue

            hashes.setdefault(h, []).append(p)

    return {h: v for h, v in hashes.items() if len(v) > 1}


def scan_assets(root):
    hashes = {}

    for dp, _, files in os.walk(root):
        for fn in files:
            if os.path.splitext(fn)[1].lower() not in IMAGE_EXTENSIONS:
                continue

            p = os.path.join(dp, fn)

            try:
                h = sha256_file(p)
            except Exception:
                continue

            hashes[h] = [p]

    return hashes


class NarrativeRow(QWidget):
    def __init__(self, path):
        super().__init__()

        self.path = path
        self.expanded = False

        rel = os.path.abspath(path).lstrip("/")
        self.parts = rel.split(os.sep)

        collapsed = path

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        top = QHBoxLayout()

        self.arrow = QPushButton("▶")
        self.arrow.setFixedWidth(28)

        self.label = QLabel(collapsed)

        top.addWidget(self.arrow)
        top.addWidget(self.label)
        top.addStretch()

        root.addLayout(top)

        self.details = QWidget()

        d = QVBoxLayout(self.details)
        d.setContentsMargins(20, 0, 0, 0)

        for depth, part in enumerate(self.parts):
            d.addWidget(QLabel(("  " * depth) + part))

        self.details.hide()
        root.addWidget(self.details)

        self.arrow.clicked.connect(self.toggle)

    def toggle(self):
        self.expanded = not self.expanded
        self.arrow.setText("▼" if self.expanded else "▶")
        self.details.setVisible(self.expanded)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            subprocess.Popen(
                ["xdg-open", os.path.dirname(self.path)]
            )
        elif e.button() == Qt.MouseButton.RightButton:
            QGuiApplication.clipboard().setText(self.path)


class AssetBlock(QFrame):
    def __init__(self, h, paths):
        super().__init__()

        self.image_path = paths[0]
        self.expanded = False

        self.setFrameShape(QFrame.Shape.Box)

        layout = QHBoxLayout(self)

        left = QVBoxLayout()

        title = QLabel(f"SHA256: {h[:16]}")
        title.setStyleSheet("font-weight:bold;")

        left.addWidget(title)

        for p in paths:
            left.addWidget(NarrativeRow(p))

        left.addStretch()

        layout.addLayout(left, 3)

        self.preview = QLabel()
        self.preview.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        self.preview.mousePressEvent = self.toggle_preview

        self.set_preview(160)

        layout.addWidget(self.preview)

    def set_preview(self, size):
        pix = QPixmap(self.image_path)

        self.preview.setFixedSize(size, size)

        if pix.isNull():
            self.preview.setText(
                "Preview\nUnavailable"
            )
            return

        self.preview.setPixmap(
            pix.scaled(
                size,
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def toggle_preview(self, e):
        self.expanded = not self.expanded

        if self.expanded:
            self.set_preview(
                max(500, self.window().width() // 2)
            )
        else:
            self.set_preview(160)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.mode = "duplicates"
        self.data = {}

        self.setWindowTitle("CloneTree")
        self.resize(1200, 800)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)

        self.container = QWidget()
        self.layout = QVBoxLayout(self.container)

        top = QHBoxLayout()

        self.btn_duplicates = QPushButton(
            "Duplicates"
        )
        self.btn_explore = QPushButton(
            "Explore"
        )
        self.btn_snapshot = QPushButton(
            "Snapshot"
        )

        top.addStretch()
        top.addWidget(self.btn_duplicates)
        top.addWidget(self.btn_explore)
        top.addWidget(self.btn_snapshot)

        self.layout.addLayout(top)

        self.btn_duplicates.clicked.connect(
            self.load_duplicates
        )
        self.btn_explore.clicked.connect(
            self.load_explore
        )
        self.btn_snapshot.clicked.connect(
            self.snapshot
        )

        self.scroll.setWidget(self.container)
        self.setCentralWidget(self.scroll)

        self.load_duplicates()

    def clear_view(self):
        while self.layout.count() > 1:
            item = self.layout.takeAt(1)
            w = item.widget()

            if w:
                w.deleteLater()

    def render(self):
        self.clear_view()

        self.layout.addWidget(
            QLabel(
                f"{self.mode.title()} Groups: "
                f"{len(self.data)}"
            )
        )

        for h, paths in self.data.items():
            self.layout.addWidget(
                AssetBlock(h, paths)
            )

        self.layout.addStretch()

    def choose_dir(self):
        return QFileDialog.getExistingDirectory(
            self,
            "Choose Directory",
            os.path.expanduser("~"),
        )

    def load_duplicates(self):
        root = self.choose_dir()

        if not root:
            return

        self.mode = "duplicates"
        self.data = scan_duplicates(root)
        self.render()

    def load_explore(self):
        root = self.choose_dir()

        if not root:
            return

        self.mode = "explore"
        self.data = scan_assets(root)
        self.render()

    def snapshot(self):
        ts = datetime.now().strftime(
            "%Y-%m-%d_%H-%M-%S"
        )
        fn = f"{self.mode}_{ts}.jsonl"

        with open(
            fn,
            "w",
            encoding="utf-8",
        ) as f:
            for h, paths in self.data.items():
                for p in paths:
                    f.write(
                        json.dumps(
                            {
                                "hash": h,
                                "path": p,
                                "filename": os.path.basename(
                                    p
                                ),
                            }
                        )
                        + "\n"
                    )

        print("saved", fn)


app = QApplication(sys.argv)

win = MainWindow()
win.show()

app.exec()
