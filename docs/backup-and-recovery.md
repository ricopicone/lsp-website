# Backup &amp; recovery runbook

What is backed up, where, how long it's kept, and exactly how to restore it.
Last reviewed 2026-06-05.

## At a glance

| Data | Primary store | Backup mechanism | Retention | Region / account |
|---|---|---|---|---|
| **Code + static content** | GitHub `ricopicone/lsp-website` | git history | forever | GitHub (off-AWS) |
| **Database** | RDS `lsp-db` (Postgres 16) | automated snapshots + PITR | **30 days** | us-west-2 |
| " | " | manual snapshots (pre-migration) | until deleted | us-west-2 |
| " | " | **weekly `pg_dump` → S3** | 365 days | **us-east-1** (off-region) |
| **Public media** (headshots, covers) | S3 `lsp-website-media-uswest2` | bucket **versioning** | noncurrent 90d | us-west-2 |
| **Private files** (gated PDFs, CVs, attachments) | S3 `lsp-website-private-uswest2` | bucket versioning | noncurrent 365d | us-west-2 |
| **Video recordings** | S3 `lsp-website-recordings-uswest2` | bucket versioning | noncurrent 7d; app-enforced 1yr | us-west-2 |

Deletion protection is **on** for `lsp-db`. All buckets and the DB are
encrypted at rest.

## Restoring the database

### A. Roll back to a point in time (corruption caught within 30 days) — PITR

This is the normal "we broke the data" recovery. RDS continuously archives
transaction logs, so you can restore to **any second** in the retention window.
It creates a **new** instance — it never overwrites the live one.

```bash
aws --profile lsp --region us-west-2 rds restore-db-instance-to-point-in-time \
  --source-db-instance-identifier lsp-db \
  --target-db-instance-identifier lsp-db-restore \
  --restore-time 2026-06-05T17:45:00Z \
  --db-subnet-group-name <same-subnet-group-as-lsp-db> \
  --vpc-security-group-ids <same-sg-as-lsp-db> \
  --no-multi-az
```

Find the valid window: `LatestRestorableTime` / earliest from
`aws rds describe-db-instances --db-instance-identifier lsp-db`.

Then verify the restored instance (connect, spot-check the corrupted rows), and
cut over by pointing `DATABASE_URL` in the host `~/lsp-website/.env` at the new
endpoint and redeploying — **or** rename instances (rename `lsp-db` →
`lsp-db-old`, `lsp-db-restore` → `lsp-db`) so the connection string is unchanged.
Reuse the same subnet group + security group as the original (see the
`aws-infra` memory) so the app can reach it.

### B. Restore a specific snapshot (e.g. a pre-migration manual snapshot)

```bash
aws --profile lsp --region us-west-2 rds describe-db-snapshots \
  --db-instance-identifier lsp-db --query 'reverse(sort_by(DBSnapshots,&SnapshotCreateTime))[].DBSnapshotIdentifier'

aws --profile lsp --region us-west-2 rds restore-db-instance-from-db-snapshot \
  --db-instance-identifier lsp-db-restore \
  --db-snapshot-identifier lsp-db-pre-workgroups-foldin-20260531 \
  --db-subnet-group-name <subnet-group> --vpc-security-group-ids <sg> --no-multi-az
```

Then verify + cut over as in A.

**Take a manual snapshot before any risky migration or bulk data change:**

```bash
aws --profile lsp --region us-west-2 rds create-db-snapshot \
  --db-instance-identifier lsp-db \
  --db-snapshot-identifier lsp-db-pre-<change>-$(date -u +%Y%m%d)
```

### C. Restore from the portable `pg_dump` (off-region, or migrating off RDS)

Use when us-west-2 / RDS itself is the problem, when you need the data outside
AWS, or to restore a *subset* of tables. These live in
`s3://lsp-db-backups-useast1/lsp-db/` (custom format, `pg_restore`-able).

```bash
# pick a dump
aws --profile lsp --region us-east-1 s3 ls s3://lsp-db-backups-useast1/lsp-db/
aws --profile lsp --region us-east-1 s3 cp \
  s3://lsp-db-backups-useast1/lsp-db/lsp-db-2026-06-07T09-00-00Z.dump ./restore.dump

# inspect without restoring (table of contents)
pg_restore --list ./restore.dump | less

# full restore into a fresh database
createdb lsp_restore
pg_restore --no-owner --no-privileges --dbname=lsp_restore ./restore.dump

# or one table only:
pg_restore --no-owner --no-privileges --dbname=lsp_restore --table=payments_payment ./restore.dump
```

No local Postgres? Run it in Docker:
`docker run --rm -e DATABASE_URL=... -v "$PWD:/w" postgres:16 sh -c 'pg_restore --no-owner --no-privileges -d "$DATABASE_URL" /w/restore.dump'`.

## Restoring media / files / recordings

Versioning is on for all three buckets, so an overwrite or delete leaves a
recoverable prior version.

```bash
# list every version of a key (current + noncurrent), newest first
aws --profile lsp --region us-west-2 s3api list-object-versions \
  --bucket lsp-website-media-uswest2 --prefix headshots/jane-doe

# a deleted object shows a DeleteMarker as its current version — remove the
# marker to "undelete":
aws --profile lsp --region us-west-2 s3api delete-object \
  --bucket lsp-website-media-uswest2 --key headshots/jane-doe.webp \
  --version-id <delete-marker-version-id>

# or pull a specific old version out to a file:
aws --profile lsp --region us-west-2 s3api get-object \
  --bucket lsp-website-media-uswest2 --key headshots/jane-doe.webp \
  --version-id <version-id> recovered.webp
```

Headshots are additionally re-derivable: `Profile.headshot_original` holds the
uncropped upload, and the 512² WebP is regenerated from it on save.

## Recovery objectives (current posture)

- **RPO (max data loss):** DB ≈ 5 min (PITR); media/files = 0 within the
  versioning window; off-region portable copy ≤ 7 days old.
- **RTO (time to restore):** DB ≈ 20–40 min (provision restored instance + cut
  over); media = minutes.

## Known residual risk

Everything except the GitHub mirror lives in **one AWS account**
(`493980123073`). The us-east-1 `pg_dump` bucket gives region diversity, but a
root-account compromise or account-level loss could still reach it. A true
off-account / off-AWS copy (a second AWS account with a replication policy, or a
periodic pull to non-AWS storage) is the next hardening step if the threat model
warrants it. Optional intermediate step: enable **RDS cross-region automated
backup replication** to keep PITR-capable snapshots in a second region:

```bash
aws --profile lsp --region us-east-1 rds start-db-instance-automated-backups-replication \
  --source-db-instance-arn arn:aws:rds:us-west-2:493980123073:db:lsp-db \
  --backup-retention-period 14 \
  --kms-key-id <us-east-1 KMS key>   # encrypted source needs a destination-region key
```

## See also

- `ops/backups/README.md` — install the weekly `pg_dump` timer on the host.
- `aws-infra` memory — VPC, subnet group, security group IDs, RDS endpoint.
- `host-cron-timers` memory — the other host systemd timers.
