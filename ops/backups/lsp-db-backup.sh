#!/usr/bin/env bash
#
# Weekly logical (pg_dump) backup of the production database to an off-region
# S3 bucket. Complements RDS automated snapshots + PITR (which are us-west-2,
# same-account, RDS-proprietary) with a portable, inspectable, engine-independent
# copy in a different region.
#
# Runs on the EC2 host (Amazon Linux 2023) via lsp-db-backup.timer.
# Requires: docker (for the postgres client image) and aws-cli v2 (ships with
# AL2023; uses the instance profile lsp-ec2-ssm-role for S3 credentials).
#
# Install: see ops/backups/README.md.
set -euo pipefail

ENV_FILE="${LSP_ENV_FILE:-/home/ec2-user/lsp-website/.env}"
BUCKET="${LSP_BACKUP_BUCKET:-lsp-db-backups-useast1}"
REGION="${LSP_BACKUP_REGION:-us-east-1}"
PG_IMAGE="${LSP_PG_IMAGE:-postgres:16}"

if [ ! -r "$ENV_FILE" ]; then
  echo "FATAL: cannot read $ENV_FILE" >&2
  exit 1
fi

# Pull DATABASE_URL out of the host .env without echoing it anywhere.
DATABASE_URL="$(grep -E '^DATABASE_URL=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
if [ -z "${DATABASE_URL:-}" ]; then
  echo "FATAL: DATABASE_URL not found in $ENV_FILE" >&2
  exit 1
fi

TS="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
KEY="lsp-db/lsp-db-${TS}.dump"
TMP="$(mktemp /tmp/lsp-db-backup.XXXXXX.dump)"
trap 'rm -f "$TMP"' EXIT

# Custom format (-Fc): compressed, restored with pg_restore, lets you restore a
# subset of tables. --no-owner/--no-privileges make it portable to any cluster.
# The connection string is passed via the container env (not argv) so it does
# not appear in the container's process list or `docker inspect`.
docker run --rm -e DATABASE_URL="$DATABASE_URL" "$PG_IMAGE" \
  sh -c 'pg_dump --format=custom --no-owner --no-privileges -d "$DATABASE_URL"' > "$TMP"

# Sanity-check the artifact before we trust it. pg_dump custom format starts
# with the magic bytes "PGDMP".
if [ ! -s "$TMP" ]; then
  echo "FATAL: dump is empty" >&2
  exit 1
fi
if [ "$(head -c 5 "$TMP")" != "PGDMP" ]; then
  echo "FATAL: dump does not start with PGDMP magic; aborting upload" >&2
  exit 1
fi

SIZE="$(wc -c < "$TMP" | tr -d ' ')"
aws s3 cp "$TMP" "s3://${BUCKET}/${KEY}" \
  --region "$REGION" \
  --only-show-errors \
  --metadata "source=lsp-db,host=$(hostname),bytes=${SIZE}"

echo "OK: uploaded s3://${BUCKET}/${KEY} (${SIZE} bytes)"
