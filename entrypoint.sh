#!/bin/sh
# Rafiq container entrypoint: one-time DB restore, then run the server.
set -e
DB=/data/harith.db
if [ ! -s "$DB" ] && [ -n "$RESTORE_ASSET_URL" ]; then
  echo "[entrypoint] restoring database from private release asset..."
  python - <<'PY'
import os, sys, urllib.request, gzip, shutil
url = os.environ["RESTORE_ASSET_URL"]
tok = os.environ.get("RESTORE_TOKEN", "")
req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}", "Accept": "application/octet-stream"})
with urllib.request.urlopen(req, timeout=120) as r, open("/tmp/restore.db.gz", "wb") as f:
    shutil.copyfileobj(r, f)
with gzip.open("/tmp/restore.db.gz", "rb") as g, open("/tmp/harith.db", "wb") as f:
    shutil.copyfileobj(g, f)
shutil.move("/tmp/harith.db", "/data/harith.db")
os.chmod("/data/harith.db", 0o600)
print("[entrypoint] restore done")
PY
fi
exec python -m harith run
