"""Local-only web UI. Binds 127.0.0.1, checks Host, accepts JSON POST only."""

from __future__ import annotations

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path

from . import store
from .scan import assemble, find_repo_items, inside, same_path, scan_shelves

KIND_NAMES = {"shelf": "保管庫", "repo": "リポジトリ"}


class State:
    """Shelf scan is fast and done on demand; the repository search runs in a thread."""

    def __init__(self, shelves: list[Path], roots: list[Path]):
        self.shelves = list(shelves)
        self.roots = list(roots)
        self.lock = threading.Lock()
        self.items: list[dict] = []
        cached = store.load_repo()
        # ignore cached files outside the current roots (a root may have been removed)
        self.repo_items: list[dict] = [it for it in cached.get("items") or []
                                       if any(inside(it["path"], r) for r in self.roots)]
        self.stats: dict | None = cached.get("stats")
        self.searching = False
        self.again = False

    def rescan(self) -> None:
        with self.lock:
            shelves = list(self.shelves)
        items = scan_shelves(shelves)
        with self.lock:
            self.items = items

    def start_search(self) -> bool:
        with self.lock:
            if self.searching:
                self.again = True  # roots changed while searching: run once more afterwards
                return False
            self.searching = True
            self.again = False
        threading.Thread(target=self._search, daemon=True).start()
        return True

    def _search(self) -> None:
        while True:
            with self.lock:
                roots, shelves = list(self.roots), list(self.shelves)
            try:
                items, stats = find_repo_items(roots, shelves)
                store.save_repo(items, stats)
                with self.lock:
                    if roots == self.roots:
                        self.repo_items, self.stats = items, stats
            except Exception:  # noqa: BLE001 - keep the server alive; next search may succeed
                pass
            with self.lock:
                if not self.again:
                    self.searching = False
                    return
                self.again = False

    # ---- folders: shelves (保管庫) and roots (リポジトリ) ----

    def add_folder(self, kind: str, raw: str) -> str | None:
        """Add a shelf or a repository folder. Returns an error message or None.

        No folder may be inside another one, of either kind: a file would be
        counted twice (for example as an original and as a copy).
        """
        raw = (raw or "").strip().strip('"')
        if not raw:
            return "パスが空"
        p = Path(raw)
        if not p.is_absolute():
            return "絶対パスで書く（例: C:\\Repos）"
        if not p.is_dir():
            return f"フォルダが無い: {raw}"
        p = Path(os.path.normpath(str(p)))
        with self.lock:
            for k, folders in (("shelf", self.shelves), ("repo", self.roots)):
                for f in folders:
                    if same_path(f, p):
                        return f"{KIND_NAMES[k]}に登録済み: {f}"
                    if inside(p, f):
                        return f"{KIND_NAMES[k]}の {f} の中にある"
                    if inside(f, p):
                        return f"{KIND_NAMES[k]}の {f} を含む。先に {f} を削除する"
            if kind == "shelf":
                self.shelves = self.shelves + [p]
            else:
                self.roots = self.roots + [p]
        self._save_folders()
        if kind == "shelf":
            self.rescan()
        else:
            self.start_search()
        return None

    def remove_folder(self, kind: str, raw: str) -> str | None:
        with self.lock:
            folders = self.shelves if kind == "shelf" else self.roots
            keep = [f for f in folders if not same_path(f, raw)]
            if len(keep) == len(folders):
                return f"{KIND_NAMES[kind]}に登録されていない: {raw}"
            if kind == "shelf" and not keep:
                return "保管庫は 1 つ以上要る。先に別の保管庫を追加する"
            if kind == "shelf":
                self.shelves = keep
            else:
                self.roots = keep
                # drop the found files at once (also from the cache, or a restart brings them back)
                self.repo_items = [it for it in self.repo_items if not inside(it["path"], raw)]
                items, stats = list(self.repo_items), self.stats
        if kind == "repo":
            store.save_repo(items, stats)
        self._save_folders()
        if kind == "shelf":
            self.rescan()
        return None

    def _save_folders(self) -> None:
        cfg = store.load_config()
        with self.lock:
            cfg["shelves"] = [str(s) for s in self.shelves]
            cfg["roots"] = [str(r) for r in self.roots]
        store.save_config(cfg)

    def prune(self) -> int:
        """Drop files that no longer exist on disk (deleted or moved since the last scan).

        Repository results come from a cache and a search that may be minutes old,
        so a deleted folder stayed in the list until the next search.
        """
        with self.lock:
            items = [it for it in self.items if os.path.exists(it["path"])]
            repo = [it for it in self.repo_items if os.path.exists(it["path"])]
            dropped = (len(self.items) - len(items)) + (len(self.repo_items) - len(repo))
            repo_changed = len(repo) != len(self.repo_items)
            self.items, self.repo_items = items, repo
            stats = self.stats
        if repo_changed:
            store.save_repo(repo, stats)
        return dropped

    def get(self) -> dict:
        with self.lock:
            return assemble(self.shelves, self.roots, self.items, self.repo_items, self.stats)

    def view(self) -> dict:
        self.prune()
        r = self.get()
        notes = store.load_notes()
        r["items"] = [dict(it, mark=store.mark_of(notes, it["note_key"],
                                                  it["sha256"] if it["place"] == "shelf" else None))
                      for it in r["items"]]
        r["searching"] = self.searching
        r["shelf_counts"] = {s: sum(1 for it in r["items"] if it["place"] == "shelf" and inside(it["path"], s))
                             for s in r["shelves"]}
        r["root_counts"] = {s: sum(1 for it in r["items"] if it["place"] == "repo" and inside(it["path"], s))
                            for s in r["roots"]}
        return r

    def path_of(self, item_id: str) -> Path | None:
        for it in self.get()["items"]:
            if it["id"] == item_id:
                return Path(it["path"])
        return None


def make_handler(state: State, port: int):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    page = resources.files("keyshelf").joinpath("web/index.html").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # quiet
            pass

        def _host_ok(self) -> bool:
            if self.headers.get("Host") not in allowed_hosts:
                self._send(403, b"forbidden host", "text/plain")
                return False
            return True

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, data) -> None:
            self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json")

        def do_GET(self):
            if not self._host_ok():
                return
            if self.path == "/":
                self._send(200, page, "text/html")
            elif self.path == "/api/list":
                self._json(200, state.view())
            elif self.path == "/favicon.ico":
                self._send(204, b"", "image/x-icon")
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            if not self._host_ok():
                return
            # Read the body first, even when refusing: replying before the client has
            # finished sending makes the connection reset on its side.
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = 0
            if n > 65536:
                self._send(413, b"too large", "text/plain")
                return
            raw = self.rfile.read(n) if n > 0 else b""
            # A cross-site form cannot send application/json without a preflight.
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                self._send(415, b"json only", "text/plain")
                return
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                self._json(400, {"error": "bad json"})
                return
            if not isinstance(body, dict):
                self._json(400, {"error": "json object only"})
                return
            if self.path == "/api/rescan":
                state.rescan()
                if body.get("repos"):
                    state.start_search()
                self._json(200, state.view())
            elif self.path == "/api/note":
                key = str(body.get("key") or "")
                it = next((i for i in state.get()["items"] if i["note_key"] == key), None)
                if it is None:
                    self._json(404, {"error": "unknown file"})
                    return
                legacy = it["sha256"] if it["place"] == "shelf" else None
                mark = store.save_note(key, body.get("note"), body.get("unneeded"), legacy=legacy)
                self._json(200, mark)
            elif self.path == "/api/folders":
                kind, action = body.get("kind"), body.get("action")
                path = str(body.get("path") or "")
                if kind not in KIND_NAMES:
                    err = "kind は shelf か repo"
                elif action == "add":
                    err = state.add_folder(kind, path)
                elif action == "remove":
                    err = state.remove_folder(kind, path)
                else:
                    err = "action は add か remove"
                if err:
                    self._json(400, {"error": err})
                else:
                    self._json(200, state.view())
            elif self.path == "/api/reveal":
                # Only files that the scan itself found may be revealed.
                p = state.path_of(str(body.get("id") or ""))
                if p is None or not p.exists():
                    self._json(404, {"error": "unknown file"})
                    return
                subprocess.Popen(["explorer", f"/select,{p}"])
                self._json(200, {"ok": True})
            else:
                self._send(404, b"not found", "text/plain")

    return Handler


def serve(shelves: list[Path], roots: list[Path], port: int, open_browser: bool = True) -> None:
    state = State(shelves, roots)
    state.rescan()
    # Show the cached result at once, but always search again in the background:
    # files may have been added or deleted since the cache was written.
    state.start_search()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state, port))
    url = f"http://127.0.0.1:{port}/"
    print(f"KeyShelf: {url}  (Ctrl+C to stop)")
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
