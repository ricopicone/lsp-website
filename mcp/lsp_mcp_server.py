"""LSP web-developer admin — MCP server.

A thin stdio MCP server that exposes the site's dev API (``/devapi/``) as tools a
Claude Code session can call directly. It closes the suggestion-box loop: instead
of running ``manage.py export_suggestions`` and reading markdown files, a session
lists the live queue, reads a suggestion (with the view + URL name that owns its
page already resolved), and marks it done as it ships the fix.

All capability lives server-side in tested Django views; this process only adds
HTTP plumbing. It authenticates as a real user via a bearer token, so it can
never do more than that user could in the web UI.

Run it via the project's MCP config (see mcp/README.md):

    uv run --group mcp python mcp/lsp_mcp_server.py

Environment:
    LSP_DEVAPI_URL    Base site URL (default https://app.lacanschool.org)
    LSP_DEVAPI_TOKEN  Bearer token from `manage.py create_devapi_token` (required)
"""

from __future__ import annotations

import os

import httpx
from mcp.server.fastmcp import FastMCP

BASE_URL = os.environ.get("LSP_DEVAPI_URL", "https://app.lacanschool.org").rstrip("/")
TOKEN = os.environ.get("LSP_DEVAPI_TOKEN", "")
TIMEOUT = 30.0

mcp = FastMCP("lsp-admin")


def _client() -> httpx.Client:
    if not TOKEN:
        raise RuntimeError(
            "LSP_DEVAPI_TOKEN is not set. Mint one with "
            "`uv run python manage.py create_devapi_token --user <email> --label <name>` "
            "and set it in the MCP server's environment."
        )
    return httpx.Client(
        base_url=f"{BASE_URL}/devapi/",
        headers={"Authorization": f"Bearer {TOKEN}"},
        timeout=TIMEOUT,
    )


def _call(method: str, path: str, **kwargs) -> dict:
    """Make a request and normalise errors into a plain dict the model can read."""
    try:
        with _client() as client:
            resp = client.request(method, path, **kwargs)
    except RuntimeError as exc:
        return {"error": str(exc)}
    except httpx.HTTPError as exc:
        return {"error": f"request failed: {exc}"}
    if resp.status_code >= 400:
        detail = ""
        try:
            detail = resp.json().get("error", "")
        except ValueError:
            detail = resp.text[:200]
        return {"error": f"HTTP {resp.status_code}: {detail or resp.reason_phrase}"}
    try:
        return resp.json()
    except ValueError:
        return {"error": "non-JSON response from server"}


@mcp.tool()
def whoami() -> dict:
    """Check connectivity and report which user + staff roles the token acts as.

    Use this first to confirm the server is reachable and authorized.
    """
    return _call("GET", "whoami/")


@mcp.tool()
def list_suggestions(
    status: str | None = None,
    kind: str | None = None,
    priority: str | None = None,
    since: str | None = None,
    limit: int = 50,
) -> dict:
    """List member suggestions, newest first.

    Args:
        status: A status value (new, acknowledged, planned, in_progress, done,
            declined) or "open" for the actionable set (new/acknowledged/
            planned/in_progress).
        kind: bug, content, feature, design, or other.
        priority: low, medium, or high.
        since: Only suggestions created on/after this date (YYYY-MM-DD).
        limit: Max rows (default 50, capped at 200).

    Returns a dict with "count" and "results" (compact suggestion summaries).
    """
    params = {"limit": limit}
    if status:
        params["status"] = status
    if kind:
        params["kind"] = kind
    if priority:
        params["priority"] = priority
    if since:
        params["since"] = since
    return _call("GET", "suggestions/", params=params)


@mcp.tool()
def get_suggestion(id: int) -> dict:
    """Get one suggestion in full, including the member's description, browser
    context, and the Django view + URL name that owns the page it's about
    (resolved server-side, so you know where to look in the code)."""
    return _call("GET", f"suggestions/{id}/")


@mcp.tool()
def update_suggestion(
    id: int,
    status: str | None = None,
    priority: str | None = None,
    staff_notes: str | None = None,
) -> dict:
    """Triage a suggestion: set its status, priority, and/or staff notes.

    Stamps you as the reviewer and notifies the submitter when the status
    changes — the same effect as a human using the triage page. Send at least
    one field. Returns the updated suggestion.

    Args:
        status: new, acknowledged, planned, in_progress, done, or declined.
        priority: low, medium, high, or "" to clear.
        staff_notes: Internal triage notes (not shown to the submitter).
    """
    payload: dict = {}
    if status is not None:
        payload["status"] = status
    if priority is not None:
        payload["priority"] = priority
    if staff_notes is not None:
        payload["staff_notes"] = staff_notes
    if not payload:
        return {"error": "send at least one of: status, priority, staff_notes"}
    return _call("POST", f"suggestions/{id}/", json=payload)


@mcp.tool()
def suggestion_stats() -> dict:
    """Counts of suggestions by status and by kind, plus the open total — a quick
    read on the size and shape of the triage queue."""
    return _call("GET", "suggestions/stats/")


if __name__ == "__main__":
    mcp.run()
