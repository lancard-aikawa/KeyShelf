"""Files and repositories under the scanned folders are not trusted (security review, 2026-11-04)."""

import json
import shutil
import subprocess

import pytest

from keyshelf.classify import classify_bytes
from keyshelf.scan import _git_tracked, full_scan


def test_har_hides_userinfo():
    har = {"log": {"entries": [{"request": {"url": "https://alice:pw-in-url@api.example.com:8443/x"}},
                               {"request": {"url": 5}}, "junk", None]}}
    info = classify_bytes("a.json", json.dumps(har).encode())
    assert info["hosts"] == ["api.example.com:8443"]
    assert "pw-in-url" not in json.dumps(info) and "alice" not in json.dumps(info)


@pytest.mark.parametrize("obj", [
    {"project_info": {"project_id": ["x"], "project_number": {}},
     "client": [{"client_info": {"android_client_info": {"package_name": ["a"]}}}]},
    {"web": {"client_id": ["c"], "project_id": {}, "redirect_uris": [1, ["u"], "http://ok/cb"]}},
    {"type": "service_account", "project_id": [], "client_email": {}, "private_key_id": ["k"]},
])
def test_odd_types_do_not_break_the_list(tmp_path, obj):
    (tmp_path / "x.json").write_text(json.dumps(obj), encoding="utf-8")
    (tmp_path / "y.json").write_text(json.dumps(obj), encoding="utf-8")
    r = full_scan([tmp_path], [])
    assert len(r["items"]) == 2
    for it in r["items"]:
        for k in ("project", "email", "client_id", "bundle", "sender_id"):
            assert it.get(k) is None or isinstance(it[k], str)


def test_odd_plist(tmp_path):
    import plistlib
    (tmp_path / "GoogleService-Info.plist").write_bytes(plistlib.dumps(["not", "a", "dict"]))
    assert len(full_scan([tmp_path], [])["items"]) == 1


@pytest.mark.skipif(not shutil.which("git"), reason="git not installed")
def test_git_config_command_does_not_run(tmp_path):
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    mark = tmp_path / "RAN"
    subprocess.run(["git", "-C", str(repo), "config", "core.fsmonitor",
                    f"echo x > '{mark.as_posix()}'; false"], check=True)
    (repo / "k.json").write_text("{}", encoding="utf-8")
    assert _git_tracked(repo, repo / "k.json") is False
    assert not mark.exists()
