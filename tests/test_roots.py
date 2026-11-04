"""Adding and removing folders (保管庫 = shelf, リポジトリ = repo) from the web UI."""

import json
import time

import pytest

from conftest import req, sa
from keyshelf import store


@pytest.fixture
def repos(tmp_path):
    a = tmp_path / "repos_a"
    b = tmp_path / "repos_b"
    for d, key in ((a, "aaaa1111"), (b, "bbbb2222")):
        (d / "proj").mkdir(parents=True)
        (d / "proj" / "key.json").write_text(json.dumps(sa("proj-" + key[:1], key)), encoding="utf-8")
    return a, b


def folders(port, kind, action, path):
    s, body = req(port, "POST", "/api/folders", body={"kind": kind, "action": action, "path": str(path)})
    return s, json.loads(body)


def wait_search(port, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        r = json.loads(req(port, "GET", "/api/list")[1])
        if not r["searching"]:
            return r
        time.sleep(0.1)
    raise AssertionError("search did not finish")


def paths(r, place):
    return sorted(it["path"] for it in r["items"] if it["place"] == place)


# ---------------------------------------------------------------- repository folders

def test_repo_add_and_remove(server, repos):
    a, b = repos
    s, body = folders(server, "repo", "add", a)
    assert s == 200, body
    r = wait_search(server)
    assert r["roots"] == [str(a)]
    assert paths(r, "repo") == [str(a / "proj" / "key.json")]
    assert store.load_config()["roots"] == [str(a)]

    folders(server, "repo", "add", b)
    r = wait_search(server)
    assert len(paths(r, "repo")) == 2
    assert r["root_counts"] == {str(a): 1, str(b): 1}

    s, r = folders(server, "repo", "remove", str(a).upper())
    assert s == 200
    assert r["roots"] == [str(b)]
    assert paths(r, "repo") == [str(b / "proj" / "key.json")]  # dropped at once, no new search needed
    assert store.load_config()["roots"] == [str(b)]
    assert (a / "proj" / "key.json").exists()  # files are never touched
    # the cache no longer holds the removed folder, so a restart does not bring it back
    assert [it["path"] for it in store.load_repo()["items"]] == [str(b / "proj" / "key.json")]


def test_cache_outside_roots_is_ignored(shelf, repos):
    from keyshelf.scan import find_repo_items
    from keyshelf.server import State
    a, b = repos
    items, stats = find_repo_items([a, b])
    store.save_repo(items, stats)
    state = State([shelf], [b])
    assert [it["path"] for it in state.repo_items] == [str(b / "proj" / "key.json")]


@pytest.mark.parametrize("path, msg", [
    ("", "空"),
    ("relative\\dir", "絶対パス"),
    ("C:\\does-not-exist-keyshelf", "無い"),
])
def test_add_rejects(server, path, msg):
    for kind in ("repo", "shelf"):
        s, body = folders(server, kind, "add", path)
        assert s == 400 and msg in body["error"]


def test_add_rejects_duplicate_and_nested(server, repos):
    a, _ = repos
    assert folders(server, "repo", "add", a)[0] == 200
    wait_search(server)
    for path, msg in ((str(a) + "\\", "登録済み"), (a / "proj", "中にある"), (a.parent, "含む")):
        s, body = folders(server, "repo", "add", path)
        assert s == 400 and msg in body["error"], (path, body)


def test_remove_unknown(server):
    assert folders(server, "repo", "remove", "C:\\nope")[0] == 400
    assert folders(server, "nope", "add", "C:\\")[0] == 400


# ---------------------------------------------------------------- shelves

def test_shelf_add_and_remove(server, shelf, tmp_path):
    extra = tmp_path / "extra_shelf"
    (extra / "sub").mkdir(parents=True)
    (extra / "sub" / "k.json").write_text(json.dumps(sa("proj-x", "xxxx1111")), encoding="utf-8")

    s, r = folders(server, "shelf", "add", extra)
    assert s == 200, r
    assert r["shelves"] == [str(shelf), str(extra)]
    assert r["shelf_counts"][str(extra)] == 1
    assert str(extra / "sub" / "k.json") in paths(r, "shelf")  # subfolders are read
    assert store.load_config()["shelves"] == [str(shelf), str(extra)]

    s, r = folders(server, "shelf", "remove", shelf)
    assert s == 200 and r["shelves"] == [str(extra)]
    assert paths(r, "shelf") == [str(extra / "sub" / "k.json")]

    s, body = folders(server, "shelf", "remove", extra)  # the last one stays
    assert s == 400 and "1 つ以上" in body["error"]


def test_nesting_between_kinds(server, shelf, repos):
    a, _ = repos
    assert folders(server, "repo", "add", a)[0] == 200
    wait_search(server)
    s, body = folders(server, "shelf", "add", a / "proj")  # a shelf inside a repository folder
    assert s == 400 and "リポジトリ" in body["error"]
    s, body = folders(server, "repo", "add", shelf.parent)  # a repository folder around a shelf
    assert s == 400 and "保管庫" in body["error"]
