#!/bin/sh
# Make the data directory usable, then drop privileges and run the server.
#
# A bind-mounted folder belongs to whoever created it on the host — on a NAS
# that is usually root — so an unprivileged container can't write to it. This
# starts as root just long enough to hand the folder to the app user, then
# gives up root for good.
#
# PUID/PGID override the user the app runs as, for anyone who would rather
# match an existing account than have the folder re-owned.
set -e

DATA_DIR="${DATA_DIR:-/data}"
APP_UID="${PUID:-1000}"
APP_GID="${PGID:-1000}"

if [ "$(id -u)" != "0" ]; then
  # Already unprivileged (someone set `user:` in compose) — nothing to do,
  # and nothing we could do: chown needs root.
  exec "$@"
fi

mkdir -p "$DATA_DIR"

# Only take ownership when the app user can't already write there. A
# recursive chown across a folder of photos is slow, and pointless if the
# permissions are fine already.
if ! setpriv --reuid "$APP_UID" --regid "$APP_GID" --clear-groups \
     sh -c '[ -w "$1" ]' sh "$DATA_DIR" 2>/dev/null; then
  echo "entrypoint: $DATA_DIR is not writable by ${APP_UID}:${APP_GID} — taking ownership"
  chown -R "$APP_UID:$APP_GID" "$DATA_DIR" \
    || echo "entrypoint: could not change ownership of $DATA_DIR; the server will report if it can't write"
fi

exec setpriv --reuid "$APP_UID" --regid "$APP_GID" --clear-groups "$@"
