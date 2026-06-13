# LSP web-developer admin — MCP server

A small [MCP](https://modelcontextprotocol.io) server that lets a Claude Code
session manage the LSP site through the dev API (`/devapi/`). It closes the
suggestion-box loop: instead of `manage.py export_suggestions` → read markdown
files, a session reads the **live** queue and marks items done as it ships them.

```
Claude Code  ──stdio──>  mcp/lsp_mcp_server.py  ──HTTPS + bearer token──>  app.lacanschool.org/devapi/
   (tools)               (thin httpx client)                              (tested Django views)
```

All capability lives server-side in `devapi/` (versioned, tested). This process
only adds HTTP plumbing. It authenticates as a **real user** via a bearer token,
so it can never do more than that user could in the web UI.

## Tools

| Tool | What it does |
|---|---|
| `whoami` | Connectivity + identity check — which user/roles the token acts as. Run first. |
| `list_suggestions` | The triage queue, newest first. Filters: `status` (or `open`), `kind`, `priority`, `since`, `limit`. |
| `get_suggestion` | One suggestion in full — incl. the **view + URL name that owns its page**, resolved server-side. |
| `update_suggestion` | Triage: set `status` / `priority` / `staff_notes`. Stamps you as reviewer + notifies the submitter on status change. |
| `suggestion_stats` | Counts by status and kind, plus the open total. |

## Setup

1. **Mint a token** (once), bound to a user holding the Web Coordinator or Web
   Developer staff role (or a superuser). On the host, or locally against the dev
   DB:

   ```
   uv run python manage.py create_devapi_token --user dr@ricopic.one --label "rico laptop — Claude Code"
   ```

   It prints the raw token **once** (`lspdev_…`). Copy it.

2. **Give the token to the server** (it's never committed). The server reads
   `LSP_DEVAPI_TOKEN` from the environment, falling back to a gitignored dotenv
   file — so you don't have to re-export it in every shell or tmux pane. Pick one:

   - **A file (recommended, survives across worktrees):**

     ```
     mkdir -p ~/.config/lsp-mcp
     printf 'LSP_DEVAPI_TOKEN=lspdev_…\n' >> ~/.config/lsp-mcp/.env
     ```

     The server also reads the repo-root `.env` (alongside Django's), or any path
     in `LSP_DEVAPI_ENV_FILE`. An exported env var always wins over a file.

   - **A shell export** (one pane / one session, or add to `~/.zshrc` to persist):

     ```
     export LSP_DEVAPI_TOKEN="lspdev_…"
     ```

   `LSP_DEVAPI_URL` is optional (defaults to `https://app.lacanschool.org`); set
   it — env or dotenv — to `http://localhost:8000` to work against a local dev
   server instead.

3. **Use it.** `.mcp.json` registers the server for this repo; Claude Code starts
   it on demand. Run `whoami` to confirm it's wired up.

### Codex and Projects MCP gotcha

The `LSP_DEVAPI_TOKEN` file above is for this repo's local `lsp-admin` stdio
server only. It does not configure the separate remote `projects-direct` MCP
server in `~/.codex/config.toml`.

For `projects-direct`, use either a real exported environment variable name in
`bearer_token_env_var`, or a static header under
`[mcp_servers.projects-direct.http_headers]`. Do not put the token value itself
in `bearer_token_env_var`; Codex treats that value as the name of an environment
variable and startup fails with "Environment variable ... is not set." If a
static `Authorization = "Bearer ..."` header is present, omit
`bearer_token_env_var`.

## Notes

- The `mcp` + `httpx` deps live in the `mcp` dependency group (`uv run --group
  mcp …`), so they stay out of the Docker image and CI — this server is a
  laptop-only tool.
- Kill switch: `DJANGO_DEVAPI_ENABLED=false` in the host `.env` disables
  `/devapi/` entirely (503), independent of the suggestion-box feature flag.
- Revoke a token from the Django admin (Dev API tokens → check *revoked*); the
  hash-only storage means a leaked DB row can't reconstruct the token.

## Roadmap

The dev API is built to grow into a broader admin surface — likely next:
site health / deploy status, `manage.py check --deploy`, member + registration
lookups, and a treasurer/referral-queue read model. New capability = a new
tested `devapi` endpoint + a thin tool here.
