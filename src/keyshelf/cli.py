"""Command line: `keyshelf list` / `keyshelf serve`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, store
from .scan import full_scan


def _args(argv):
    ap = argparse.ArgumentParser(prog="keyshelf", description="Shelf for Google / Firebase credential files (read-only)")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd")
    for name in ("list", "serve"):
        s = sub.add_parser(name)
        s.add_argument("--shelf", "--folder", dest="shelf", action="append",
                       help="folder that keeps the downloaded files (repeatable; default: config)")
        s.add_argument("--root", action="append", help="repository root to search for copies (repeatable)")
        s.add_argument("--no-copies", action="store_true", help="do not search repositories")
        if name == "list":
            s.add_argument("--json", action="store_true", help="print JSON")
        else:
            s.add_argument("--port", type=int)
            s.add_argument("--no-browser", action="store_true")
    return ap, ap.parse_args(argv)


def main(argv=None) -> int:
    ap, a = _args(argv)
    if not a.cmd:
        ap.print_help()
        return 0
    cfg = store.load_config()
    shelves = [Path(s) for s in (a.shelf or cfg["shelves"])]
    roots = [] if a.no_copies else [Path(r) for r in (a.root or cfg["roots"])]
    if not a.shelf:
        first = Path(store.default_shelf())
        if first in shelves and not first.exists():
            first.mkdir(parents=True)  # first run: an empty shelf to put the downloaded files in
            print(f"created the shelf folder: {first}", file=sys.stderr)
    missing = [s for s in shelves if not s.is_dir()]
    if missing:
        print("shelf folder not found: " + ", ".join(map(str, missing)), file=sys.stderr)
        return 2
    if a.cmd == "serve":
        from .server import serve
        serve(shelves, roots, a.port or cfg["port"], open_browser=not a.no_browser)
        return 0
    r = full_scan(shelves, roots)
    if a.json:
        sys.stdout.reconfigure(encoding="utf-8")
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0
    sys.stdout.reconfigure(encoding="utf-8")
    shelf = [it for it in r["items"] if it["place"] == "shelf"]
    repo = [it for it in r["items"] if it["place"] == "repo"]
    print(f"== shelves: {', '.join(r['shelves'])}")
    for it in shelf:
        proj = it.get("project") or "-"
        print(f"[{it['label']}] {proj:<24} {it['path']}")
        for c in it["copies"]:
            t = "git" if c["tracked"] else "-"
            print(f"      copy({c['how']}, {t}): {c['path']}")
    if not a.no_copies:
        print(f"\n== repositories: {', '.join(r['roots'])}")
        for it in repo:
            proj = it.get("project") or "-"
            t = "git" if it["tracked"] else "-"
            rel = "on shelf" if it["shelf_ids"] else "NOT on shelf"
            print(f"[{it['label']}] {proj:<24} {t:<3} {rel:<12} {it['path']}")
    if r["findings"]:
        print()
        for f in r["findings"]:
            print(f"! {f['title']}: {f['text']}")
    s = r["repo_scan"]
    print(f"\nshelf {len(shelf)} files, repositories {len(repo)} files"
          f" ({s['looked']} candidates in {s['seconds']}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
