from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class Asset:
    path: str
    filename: str
    size: int
    modified_time: float
    hash: str = ""
    duplicate_count: int = 1

    @property
    def path_parts(self) -> list[str]:
        return list(Path(self.path).resolve().parts)


@dataclass(slots=True)
class HashGroup:
    hash: str
    assets: list[Asset] = field(default_factory=list)

    @property
    def duplicate_count(self) -> int:
        return len(self.assets)

    @property
    def size(self) -> int:
        return self.assets[0].size if self.assets else 0

    @property
    def modified_time(self) -> float:
        return max((asset.modified_time for asset in self.assets), default=0.0)

    @property
    def filename(self) -> str:
        return self.assets[0].filename if self.assets else ""

    @property
    def thumbnail_path(self) -> str:
        return self.assets[0].path if self.assets else ""
