"""Windows scripts must be ASCII only with CRLF (cmd / PowerShell 5.1 misread UTF-8 and LF)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_scripts_ascii_crlf():
    files = [p for ext in ("*.cmd", "*.bat", "*.ps1") for p in ROOT.rglob(ext) if ".venv" not in p.parts]
    assert files
    for p in files:
        data = p.read_bytes()
        assert data.isascii(), p
        assert b"\n" not in data.replace(b"\r\n", b""), f"{p}: LF without CR"
