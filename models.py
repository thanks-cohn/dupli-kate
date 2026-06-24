from dataclasses import dataclass


@dataclass(slots=True)
class Asset:
    hash: str
    path: str
    filename: str
    size: int
    modified_time: float
    duplicate_count: int = 1
