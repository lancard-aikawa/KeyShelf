import http.client
import json
import plistlib
import threading
from http.server import ThreadingHTTPServer

import pytest

from keyshelf.server import State, make_handler

# Built at runtime so that no file in this repository contains a key-shaped string.
PEM = "-----BEGIN " + "PRIVATE KEY-----\nFAKEFAKEFAKE\n-----END " + "PRIVATE KEY-----\n"
SECRETS = ["FAKEFAKEFAKE", "GOCSPX-fakesecret", "AIzaFAKEapikey000", "1//fake-refresh", "fake-har-pw"]


def sa(project, key_id, email=None):
    return {
        "type": "service_account", "project_id": project, "private_key_id": key_id,
        "private_key": PEM, "client_email": email or f"firebase-adminsdk-x@{project}.iam.gserviceaccount.com",
        "client_id": "1234567890",
    }


@pytest.fixture
def shelf(tmp_path, monkeypatch):
    monkeypatch.setenv("KEYSHELF_HOME", str(tmp_path / "home"))
    d = tmp_path / "shelf"
    d.mkdir()
    w = lambda name, obj: (d / name).write_text(json.dumps(obj), encoding="utf-8")
    w("a-adminsdk.json", sa("proj-a", "aaaaaaaa1111"))
    w("a-adminsdk-old.json", sa("proj-a", "bbbbbbbb2222"))
    oauth = {"web": {"client_id": "111-abc.apps.googleusercontent.com", "project_id": "proj-o",
                     "client_secret": "GOCSPX-fakesecret", "redirect_uris": ["http://localhost:3000/cb"]}}
    w("client_secret_111.json", oauth)
    w("client_secret_111(1).json", oauth)
    w("google-services.json", {
        "project_info": {"project_id": "proj-a", "project_number": "42"},
        "client": [{"client_info": {"android_client_info": {"package_name": "com.example.a"}},
                    "api_key": [{"current_key": "AIzaFAKEapikey000"}]}],
    })
    w("adc.json", {"type": "authorized_user", "client_id": "222", "client_secret": "GOCSPX-fakesecret",
                   "refresh_token": "1//fake-refresh"})
    w("archive.json", {"log": {"entries": [{"request": {"url": "https://alice:fake-har-pw@example.com/x"}}]}})
    (d / "GoogleService-Info.plist").write_bytes(plistlib.dumps(
        {"PROJECT_ID": "proj-a", "BUNDLE_ID": "com.example.a", "API_KEY": "AIzaFAKEapikey000"}))
    (d / "broken.json").write_text("{not json", encoding="utf-8")
    (d / "readme.txt").write_text("ignored", encoding="utf-8")
    return d


@pytest.fixture
def server(shelf):
    """A running server on a free port, with no repository folders yet."""
    state = State([shelf], [])
    state.rescan()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), None)
    port = httpd.server_address[1]
    httpd.RequestHandlerClass = make_handler(state, port)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield port
    httpd.shutdown()
    httpd.server_close()


def req(port, method, path, body=None, host=None, ctype="application/json"):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"Host": host or f"127.0.0.1:{port}"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = ctype
    c.request(method, path, body=data, headers=headers)
    r = c.getresponse()
    return r.status, r.read()
