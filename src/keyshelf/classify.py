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


def _ios(d: dict) -> dict:
    return {
        "kind": "ios",
        "project": d.get("PROJECT_ID"),
        "bundle": d.get("BUNDLE_ID"),
        "sender_id": d.get("GCM_SENDER_ID"),
    }


def _json(d) -> dict:
    if not isinstance(d, dict):
        return {"kind": "other", "keys": [type(d).__name__]}
    t = d.get("type")
    if t == "service_account":
        return {
            "kind": "service_account",
            "project": d.get("project_id"),
            "email": d.get("client_email"),
            "key_id": (d.get("private_key_id") or "")[:8],
        }
    if t == "authorized_user":
        return {
            "kind": "authorized_user",
            "project": d.get("quota_project_id"),
            "client_id": d.get("client_id"),
        }
    if "project_info" in d:
        pi = d.get("project_info") or {}
        packages = []
        for c in d.get("client") or []:
            pkg = ((c.get("client_info") or {}).get("android_client_info") or {}).get("package_name")
            if pkg:
                packages.append(pkg)
        return {
            "kind": "android",
            "project": pi.get("project_id"),
            "sender_id": pi.get("project_number"),
            "packages": packages,
        }
    for k in ("web", "installed"):
        if isinstance(d.get(k), dict) and "client_id" in d[k]:
            c = d[k]
            return {
                "kind": f"oauth_{k}",
                "project": c.get("project_id"),
                "client_id": c.get("client_id"),
                "redirects": list(c.get("redirect_uris") or []),
                "origins": list(c.get("javascript_origins") or []),
            }
    if isinstance(d.get("log"), dict) and "entries" in d["log"]:
        entries = d["log"].get("entries") or []
        hosts = []
        for e in entries:
            url = ((e or {}).get("request") or {}).get("url") or ""
            host = url.split("/")[2] if url.count("/") >= 2 else ""
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
