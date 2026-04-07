"""Manage raw / redacted Markdown files and detect changes."""

import hashlib
from pathlib import Path

from app.config import settings


def _raw_dir() -> Path:
    return settings.resolve_path(settings.md_raw_dir)


def _redacted_dir() -> Path:
    return settings.resolve_path(settings.md_redacted_dir)


def _index_dir() -> Path:
    return settings.resolve_path(settings.index_dir)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def list_raw_files() -> list[Path]:
    """Return all .md files in the raw directory, sorted by name."""
    d = _raw_dir()
    if not d.exists():
        return []
    return sorted(d.glob("*.md"))


def read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_redacted(filename: str, content: str) -> Path:
    d = _redacted_dir()
    d.mkdir(parents=True, exist_ok=True)
    out = d / filename
    out.write_text(content, encoding="utf-8")
    return out


def write_index(filename_stem: str, json_text: str) -> Path:
    """Write an index JSON file. filename_stem should NOT include extension."""
    d = _index_dir()
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"{filename_stem}.json"
    out.write_text(json_text, encoding="utf-8")
    return out


def save_raw(filename: str, content: bytes) -> Path:
    """Save an uploaded MD file to the raw directory. Returns the saved path."""
    d = _raw_dir()
    d.mkdir(parents=True, exist_ok=True)
    out = d / filename
    out.write_bytes(content)
    return out


def read_redacted(filename: str) -> str | None:
    f = _redacted_dir() / filename
    if f.exists():
        return f.read_text(encoding="utf-8")
    return None


def read_index(filename_stem: str) -> str | None:
    f = _index_dir() / f"{filename_stem}.json"
    if f.exists():
        return f.read_text(encoding="utf-8")
    return None
