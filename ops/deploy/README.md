# Zero-downtime (blue-green) deploys

Deploys and `.env` recreates swap the running app container without dropping a
request. Host nginx proxies to a `lsp_app` upstream that points at whichever
**color** is live; a deploy starts the idle color, health-checks it, flips the
upstream with a graceful `nginx -s reload`, then stops the old color.

```
/etc/nginx/conf.d/lsp-active.conf   upstream lsp_app { server 127.0.0.1:8001; }   # 8001<->8002
host nginx (lsp.conf)  ──►  proxy_pass http://lsp_app  ──►  web_blue  :8001 (active)
   / and /ws/                                                web_green :8002 (idle, stopped)
                                   both share: redis (Channels) + lsp-private-media volume
```

## Files (host is the source of truth)

The scripts run on the EC2 host; the copies here are version-controlled
reference. Keep them in sync when you change either.

| Repo (reference)                     | Host (authoritative)                       |
|--------------------------------------|--------------------------------------------|
| `ops/deploy/deploy.sh`               | `~/bin/deploy.sh` (0755)                    |
| `ops/deploy/lsp-activate-color`      | `/usr/local/bin/lsp-activate-color` (root:root, 0755) |
| `ops/deploy/lsp-active.conf.example` | `/etc/nginx/conf.d/lsp-active.conf` (helper-managed) |
| `ops/deploy/lsp.conf.snippet`        | the proxy_pass lines in `/etc/nginx/conf.d/lsp.conf` |
| `ops/deploy/sudoers.d-lsp-deploy`    | `/etc/sudoers.d/lsp-deploy` (root:root, 0440) |
| `ops/deploy/lsp-web-exec`            | `/usr/local/bin/lsp-web-exec` (root:root, 0755) |
| —                                    | `~/lsp-website/.active-color` (state: `blue`/`green`) |

Because the active container name alternates (`lsp-website-web_blue-1` ↔
`web_green-1`), anything that `docker exec`s the app — notably the host systemd
timer services — must resolve the live color via `lsp-web-exec python manage.py
<cmd>`, never a hardcoded name.

`compose.yml` (in the repo) defines `web_blue` (:8001) and `web_green` (:8002)
plus shared `redis`; the deploy script always targets one color by name.

## Everyday use

- **Normal deploy:** push to `main`. GitHub Actions runs tests, then triggers
  `~/bin/deploy.sh` on the host via SSM. Zero downtime.
- **`.env`-only change** (no code): edit `~/lsp-website/.env`, then
  `SKIP_GIT=1 ~/bin/deploy.sh`. Recreates the idle color so it re-reads the env
  file, then flips. (Replaces `docker compose up -d --force-recreate`, which 502s.)
- **Rollback a deploy:** `sudo /usr/local/bin/lsp-activate-color <old-port>` and
  `docker compose up -d web_<old-color>` — instant revert (the old image is still
  present until the next `docker image prune`).

## Operational constraints

- **Backward-compatible migrations.** During the flip both code versions briefly
  run against the already-migrated DB (the new color migrates before it reports
  healthy). Keep migrations additive; split destructive changes (drop/rename) into
  two deploys — first ship code that no longer uses the column, then a later deploy
  that drops it.
- **WebSockets** (Parlêtre chat, notification bell) on the old color persist on its
  daphne until they close; new connections hit the new color. Both share Redis, so
  fan-out stays consistent and clients reconnect seamlessly.
- A **failed `/healthz`** aborts the deploy before the flip — the old color keeps
  serving, so a bad build means no downtime (and a non-zero SSM/GHA result).

## First-time bootstrap (one-time, zero-downtime)

Run from the current single-`web` (:8000) state:

1. `nginx`: add `lsp-active.conf` with `server 127.0.0.1:8000;`, change the two
   `proxy_pass` in `lsp.conf` to `http://lsp_app`, `nginx -t && nginx -s reload`
   (still hitting the old `web` — no downtime).
2. Install `/usr/local/bin/lsp-activate-color`, `/etc/sudoers.d/lsp-deploy`
   (`visudo -c`), and the new `~/bin/deploy.sh`.
3. Land the repo changes on `main` (new `compose.yml` + `/healthz`). The
   GHA-triggered new `deploy.sh` builds `web_blue` on :8001, health-checks, flips
   :8000→:8001, then stops the legacy container.
4. `docker compose rm -f web` to clear the now-orphaned single-container service.
