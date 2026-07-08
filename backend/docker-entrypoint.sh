#!/bin/sh
set -e

# The /data bind mount is host-managed and often created root-owned by Docker
# before the app container ever runs; fix ownership here (as root, before
# dropping to the unprivileged "app" user) rather than requiring the host to
# pre-chown it, since that's an easy step to forget.
mkdir -p /data
chown -R app:app /data

exec gosu app "$@"
