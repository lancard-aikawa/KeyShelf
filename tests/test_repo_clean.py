"""No credential file may ever be committed to this repository."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def tracked_files():
    r = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-co", "--exclude-standard"],
                       capture_output=True, text=True, check=True)
    return [ROOT / p for p in r.stdout.splitlines()]


def test_no_credential_files_tracked():
    bad = []
    marker = "BEGIN " + "PRIVATE KEY"
    for p in tracked_files():
        if p.suffix.lower() in (".json", ".plist") and p.name not in ("package.json",):
            bad.append(p)
        elif p.is_file() and marker in p.read_text(encoding="utf-8", errors="ignore"):
            bad.append(p)
    assert bad == []
