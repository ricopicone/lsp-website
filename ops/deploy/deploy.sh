#!/bin/bash
# LSP website deploy — blue-green, zero-downtime.
#
# The AUTHORITATIVE copy lives on the EC2 host at ~/bin/deploy.sh; this file
# (ops/deploy/) is a version-controlled reference — keep them in sync (see
# ops/deploy/README.md). Triggered by GitHub Actions via SSM (runs as ec2-user),
# or manually on the host:
#   ~/bin/deploy.sh              # pull main + deploy new code (zero downtime)
#   SKIP_GIT=1 ~/bin/deploy.sh   # recreate the idle color to pick up .env changes
#
# Mechanism: build + start the idle color (blue:8001 / green:8002) alongside the
# live one, wait for /healthz, flip the nginx `lsp_app` upstream with a graceful
# reload, then stop the old color. A failed health check aborts BEFORE the flip,
# so a broken build causes no downtime — the old color keeps serving.
set -euo pipefail

REPO=/home/ec2-user/lsp-website
HOST=app.lacanschool.org
STATE="$REPO/.active-color"
cd "$REPO"

if [ "${SKIP_GIT:-0}" != 1 ]; then
  git fetch --depth 1 origin main
  git reset --hard origin/main
fi

active=$(cat "$STATE" 2>/dev/null || echo none)
if [ "$active" = blue ]; then
  new=green; nport=8002; oldsvc=web_blue
else
  new=blue;  nport=8001; oldsvc=web_green
fi
newsvc="web_$new"
echo "active=$active -> deploying $newsvc on :$nport"

# Build + start the idle color; the live color keeps serving throughout.
sg docker -c "docker compose up -d --build $newsvc"

# Wait for readiness. The container CMD runs `migrate` before daphne listens, so
# a 200 here means migrated + serving + DB reachable. Headers make the probe pass
# ALLOWED_HOSTS and skip the http->https redirect.
ready=0; code=000
for _ in $(seq 1 60); do
  code=$(curl -s -o /dev/null -w '%{http_code}' \
    -H "Host: $HOST" -H 'X-Forwarded-Proto: https' \
    "http://127.0.0.1:$nport/healthz" || true)
  if [ "$code" = 200 ]; then ready=1; break; fi
  sleep 1
done
if [ "$ready" != 1 ]; then
  echo "ERROR: $newsvc failed /healthz (last code=$code) — NOT flipping; old color still serving" >&2
  sg docker -c "docker compose stop $newsvc" || true
  exit 1
fi

# Flip nginx to the new color (graceful reload — no dropped connections), record state.
sudo /usr/local/bin/lsp-activate-color "$nport"
echo "$new" > "$STATE"
echo "flipped traffic to $newsvc (:$nport)"

# Drain the old color and reclaim the now-dangling image.
sg docker -c "docker compose stop $oldsvc" || true
sg docker -c "docker image prune -f" || true

# Bound the BuildKit cache. Nothing pruned it before, and on 2026-07-31 it
# reached 22.6GB on a 20GB disk and failed a deploy mid-build ("No space left on
# device"); blue-green meant no outage, but no fix could ship either. A size cap
# rather than `--filter until=`: the cap bounds the disk, which is the thing that
# actually breaks, whatever the deploy rate. 3GB holds roughly five deploys'
# worth of layers, so incremental rebuilds stay fast. Runs after the flip, so a
# failed build keeps its cache.
# `--reserved-space`, not the older `--keep-storage`: the latter still works on
# Docker 25 but prints a deprecation notice saying it has been renamed.
sg docker -c "docker builder prune -f --reserved-space 3GB" || true

# Report disk on every deploy. The cache grew past the size of the whole disk
# with nothing ever saying so; make the next creeping problem visible early.
df -h / | tail -1
sg docker -c "docker system df" || true
echo "deploy done."
