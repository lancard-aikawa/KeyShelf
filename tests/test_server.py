import json

from conftest import SECRETS, req


def test_page_and_list(server):
    s, page = req(server, "GET", "/")
    assert s == 200 and b"KeyShelf" in page
    s, body = req(server, "GET", "/api/list")
    assert s == 200
    text = body.decode("utf-8")
    for secret in SECRETS:
        assert secret not in text
    assert len(json.loads(text)["items"]) == 9


def test_host_check(server):
    s, _ = req(server, "GET", "/api/list", host="evil.example:80")
    assert s == 403


def test_post_needs_json(server):
    s, _ = req(server, "POST", "/api/note", body={}, ctype="text/plain")
    assert s == 415


def test_note_roundtrip(server):
    items = json.loads(req(server, "GET", "/api/list")[1])["items"]
    key = items[0]["note_key"]
    s, _ = req(server, "POST", "/api/note", body={"key": key, "note": "メモ", "unneeded": True})
    assert s == 200
    items = json.loads(req(server, "GET", "/api/list")[1])["items"]
    it = next(i for i in items if i["note_key"] == key)
    assert it["mark"] == {"note": "メモ", "unneeded": True}


def test_note_unknown_file(server):
    s, _ = req(server, "POST", "/api/note", body={"key": "repo:C:\\nowhere.json", "note": "x"})
    assert s == 404


def test_reveal_only_known_ids(server):
    s, _ = req(server, "POST", "/api/reveal", body={"id": r"C:\Windows\System32\cmd.exe"})
    assert s == 404
