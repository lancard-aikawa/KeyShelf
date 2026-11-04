"""Scan the shelves and the repository roots, and relate what was found.

Two kinds of folders hold files (the UI calls the shelf "保管庫"):
- shelves: where downloaded files are kept (the originals). Every .json / .plist, subfolders too
- repository roots: every credential-shaped .json / .plist under them (the copies in use)

Both become items of the same shape. Repository items are matched to shelf items
by content or by identity (same key id, same OAuth client, same app).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import subprocess
import time
from collections import defaultdict
from pathlib import Path

from .classify import classify_file

SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "build", "dist", "target", ".dart_tool",
    "__pycache__", ".gradle", "Pods", ".idea", ".next", ".nuxt", ".cache", "vendor",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", "site-packages",
}
EXTS = {".json", ".plist"}
REPO_MAX = 64 * 1024
# A repository file is only parsed when one of these markers appears in it.
MARKERS = (b"private_key_id", b"client_id", b"project_info", b"PROJECT_ID")
# Repository files of these kinds are not shown (not credential-shaped).
NOT_CREDENTIAL = {"other", "error", "har"}

IDENT_NAMES = {"sa": "管理鍵", "oauth": " OAuth クライアント", "android": " Android アプリの設定", "ios": " iOS アプリの設定"}


# ---------------------------------------------------------------- paths

def path_key(p) -> str:
    return os.path.normcase(os.path.normpath(str(p)))


def same_path(a, b) -> bool:
    return path_key(a) == path_key(b)


def inside(child, parent) -> bool:
    """True if child is strictly inside parent (case-insensitive on Windows)."""
    return path_key(child).startswith(path_key(parent).rstrip("\\/") + os.sep)


def _id(prefix: str, p: Path) -> str:
    return prefix + hashlib.sha256(path_key(p).encode("utf-8")).hexdigest()[:15]


def _meta(p: Path, info: dict) -> dict:
    st = p.stat()
    info["name"] = p.name
    info["path"] = str(p)
    info["size"] = st.st_size
    info["mtime"] = dt.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d")
    return info


# ---------------------------------------------------------------- shelves

def scan_shelves(shelves: list[Path]) -> list[dict]:
    """Every .json / .plist under the shelves (subfolders too), credential or not."""
    items = []
    for shelf in shelves:
        if not shelf.is_dir():
            continue
        for p in sorted(_walk(shelf), key=lambda x: str(x).lower()):
            try:
                info = _meta(p, classify_file(p))
            except OSError:
                continue
            info["id"] = _id("s", p)
            info["place"] = "shelf"
            info["shelf"] = str(shelf)
            info["rel"] = str(p.relative_to(shelf))
            # keyed by place: marking one of two identical files "unneeded" must not mark both
            info["note_key"] = "shelf:" + str(p)
            items.append(info)
    return items


def identity(info: dict) -> tuple | None:
    """What makes two files "the same credential" even if bytes differ."""
    k = info["kind"]
    if k == "service_account" and info.get("key_id"):
        return ("sa", info.get("email"), info["key_id"])
    if k.startswith("oauth_") and info.get("client_id"):
        return ("oauth", info["client_id"])
    if k == "android":
        return ("android", info.get("project"), tuple(sorted(info.get("packages") or [])))
    if k == "ios":
        return ("ios", info.get("project"), info.get("bundle"))
    return None


# ---------------------------------------------------------------- repositories

def _walk(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in filenames:
            if os.path.splitext(f)[1].lower() in EXTS:
                yield Path(dirpath) / f


def repo_dir_of(path: Path) -> Path | None:
    """Nearest parent that has a .git entry (folder, or file for worktrees)."""
    for d in path.parents:
        if (d / ".git").exists():
            return d
    return None


def _git_tracked(repo: Path, path: Path) -> bool | None:
    try:
        r = subprocess.run(
            ["git", "-C", str(repo),
             # the repository is not trusted: its .git/config could name a command for fsmonitor
             "-c", "core.fsmonitor=false", "-c", "core.hooksPath=",
             "ls-files", "--error-unmatch", str(path.relative_to(repo))],
            capture_output=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    return r.returncode == 0


def find_repo_items(roots: list[Path], shelves: list[Path] | None = None) -> tuple[list[dict], dict]:
    """Every credential-shaped file under the roots, with its repository and git state.

    Files inside a shelf are skipped (they are originals, not copies).
    """
    t0 = time.monotonic()
    shelves = shelves or []
    items = []
    looked = 0
    for root in roots:
        if not root.is_dir():
            continue
        for p in _walk(root):
            try:
                if any(inside(p, s) for s in shelves):
                    continue
                if p.stat().st_size > REPO_MAX:
                    continue
                data = p.read_bytes()
            except OSError:
                continue
            if not any(m in data for m in MARKERS):
                continue
            looked += 1
            info = classify_file(p)
            if info["kind"] in NOT_CREDENTIAL:
                continue
            info = _meta(p, info)
            repo = repo_dir_of(p)
            info["repo"] = str(repo) if repo else None
            info["rel"] = str(p.relative_to(repo if repo else root))
            info["tracked"] = _git_tracked(repo, p) if repo else None
            info["id"] = _id("r", p)
            info["root"] = str(root)
            info["place"] = "repo"
            info["note_key"] = "repo:" + str(p)
            items.append(info)
    stats = {
        "looked": looked,
        "found": len(items),
        "seconds": round(time.monotonic() - t0, 2),
        "at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    return items, stats


# ---------------------------------------------------------------- relations

def relate(shelf_items: list[dict], repo_items: list[dict]) -> tuple[list[dict], list[dict]]:
    """Attach copies to shelf items and shelf matches to repository items (new dicts)."""
    by_hash = defaultdict(list)
    by_ident = defaultdict(list)
    for it in shelf_items:
        by_hash[it["sha256"]].append(it)
        ident = identity(it)
        if ident:
            by_ident[ident].append(it)
    copies = defaultdict(list)
    out_repo = []
    for r in repo_items:
        matched = []
        how = None
        if r["sha256"] in by_hash:
            matched.extend(by_hash[r["sha256"]])
            how = "同じ中身"
        ident = identity(r)
        for s in by_ident.get(ident, []) if ident else []:
            if s not in matched:
                matched.append(s)
            how = how or "同じ登録"
        out_repo.append(dict(r, shelf_ids=[s["id"] for s in matched], how=how))
        for s in matched:
            copies[s["id"]].append({"id": r["id"], "path": r["path"], "how": how, "tracked": r["tracked"]})
    out_shelf = [dict(s, copies=copies.get(s["id"], [])) for s in shelf_items]
    return out_shelf, out_repo


def _breakdown(items: list[dict]) -> str:
    """e.g. "管理鍵 11・ログイン情報 3"."""
    counts: dict[str, int] = {}
    for it in items:
        counts[it["label"]] = counts.get(it["label"], 0) + 1
    return "・".join(f"{k} {v}" for k, v in counts.items())


def findings(shelf_items: list[dict], repo_items: list[dict]) -> list[dict]:
    out = []

    # git-tracked credentials with high risk (admin keys, user tokens)
    committed = [r for r in repo_items if r["risk"] == "high" and r.get("tracked")]
    if committed:
        out.append({
            "type": "committed", "level": "danger", "title": "git に入っている",
            "text": f"git の管理下にある（{_breakdown(committed)}）: " + ", ".join(r["path"] for r in committed),
            "ids": [r["id"] for r in committed],
        })

    # high-risk files that exist only in repositories
    orphans = [r for r in repo_items if r["risk"] == "high" and not r.get("shelf_ids")]
    if orphans:
        out.append({
            "type": "not_on_shelf", "level": "warn", "title": "未保管",
            "text": f"リポジトリにだけある（{_breakdown(orphans)}）。保管庫に入れるか、要らなければ Google 側で無効にする",
            "ids": [r["id"] for r in orphans],
        })

    # shelf duplicates
    by_hash = defaultdict(list)
    by_ident = defaultdict(list)
    for it in shelf_items:
        by_hash[it["sha256"]].append(it)
        ident = identity(it)
        if ident:
            by_ident[ident].append(it)
    for group in by_hash.values():
        if len(group) > 1:
            out.append({
                "type": "same_content", "level": "info", "title": "中身が同じ",
                "text": f"{len(group)} 個のファイルは中身が全く同じ。1 つ残せばよい",
                "ids": [g["id"] for g in group],
            })
    seen = {tuple(sorted(g["id"] for g in v)) for v in by_hash.values()}
    for ident, group in by_ident.items():
        ids = tuple(sorted(g["id"] for g in group))
        if len(group) > 1 and ids not in seen:
            out.append({
                "type": "same_identity", "level": "info", "title": "同じ登録",
                "text": f"{len(group)} 個のファイルは同じ{IDENT_NAMES[ident[0]]}（{group[0].get('project') or '?'}）。"
                        "取得した日や戻り先の登録が違うだけなので、新しい 1 つを残せばよい",
                "ids": list(ids),
            })

    # several keys for one service account, across shelf and repositories
    by_account = defaultdict(list)
    for it in shelf_items + repo_items:
        if it["kind"] == "service_account" and it.get("email") and it.get("key_id"):
            by_account[it["email"]].append(it)
    for email, group in by_account.items():
        keys = sorted({g["key_id"] for g in group})
        if len(keys) > 1:
            out.append({
                "type": "multiple_keys", "level": "warn", "title": "鍵が複数",
                "text": (f"{email} の鍵が {len(keys)} 本（{', '.join(keys)}）。"
                         "要らない鍵が Google 側でまだ有効なら、コンソールで無効にする"),
                "ids": [g["id"] for g in group],
            })
    return out


def assemble(shelves: list[Path], roots: list[Path], shelf_items: list[dict],
             repo_items: list[dict], stats: dict | None) -> dict:
    shelf, repo = relate(shelf_items, repo_items)
    return {
        "shelves": [str(s) for s in shelves],
        "roots": [str(r) for r in roots],
        "items": shelf + repo,
        "findings": findings(shelf, repo),
        "repo_scan": stats,
        "scanned_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def full_scan(shelves: list[Path], roots: list[Path]) -> dict:
    shelf = scan_shelves(shelves)
    repo, stats = find_repo_items(roots, shelves)
    return assemble(shelves, roots, shelf, repo, stats)
