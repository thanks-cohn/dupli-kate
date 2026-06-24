import csv
import json
import sqlite3
from dataclasses import asdict


def export_jsonl(path, assets):
    with open(path, "w", encoding="utf-8") as f:
        for asset in assets:
            f.write(json.dumps(asdict(asset), ensure_ascii=False) + "\n")


def export_csv(path, assets):
    fields = ["hash", "path", "filename", "size", "modified_time", "duplicate_count"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for asset in assets:
            writer.writerow(asdict(asset))


def export_sqlite(path, assets):
    with sqlite3.connect(path) as db:
        db.execute("drop table if exists assets")
        db.execute("""
            create table assets (
                hash text, path text primary key, filename text,
                size integer, modified_time real, duplicate_count integer
            )
        """)
        db.executemany(
            "insert into assets values (:hash, :path, :filename, :size, :modified_time, :duplicate_count)",
            (asdict(asset) for asset in assets),
        )
