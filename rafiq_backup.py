#!/usr/bin/env python3
"""Rafiq rolling backup helper (container-side).

Modes:
  restore  if /data/harith.db is missing, fetch the latest encrypted rolling
           backup asset and decrypt+gunzip it into place; fall back to the
           original plain-gzip asset at RESTORE_ASSET_URL. Also restores the
           /data/files archive when the files dir is empty.
  push     gzip+encrypt /data/harith.db and upload it as the rolling asset.
           Also archives /data/files into a separate encrypted rolling asset,
           but only when the files manifest changed since the last push.

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
FILES_DIR = os.path.join(os.environ.get("HARITH_DATA_DIR", "/data"), "files")
ASSET_FILES = "rafiq-files-latest.tar.gz.fenc"
MANIFEST_NAME = ".manifest.json"
SALT = b"rafiq-rolling-backup-v2"
ITER = 100_000
SALT_V1 = b"rafiq-rolling-backup-v1"
ITER_V1 = 600_000


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


def fernet(salt=SALT, iterations=ITER):
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    pw = os.environ["BACKUP_PASSPHRASE"].encode()
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(pw)))


def decrypt_any(enc):
    from cryptography.fernet import InvalidToken
    try:
        return fernet().decrypt(enc)
    except InvalidToken:
        return fernet(SALT_V1, ITER_V1).decrypt(enc)


def get_release(create=False):
    rel = api("GET", f"https://api.github.com/repos/{repo()}/releases/tags/{TAG}")
    if rel is None and create:
        rel = api("POST", f"https://api.github.com/repos/{repo()}/releases",
                  body={"tag_name": TAG, "name": TAG, "prerelease": True,
                        "body": "Rolling latest backup written by the Rafiq container."})
    return rel


def find_asset(rel, name=ASSET):
    for a in rel.get("assets", []):
        if a.get("name") == name:
            return a
    return None


def push():
    try:
        os.nice(10)
    except Exception:
        pass
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
    files_push(rel)


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
        plain = decrypt_any(enc)
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


def files_manifest():
    """Map relpath -> [size, mtime_ns] for every file under FILES_DIR."""
    import os.path as p
    man = {}
    if not p.isdir(FILES_DIR):
        return man
    for root, dirs, names in os.walk(FILES_DIR):
        for n in names:
            if n == MANIFEST_NAME:
                continue
            full = p.join(root, n)
            rel = p.relpath(full, FILES_DIR)
            try:
                st = os.stat(full)
            except OSError:
                continue
            man[rel] = [st.st_size, st.st_mtime_ns]
    return man


def files_archive():
    """Build tar.gz of FILES_DIR (plus its manifest) and encrypt it."""
    import tarfile
    man = files_manifest()
    man_path = os.path.join(FILES_DIR, MANIFEST_NAME)
    with open(man_path, "w") as f:
        json.dump(man, f)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel in sorted(man):
            tar.add(os.path.join(FILES_DIR, rel), arcname=os.path.join("files", rel))
        tar.add(man_path, arcname=os.path.join("files", MANIFEST_NAME))
    return fernet().encrypt(buf.getvalue()), len(man)


def files_push(rel=None):
    """Upload the files archive only when the manifest changed."""
    if not os.path.isdir(FILES_DIR):
        return
    man = files_manifest()
    if not man:
        print("[backup] files dir empty, skipping files push", flush=True)
        return
    man_path = os.path.join(FILES_DIR, MANIFEST_NAME)
    old = None
    if os.path.exists(man_path):
        try:
            with open(man_path) as f:
                old = json.load(f)
        except Exception:
            old = None
    if old == man:
        print(f"[backup] files unchanged ({len(man)} files), skipping files push", flush=True)
        return
    enc, n = files_archive()
    if rel is None:
        rel = get_release(create=True)
    oldasset = find_asset(rel, ASSET_FILES)
    if oldasset:
        api("DELETE", f"https://api.github.com/repos/{repo()}/releases/assets/{oldasset['id']}")
    up = api("POST",
             f"https://uploads.github.com/repos/{repo()}/releases/{rel['id']}/assets?name={ASSET_FILES}",
             raw=enc)
    print(f"[backup] pushed files archive: {n} files, {len(enc)} bytes as {up.get('name')}", flush=True)


def files_restore():
    """Restore FILES_DIR from the encrypted archive when it is empty."""
    if os.path.isdir(FILES_DIR) and any(True for _ in os.scandir(FILES_DIR)):
        print("[backup] files dir present, no files restore", flush=True)
        return
    rel = get_release()
    asset = find_asset(rel, ASSET_FILES) if rel else None
    if not asset:
        print("[backup] no files archive asset; nothing to restore", flush=True)
        return
    print("[backup] restoring files archive...", flush=True)
    enc = api("GET", f"https://api.github.com/repos/{repo()}/releases/assets/{asset['id']}",
              accept="application/octet-stream")
    plain = decrypt_any(enc)
    import tarfile
    base = os.path.dirname(FILES_DIR.rstrip("/")) or "/"
    os.makedirs(FILES_DIR, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(plain), mode="r:gz") as tar:
        tar.extractall(base, filter="data")
    n = sum(len(names) for _, _, names in os.walk(FILES_DIR))
    print(f"[backup] files restore done ({n} files)", flush=True)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "restore"
    if mode == "push":
        push()
    elif mode == "files-push":
        files_push()
    elif mode == "restore":
        restore()
        try:
            files_restore()
        except Exception as e:
            print(f"[backup] files restore failed: {e}", flush=True)
    else:
        print(f"unknown mode {mode}", file=sys.stderr)
        sys.exit(2)
