"""Read one credential file and return only safe metadata.

The returned dict must never contain secret values (private keys, client
secrets, API keys, refresh tokens). Only identifiers that are needed to tell
files apart are kept: project id, account e-mail, the first 8 characters of
the key id, client id, package / bundle names and redirect URIs.
"""

from __future__ import annotations

import hashlib
import json
import plistlib
from pathlib import Path
from urllib.parse import urlsplit

MAX_BYTES = 2 * 1024 * 1024

# kind -> (short label, risk)
KINDS = {
    "service_account": ("管理鍵", "high"),
    "authorized_user": ("ログイン情報", "high"),
    "oauth_web": ("OAuth", "mid"),
    "oauth_installed": ("OAuth", "mid"),
    "android": ("Android", "low"),
    "ios": ("iOS", "low"),
    "har": ("通信記録", "mid"),
    "other": ("その他", "unknown"),
    "error": ("読めない", "unknown"),
}


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def classify_bytes(name: str, data: bytes) -> dict:
    """Classify file content. ``name`` is used only to pick the parser."""
    info: dict = {"kind": "other"}
    try:
        if name.lower().endswith(".plist"):
            info = _ios(plistlib.loads(data))
        else:
            info = _json(json.loads(data.decode("utf-8-sig")))
    except Exception as e:  # noqa: BLE001 - any parse error is just "unreadable"
        info = {"kind": "error", "error": type(e).__name__}
    label, risk = KINDS[info["kind"]]
    info["label"] = label
    info["risk"] = risk
    info["usage"] = usage_text(info)
    return info


def classify_file(path: Path) -> dict:
    data = path.read_bytes()[: MAX_BYTES + 1]
    if len(data) > MAX_BYTES:
        info = {"kind": "other", "note": "too large"}
        info.update(label=KINDS["other"][0], risk="unknown", usage=usage_text(info))
    else:
        info = classify_bytes(path.name, data)
    info["sha256"] = sha256_of(data)
    return info


def _s(v):
    """Keep a text identifier; anything else in a hand-edited file (list, dict, ...) becomes None."""
    if isinstance(v, str):
        return v
    if isinstance(v, int) and not isinstance(v, bool):
        return str(v)
    return None


def _strs(v) -> list[str]:
    return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []


def _host(url) -> str:
    """Host (and port) only: user:password@ in the URL must not reach the output."""
    try:
        u = urlsplit(url)
        return (u.hostname or "") + (f":{u.port}" if u.port else "")
    except (TypeError, ValueError, AttributeError):
        return ""


def _ios(d: dict) -> dict:
    if not isinstance(d, dict):
        return {"kind": "other", "keys": [type(d).__name__]}
    return {
        "kind": "ios",
        "project": _s(d.get("PROJECT_ID")),
        "bundle": _s(d.get("BUNDLE_ID")),
        "sender_id": _s(d.get("GCM_SENDER_ID")),
    }


def _json(d) -> dict:
    if not isinstance(d, dict):
        return {"kind": "other", "keys": [type(d).__name__]}
    t = d.get("type")
    if t == "service_account":
        return {
            "kind": "service_account",
            "project": _s(d.get("project_id")),
            "email": _s(d.get("client_email")),
            "key_id": (_s(d.get("private_key_id")) or "")[:8],
        }
    if t == "authorized_user":
        return {
            "kind": "authorized_user",
            "project": _s(d.get("quota_project_id")),
            "client_id": _s(d.get("client_id")),
        }
    if "project_info" in d:
        pi = d.get("project_info") or {}
        packages = []
        for c in d.get("client") or []:
            pkg = ((c.get("client_info") or {}).get("android_client_info") or {}).get("package_name")
            if _s(pkg):
                packages.append(_s(pkg))
        return {
            "kind": "android",
            "project": _s(pi.get("project_id")),
            "sender_id": _s(pi.get("project_number")),
            "packages": packages,
        }
    for k in ("web", "installed"):
        if isinstance(d.get(k), dict) and "client_id" in d[k]:
            c = d[k]
            return {
                "kind": f"oauth_{k}",
                "project": _s(c.get("project_id")),
                "client_id": _s(c.get("client_id")),
                "redirects": _strs(c.get("redirect_uris")),
                "origins": _strs(c.get("javascript_origins")),
            }
    if isinstance(d.get("log"), dict) and "entries" in d["log"]:
        entries = d["log"].get("entries") or []
        hosts = []
        for e in entries:
            req = e.get("request") if isinstance(e, dict) else None
            host = _host(req.get("url")) if isinstance(req, dict) else ""
            if host and host not in hosts:
                hosts.append(host)
        return {"kind": "har", "entries": len(entries), "hosts": hosts[:10]}
    return {"kind": "other", "keys": sorted(d.keys())[:10]}


def usage_text(info: dict) -> str:
    """Plain Japanese explanation of what the file is used for."""
    k = info["kind"]
    p = info.get("project") or "?"
    if k == "service_account":
        return (
            f"サーバやスクリプトから、プロジェクト {p} を管理者として操作する鍵。"
            "Firebase Admin SDK（FCM の送信・Firestore・Auth など）や gcloud で使う。"
            "漏れるとプロジェクトを丸ごと操作される。アプリに同梱しない"
        )
    if k == "authorized_user":
        return "gcloud などでログインした人の資格情報（更新用のトークン入り）。その人として API を呼べる"
    if k in ("oauth_web", "oauth_installed"):
        where = "ウェブ" if k == "oauth_web" else "デスクトップ"
        r = info.get("redirects") or []
        dest = f"戻り先: {', '.join(r)}" if r else "戻り先の登録なし"
        return f"Google でログインさせる（OAuth）ための{where}アプリの登録情報。プロジェクト {p}。{dest}"
    if k == "android":
        pk = ", ".join(info.get("packages") or []) or "?"
        return (
            f"Android アプリ（{pk}）に組み込む Firebase の設定。"
            "app/google-services.json に置く。アプリに入れて配る前提のもので、秘密度は低い"
        )
    if k == "ios":
        return (
            f"iOS アプリ（{info.get('bundle') or '?'}）に組み込む Firebase の設定。"
            "Runner/GoogleService-Info.plist に置く。秘密度は低い"
        )
    if k == "har":
        hosts = ", ".join(info.get("hosts") or [])
        return f"ブラウザの通信の記録（HAR、{info.get('entries', 0)} 件。{hosts}）。鍵ではないが、Cookie やトークンが写っていることがある"
    if k == "error":
        return "JSON / plist として読めなかった"
    return "Google の鍵の形ではない"
