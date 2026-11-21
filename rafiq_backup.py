#!/usr/bin/env python3
"""Rafiq rolling backup helper (container-side).

Modes:
  restore  if /data/harith.db is missing, fetch the latest encrypted rolling
           backup asset and decrypt+gunzip it into place; fall back to the
           original plain-gzip asset at RESTORE_ASSET_URL.
  push     gzip+encrypt /data/harith.db and upload it as the rolling asset.

Encryption: Fernet (cryptography, already an app dependency) with a key
derived from BACKUP_PASSPHRASE via PBKDF2-HMAC-SHA256 (static salt, 600k
iterations). Asset lives on release tag "auto-backup" in BACKUP_REPO.
Auth: RESTORE_TOKEN (repo scope).
"""
import base64
import gzip
import io
import json
import os
import sys
import urllib.request
import urllib.error

DB = "/data/harith.db"
TAG = "auto-backup"
ASSET = "rafiq-latest.db.gz.fenc"
SALT = b"rafiq-rolling-backup-v1"
ITER = 600_000


def repo():
    return os.environ.get("BACKUP_REPO", "ALHARITH1/rafiq-backup")


def token():
    return os.environ["RESTORE_TOKEN"]


def api(method, url, body=None, raw=None, accept="application/vnd.github+json"):
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", f"Bearer {token()}")
    req.add_header("Accept", accept)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    elif raw is not None:
        data = raw
        req.add_header("Content-Type", "application/octet-stream")
    try:
        with urllib.request.urlopen(req, data=data, timeout=300) as r:
            payload = r.read()
            if accept == "application/octet-stream":
                return payload
            return json.loads(payload or b"{}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def fernet():
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    pw = os.environ["BACKUP_PASSPHRASE"].encode()
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=SALT, iterations=ITER)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(pw)))


def get_release(create=False):
    rel = api("GET", f"https://api.github.com/repos/{repo()}/releases/tags/{TAG}")
    if rel is None and create:
        rel = api("POST", f"https://api.github.com/repos/{repo()}/releases",
                  body={"tag_name": TAG, "name": TAG, "prerelease": True,
                        "body": "Rolling latest backup written by the Rafiq container."})
    return rel


def find_asset(rel):
    for a in rel.get("assets", []):
        if a.get("name") == ASSET:
            return a
    return None


def push():
    if not os.path.exists(DB):
        print("[backup] no database file, skipping push", flush=True)
        return
    with open(DB, "rb") as f:
        plain = f.read()
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as g:
        g.write(plain)
    enc = fernet().encrypt(buf.getvalue())
    rel = get_release(create=True)
    old = find_asset(rel)
    if old:
        api("DELETE", f"https://api.github.com/repos/{repo()}/releases/assets/{old['id']}")
    up = api("POST",
             f"https://uploads.github.com/repos/{repo()}/releases/{rel['id']}/assets?name={ASSET}",
             raw=enc)
    print(f"[backup] pushed {len(enc)} bytes as {up.get('name')} (id {up.get('id')})", flush=True)


def restore():
    if os.path.exists(DB) and os.path.getsize(DB) > 0:
        print("[backup] database present, no restore", flush=True)
        return
    rel = get_release()
    asset = find_asset(rel) if rel else None
    if asset:
        print("[backup] restoring from rolling encrypted asset...", flush=True)
        enc = api("GET", f"https://api.github.com/repos/{repo()}/releases/assets/{asset['id']}",
                  accept="application/octet-stream")
        plain = fernet().decrypt(enc)
        data = gzip.decompress(plain)
    else:
        url = os.environ.get("RESTORE_ASSET_URL", "")
        if not url:
            print("[backup] no rolling asset and no RESTORE_ASSET_URL; starting empty", flush=True)
            return
        print("[backup] restoring from initial plain asset...", flush=True)
        data = gzip.decompress(api("GET", url, accept="application/octet-stream"))
    tmp = "/data/.harith.db.tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.chmod(tmp, 0o600)
    os.replace(tmp, DB)
    print(f"[backup] restore done ({len(data)} bytes)", flush=True)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "restore"
    if mode == "push":
        push()
    elif mode == "restore":
        restore()
    else:
        print(f"unknown mode {mode}", file=sys.stderr)
        sys.exit(2)
