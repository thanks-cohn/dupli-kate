# CloneTree

## Runtime

Python 3.14+

## GUI

PySide6

## Platform

Linux (Garuda Linux primary)

## Image Formats

.png
.jpg
.jpeg
.webp
.gif

## Current Architecture

main.py
scanner.py
ui.py
models.py
cache.py
export.py

## Requirements

- Qt only
- No Electron
- No web UI
- No database dependency
- SQLite export allowed
- Must run locally
- Must support large image collections

## Performance Goals

- 100,000+ images
- Responsive UI
- Threaded scanning
- Lazy thumbnail loading
- Pagination

## Coding Rules

- Avoid placeholders
- Avoid TODO comments
- Avoid mock implementations
- Produce complete code
- Prefer built-in Qt widgets over custom widgets
- Keep implementation compact

## Future Features

- Metadata inspection
- Reverse image search
- PostgreSQL export
