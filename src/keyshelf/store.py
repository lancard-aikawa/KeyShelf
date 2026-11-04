"""Config and user notes, kept in %USERPROFILE%\\.keyshelf. Never holds secrets."""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_PORT = 20002


def home() -> Path:
    return Path(os.environ.get("KEYSHELF_HOME") or Path.home() / ".keyshelf")


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def default_roots() -> list[str]:
    """Common places for repositories that exist on this machine (change them in the UI)."""
    h = Path.home()
    cands = [h / "source" / "repos", h / "repos", h / "src", Path(r"C:\Repos")]
    return [str(r) for r in cands if r.is_dir()]


def default_shelf() -> str:
    """Created on first run when nothing else is configured."""
    return str(Path.home() / "KeyShelf")


def load_config() -> dict:
    """{"shelves": [...], "roots": [...], "port": int}.

    Older configs had a single "folder" (the shelf); it becomes the first shelf.
    """
    cfg = _read(home() / "config.json", {})
    if "shelves" not in cfg:
        cfg["shelves"] = [cfg.get("folder") or default_shelf()]
    cfg.pop("folder", None)
    cfg.setdefault("roots", default_roots())
    cfg.setdefault("port", DEFAULT_PORT)
    return cfg


def save_config(cfg: dict) -> None:
    _write(home() / "config.json", cfg)


def load_repo() -> dict:
    """Last repository search: {"items": [...], "stats": {...}}. Metadata only, no secrets."""
    return _read(home() / "repo.json", {"items": [], "stats": None})


def save_repo(items: list, stats: dict) -> None:
    _write(home() / "repo.json", {"items": items, "stats": stats})


def load_notes() -> dict:
    """{note_key: {"note": str, "unneeded": bool}}.

    Keys are "shelf:<path>" and "repo:<path>": each file has its own mark, so one of
    two identical files can be marked unneeded. Older notes were keyed by content
    sha256; they are still read as a fallback (``legacy``) and moved on the next save.
    """
    return _read(home() / "notes.json", {})


BLANK = {"note": "", "unneeded": False}


def mark_of(notes: dict, key: str, legacy: str | None = None) -> dict:
    return notes.get(key) or (notes.get(legacy) if legacy else None) or dict(BLANK)


def save_note(key: str, note: str | None = None, unneeded: bool | None = None,
              legacy: str | None = None) -> dict:
    notes = load_notes()
    cur = dict(mark_of(notes, key, legacy))
    if note is not None:
        cur["note"] = note[:2000]
    if unneeded is not None:
        cur["unneeded"] = bool(unneeded)
    notes[key] = cur
    _write(home() / "notes.json", notes)
    return cur
