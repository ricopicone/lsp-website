# AWS account resilience &amp; backup-account plan

**Status: NOT YET IMPLEMENTED — blocked on shared-email control.** Rico does not
yet control an LSP shared mailbox / distribution list to use as the backup
account's root email. Do this once that exists. Drafted 2026-06-05.

Goal: protect against two failure modes that the current single-account setup
does not cover —

1. **Lockout** — rico loses access to the prod AWS account (lost/compromised
   credentials, account suspension, lost root email or MFA).
2. **Bus factor** — rico is permanently unavailable; someone else must reach the
   backups and run the restore.

Both want the same thing: **backups in an account whose fate is independent of
the prod account, reachable by a second person.** Lockout stresses *independent
recovery*; bus factor stresses *ownership + documentation*.

## Root vs IAM — both, for different jobs

| Layer | Job | Why it matters here |
|---|---|---|
| **Root** | Owns the account; a handful of account-level actions (close account, change payment, some break-glass). Locked down, used ~never. | The **ultimate recovery key**. Its email + MFA must be recoverable by a *second person* — that's what saves both scenarios. |
| **IAM / Identity Center** | Day-to-day access; what the EC2 role and humans use. | A **second IAM/SSO admin principal** gives the bus-factor person normal access without ever touching root. |

**Anti-pattern to avoid:** backup-account root email = a personal inbox, MFA =
only one phone. That recreates both single points of failure.

## Recommended setup

### 1. Dedicated backup account with independent, shared recovery
- Root email = **LSP distribution list / shared mailbox** (≥2 officers receive
  it), never a personal inbox. **← this is the current blocker.**
- Its **own payment method** (an LSP card), not tied to the prod account billing.
- **Two hardware MFA keys** on root (AWS root supports up to 8): one with rico,
  one in a safe / with a board officer or the treasurer.
- Root password + recovery kit in a **shared vault with emergency/legacy access**
  (1Password Emergency Kit, Bitwarden Emergency Access, or a sealed envelope in
  the LSP safe).

### 2. Make the backups un-deletable even from a compromised prod account
- Backup-account S3 bucket with **versioning + Object Lock** (Governance or
  Compliance mode) — write-once-read-many; ransomware or a rogue actor in prod
  cannot erase history. **Object Lock must be enabled at/near bucket creation**
  (for an existing bucket: recreate + migrate).
- Grant the prod EC2 role (`lsp-ec2-ssm-role` in account `493980123073`)
  cross-account `s3:PutObject` to that bucket; repoint the weekly `pg_dump` (and
  optionally a media `s3 sync`) at it.
- For RDS: copy snapshots cross-account, or use **AWS Backup** cross-account copy.

### 3. Org relationship — the one real trade-off

| Option | Lockout resilience | Bus factor / governance | Effort |
|---|---|---|---|
| **Standalone** separate account (own org) | ✅ Best — fully independent fate | ⚠️ hand-managed | Low |
| Member account under an **AWS Organization** rico/LSP owns | ⚠️ shares fate with the *management* account | ✅ central SSO, backup policies, easy 2nd admin | Medium |

**Recommendation:** lean **standalone backup account** for max independence,
*unless* centralized governance is wanted later (more accounts, staff access) —
then stand up an Organization with the **management account owned by LSP** (shared
root mailbox) and prod + backup as members.

## Do-now items that don't need a second account (current-account exposure)
These are the *actual* lockout/bus risks on the prod account today; worth closing
independently of account #2:
- **Audit the prod account's own root recovery:** is its root email a shared
  mailbox? Is there a second root MFA device? If both are rico-only, the prod
  account is exposed in both scenarios regardless of backups.
- **Add Object Lock + versioning to the existing `lsp-db-backups-useast1`
  bucket** so the dumps can't be wiped by an attacker who gets into prod.
  (Object Lock needs enabling at/near creation → quick recreate + migrate.)

## Execution checklist (when the shared mailbox exists)
- [ ] Create LSP shared mailbox / distribution list for AWS root email.
- [ ] Create backup AWS account (standalone) with that root email + LSP payment.
- [ ] Register 2 hardware MFA keys on root; distribute (rico + safe/officer).
- [ ] Store root creds in shared vault with emergency access to a 2nd person.
- [ ] Create backup-account S3 bucket with versioning + Object Lock.
- [ ] Cross-account bucket policy granting prod `lsp-ec2-ssm-role` PutObject.
- [ ] Repoint `ops/backups/lsp-db-backup.sh` (or add a second target) at it.
- [ ] (Optional) AWS Backup cross-account copy for RDS snapshots.
- [ ] (Optional, now) Recreate `lsp-db-backups-useast1` with Object Lock; audit
      prod root email/MFA.
- [ ] Document the break-glass procedure (who, what creds, where) in this file.

## What Claude can / can't do
- **Can't** create an AWS account (needs a human: email + payment + agreement).
- **Can**, once the account exists and a role/credentials are provided: wire the
  cross-account bucket policy + Object Lock, repoint the `pg_dump` job, set up
  AWS Backup copy. Can also, anytime: add Object Lock to the current bucket and
  audit prod-account root posture.

See `docs/backup-and-recovery.md` for the existing (single-account) backup
posture this plan hardens.
