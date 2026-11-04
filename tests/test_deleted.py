"""Files deleted on disk must leave the list without a manual search (user report 2026-11-04:
folders deleted under C:\\Repos\\test stayed in the list, 55 files, served from the cache)."""

import json
import shutil

from conftest import req, sa
from keyshelf import store
from test_roots import folders, wait_search


def listing(port):
    return json.loads(req(port, "GET", "/api/list")[1])


def test_deleted_repo_folder_leaves_list_and_cache(server, tmp_path):
    root = tmp_path / "repos"
    for name in ("keep", "gone"):
        (root / name).mkdir(parents=True)
        (root / name / "k.json").write_text(json.dumps(sa("p-" + name, name * 2)), encoding="utf-8")
    assert folders(server, "repo", "add", root)[0] == 200
    wait_search(server)
    assert len([i for i in listing(server)["items"] if i["place"] == "repo"]) == 2

    shutil.rmtree(root / "gone")
    repo = [i["path"] for i in listing(server)["items"] if i["place"] == "repo"]
    assert repo == [str(root / "keep" / "k.json")]
    assert [i["path"] for i in store.load_repo()["items"]] == repo  # a restart does not bring it back


def test_deleted_shelf_subfolder_leaves_list(server, shelf):
    (shelf / "sub").mkdir()
    (shelf / "sub" / "x.json").write_text(json.dumps(sa("p-x", "x1")), encoding="utf-8")
    req(server, "POST", "/api/rescan", body={})
    assert any(i["path"].endswith("x.json") for i in listing(server)["items"])

    shutil.rmtree(shelf / "sub")
    assert not any(i["path"].endswith("x.json") for i in listing(server)["items"])
