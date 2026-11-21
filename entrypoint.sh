#!/bin/sh
# Rafiq container entrypoint: restore DB once, run server, back up on stop and periodically.
set -e

python /usr/local/bin/rafiq_backup.py restore || echo "[entrypoint] restore failed, continuing"

# periodic safety backup every 6h (covers crashes that skip the TERM trap)
if [ -n "$RESTORE_TOKEN" ] && [ -n "$BACKUP_PASSPHRASE" ]; then
  ( while true; do sleep 21600; python /usr/local/bin/rafiq_backup.py push || true; done ) &
  LOOP_PID=$!
fi

python -m harith run &
SRV_PID=$!

shutdown() {
  echo "[entrypoint] stopping: pushing final backup..."
  if [ -n "$RESTORE_TOKEN" ] && [ -n "$BACKUP_PASSPHRASE" ]; then
    python /usr/local/bin/rafiq_backup.py push || true
  fi
  kill -TERM "$SRV_PID" 2>/dev/null || true
  wait "$SRV_PID" 2>/dev/null || true
  [ -n "$LOOP_PID" ] && kill "$LOOP_PID" 2>/dev/null || true
  exit 0
}
trap shutdown TERM INT

wait "$SRV_PID"
