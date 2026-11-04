import json
import shutil
import subprocess

from conftest import SECRETS, sa
from keyshelf.scan import full_scan


def by_name(r):
    return {it["name"]: it for it in r["items"]}


def test_kinds(shelf):
    items = by_name(full_scan([shelf], []))
    assert "readme.txt" not in items
    assert items["a-adminsdk.json"]["kind"] == "service_account"
    assert items["a-adminsdk.json"]["key_id"] == "aaaaaaaa"
    assert items["client_secret_111.json"]["kind"] == "oauth_web"
    assert items["client_secret_111.json"]["redirects"] == ["http://localhost:3000/cb"]
    assert items["google-services.json"]["packages"] == ["com.example.a"]
    assert items["GoogleService-Info.plist"]["bundle"] == "com.example.a"
    assert items["adc.json"]["kind"] == "authorized_user"
    assert items["archive.json"]["kind"] == "har"
    assert items["broken.json"]["kind"] == "error"
    for it in items.values():
        assert it["usage"]


def test_no_secret_in_output(shelf):
    text = json.dumps(full_scan([shelf], []), ensure_ascii=False)
    for s in SECRETS:
        assert s not in text
    assert "PRIVATE KEY" not in text


def test_findings(shelf):
    fs = full_scan([shelf], [])["findings"]
    types = sorted(f["type"] for f in fs)
    assert types == ["multiple_keys", "same_content"]
    mk = next(f for f in fs if f["type"] == "multiple_keys")
    assert "aaaaaaaa" in mk["text"] and "bbbbbbbb" in mk["text"]


def make_repos(shelf, tmp_path):
    root = tmp_path / "repos"
    app = root / "app"
    (app / "server").mkdir(parents=True)
    shutil.copy(shelf / "a-adminsdk.json", app / "server" / "service-account.json")
    (app / "node_modules").mkdir()
    shutil.copy(shelf / "a-adminsdk.json", app / "node_modules" / "skip.json")
    # not credential-shaped, even though it mentions client_id
    (app / "package.json").write_text(json.dumps({"name": "app", "config": {"client_id": "x"}}), encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(app)], check=True)
    subprocess.run(["git", "-C", str(app), "add", "server/service-account.json"], check=True)
    # a key that is only in a repository (and outside git)
    other = root / "loose"
    other.mkdir()
    (other / "key.json").write_text(json.dumps(sa("proj-z", "zzzzzzzz9999")), encoding="utf-8")
    return root


def test_repo_items(shelf, tmp_path):
    r = full_scan([shelf], [make_repos(shelf, tmp_path)])
    repo = [it for it in r["items"] if it["place"] == "repo"]
    assert sorted(it["name"] for it in repo) == ["key.json", "service-account.json"]

    copy = next(it for it in repo if it["name"] == "service-account.json")
    assert copy["tracked"] is True
    assert copy["repo"].endswith("app") and copy["rel"].replace("\\", "/") == "server/service-account.json"
    assert copy["shelf_ids"] == [by_name(r)["a-adminsdk.json"]["id"]]
    assert copy["how"] == "同じ中身"

    loose = next(it for it in repo if it["name"] == "key.json")
    assert loose["repo"] is None and loose["tracked"] is None and loose["shelf_ids"] == []
    assert loose["rel"].replace("\\", "/") == "loose/key.json"

    shelf_it = by_name(r)["a-adminsdk.json"]
    assert [c["id"] for c in shelf_it["copies"]] == [copy["id"]]

    types = {f["type"]: f for f in r["findings"]}
    assert types["committed"]["ids"] == [copy["id"]]
    assert types["not_on_shelf"]["ids"] == [loose["id"]]
    assert "管理鍵 1" in types["not_on_shelf"]["text"]


def test_repo_items_have_no_secrets(shelf, tmp_path):
    text = json.dumps(full_scan([shelf], [make_repos(shelf, tmp_path)]), ensure_ascii=False)
    for s in SECRETS:
        assert s not in text
