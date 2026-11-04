"""Shelves: subfolders, several shelves, per-file marks, migration from older data."""

import json
import shutil

from conftest import req, sa
from keyshelf import store
from keyshelf.scan import full_scan


def test_subfolders_and_ids(shelf):
    (shelf / "a-lamo").mkdir()
    shutil.copy(shelf / "a-adminsdk.json", shelf / "a-lamo" / "a-adminsdk.json")
    r = full_scan([shelf], [])
    copies = [it for it in r["items"] if it["name"] == "a-adminsdk.json"]
    assert len(copies) == 2
    assert {c["rel"].replace("\\", "/") for c in copies} == {"a-adminsdk.json", "a-lamo/a-adminsdk.json"}
    assert copies[0]["id"] != copies[1]["id"]  # same content, still two items
    same = [f for f in r["findings"] if f["type"] == "same_content" and set(f["ids"]) == {c["id"] for c in copies}]
    assert same


def test_repo_skips_files_inside_shelves(shelf, tmp_path):
    root = tmp_path / "repos"
    (root / "app").mkdir(parents=True)
    shutil.copy(shelf / "a-adminsdk.json", root / "app" / "sa.json")
    r = full_scan([shelf], [root])
    repo = [it for it in r["items"] if it["place"] == "repo"]
    assert [it["name"] for it in repo] == ["sa.json"]


def test_unneeded_is_per_file(server, shelf):
    items = json.loads(req(server, "GET", "/api/list")[1])["items"]
    twins = [it for it in items if it["name"].startswith("client_secret_111")]
    assert len(twins) == 2 and twins[0]["sha256"] == twins[1]["sha256"]
    req(server, "POST", "/api/note", body={"key": twins[0]["note_key"], "unneeded": True})
    items = json.loads(req(server, "GET", "/api/list")[1])["items"]
    marks = {it["id"]: it["mark"]["unneeded"] for it in items if it["name"].startswith("client_secret_111")}
    assert sorted(marks.values()) == [False, True]


def test_legacy_notes_keyed_by_content(server, shelf):
    items = json.loads(req(server, "GET", "/api/list")[1])["items"]
    it = next(i for i in items if i["name"] == "a-adminsdk.json")
    store._write(store.home() / "notes.json", {it["sha256"]: {"note": "old", "unneeded": False}})
    items = json.loads(req(server, "GET", "/api/list")[1])["items"]
    assert next(i for i in items if i["id"] == it["id"])["mark"]["note"] == "old"
    # saving moves it to the new key and keeps the old text
    req(server, "POST", "/api/note", body={"key": it["note_key"], "unneeded": True})
    assert store.load_notes()[it["note_key"]] == {"note": "old", "unneeded": True}


def test_config_migrates_single_folder(shelf):
    store._write(store.home() / "config.json", {"folder": "C:\\old", "roots": []})
    cfg = store.load_config()
    assert cfg["shelves"] == ["C:\\old"] and "folder" not in cfg
