# Off-region logical database backup

These files install a **weekly `pg_dump`** of the production database to
`s3://lsp-db-backups-useast1/` (us-east-1 — a different region from everything
else). This is the *portable* backup: a `pg_restore`-able, inspectable file you
can open on a laptop or load into any Postgres, in a region that survives a
us-west-2 event. It complements — does not replace — RDS automated snapshots +
PITR (us-west-2, 30-day retention) and the manual pre-migration snapshots.

Like the other host timers (`lsp-dues-cron.timer`, etc.), these live **only on
the EC2 host**, not in the running container. The copies here are the
version-controlled source of truth — install them by hand.

## One-time install (on the host)

SSH in (`ssh lsp`) and:

```bash
# 1. Script
mkdir -p ~/bin
# copy ops/backups/lsp-db-backup.sh from the repo to ~/bin/lsp-db-backup.sh
chmod +x ~/bin/lsp-db-backup.sh

# 2. systemd units
sudo cp lsp-db-backup.service lsp-db-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now lsp-db-backup.timer

# 3. Verify schedule + run once on demand
systemctl list-timers lsp-db-backup.timer
sudo systemctl start lsp-db-backup.service   # fire immediately
journalctl -u lsp-db-backup.service --no-pager | tail
aws s3 ls s3://lsp-db-backups-useast1/lsp-db/ --region us-east-1
```

Prereqs already true on this host: `docker` present, `aws` CLI v2 present
(AL2023 default), instance profile `lsp-ec2-ssm-role` attached. The script
pulls `postgres:16` on first run to get a matching `pg_dump`.

## IAM permission (REQUIRED — must be granted once, off-host)

The instance role needs S3 write to the backup bucket. This was **not** applied
automatically (IAM changes need explicit human authorization). Run from a
workstation with the `lsp` profile:

```bash
cat > /tmp/lsp-db-backup-s3.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "DbBackupBucketWrite",
    "Effect": "Allow",
    "Action": ["s3:PutObject", "s3:GetObject", "s3:ListBucket"],
    "Resource": [
      "arn:aws:s3:::lsp-db-backups-useast1",
      "arn:aws:s3:::lsp-db-backups-useast1/*"
    ]
  }]
}
JSON
aws --profile lsp iam put-role-policy \
  --role-name lsp-ec2-ssm-role \
  --policy-name lsp-db-backup-s3-write \
  --policy-document file:///tmp/lsp-db-backup-s3.json
```

Until this is attached, the upload step fails with `AccessDenied` (the dump
itself still succeeds).

## Restore

See `docs/backup-and-recovery.md` for the full recovery runbook (RDS PITR,
snapshot restore, and restoring one of these `pg_dump` files).
