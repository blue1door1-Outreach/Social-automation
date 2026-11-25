"""Buffer API client (GraphQL).

Verified against the official docs at https://developers.buffer.com on
2026-11-23:

* endpoint            https://api.buffer.com
* auth header         Authorization: Bearer <API key>
* API key             https://publish.buffer.com/settings/api
* organizations       ``account { organizations { id name } }``
* channels            ``channels(input: { organizationId })``
* create post         ``createPost(input: { text, channelId, schedulingType,
                      mode, dueAt, assets: [{ image: { url } }] })``

Buffer fetches the image when the post publishes, not when it is created, so
the URL must stay publicly reachable. That is why ``main`` verifies the exact
bytes before queueing.

Two failure kinds are kept apart on purpose:

* ``BufferError`` - Buffer clearly rejected the request. Safe to report.
* ``BufferUncertain`` - timeout, 5xx or connection reset. The post may or may
  not exist. Never retry automatically; record "unknown" and check the queue.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import requests

LOG = logging.getLogger("khuje.buffer")

API_URL = "https://api.buffer.com"
ALLOWED_MODES = ("addToQueue", "customScheduled", "shareNow", "shareNext")


class BufferError(RuntimeError):
    pass


class BufferUncertain(BufferError):
    """The request outcome is unknown; a blind retry could double-post."""


class BufferClient:
    def __init__(
        self,
        token: str,
        endpoint: str = API_URL,
        session: requests.Session | None = None,
        timeout: int = 30,
    ):
        if not token:
            raise BufferError("missing Buffer API key")
        self.token = token
        self.endpoint = endpoint.rstrip("/")
        self.session = session or requests.Session()
        self.timeout = timeout

    def _graphql(self, query: str) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        try:
            response = self.session.post(
                self.endpoint, json={"query": query}, headers=headers, timeout=self.timeout
            )
        except requests.Timeout as exc:
            raise BufferUncertain(f"timeout calling Buffer: {exc}") from exc
        except requests.RequestException as exc:
            raise BufferUncertain(f"connection error calling Buffer: {exc}") from exc

        if response.status_code >= 500:
            raise BufferUncertain(f"Buffer returned {response.status_code}")
        if response.status_code in (401, 403):
            raise BufferError(
                f"Buffer rejected the API key ({response.status_code}). "
                "Create a new key at https://publish.buffer.com/settings/api"
            )
        if response.status_code >= 400:
            raise BufferError(f"Buffer returned {response.status_code}: {(response.text or '')[:300]}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise BufferError(f"Buffer returned non-JSON: {exc}") from exc

        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            messages = [
                str(error.get("message", "")).strip()
                for error in errors
                if isinstance(error, dict)
            ]
            raise BufferError("; ".join(message for message in messages if message) or "Buffer GraphQL error")

        data = payload.get("data")
        if not isinstance(data, dict):
            raise BufferError("Buffer returned no data")
        return data

    def organizations(self) -> list[dict[str, Any]]:
        data = self._graphql("{ account { organizations { id name } } }")
        account = data.get("account") or {}
        rows = account.get("organizations") or []
        return [row for row in rows if isinstance(row, dict) and row.get("id")]

    def default_organization_id(self) -> str:
        organizations = self.organizations()
        if not organizations:
            raise BufferError("this Buffer account has no organizations")
        return str(organizations[0]["id"])

    def channels(self, organization_id: str | None = None) -> list[dict[str, Any]]:
        org_id = organization_id or self.default_organization_id()
        query = (
            "query { channels(input: { organizationId: "
            f"{json.dumps(str(org_id))}"
            " }) { id name service } }"
        )
        data = self._graphql(query)
        rows = data.get("channels") or []
        return [row for row in rows if isinstance(row, dict)]

    def create_update(
        self,
        channel_id: str,
        text: str,
        image_url: str,
        mode: str = "addToQueue",
        due_at: str | None = None,
        service: str = "",
    ) -> dict[str, Any]:
        if mode not in ALLOWED_MODES:
            raise BufferError(f"unsupported Buffer mode {mode!r}")
        if not image_url:
            raise BufferError("create_update needs a public image URL")

        effective_mode = "customScheduled" if due_at else mode
        due_clause = f"dueAt: {json.dumps(due_at)}" if due_at else ""
        metadata = ""
        if service == "facebook":
            metadata = "metadata: { facebook: { type: post } }"
        elif service == "instagram":
            metadata = "metadata: { instagram: { type: post, shouldShareToFeed: true } }"
        query = f"""
mutation CreatePost {{
  createPost(input: {{
    text: {json.dumps(text)}
    channelId: {json.dumps(channel_id)}
    schedulingType: automatic
    mode: {effective_mode}
    {due_clause}
    {metadata}
    assets: [{{ image: {{ url: {json.dumps(image_url)} }} }}]
  }}) {{
    ... on PostActionSuccess {{ post {{ id dueAt }} }}
    ... on MutationError {{ message }}
  }}
}}
"""
        data = self._graphql(query)
        result = data.get("createPost")
        if not isinstance(result, dict):
            raise BufferError("unexpected createPost payload from Buffer")
        message = result.get("message")
        if message:
            raise BufferError(f"Buffer rejected the post: {message}")

        post = result.get("post") or {}
        if not post.get("id"):
            raise BufferError("Buffer returned no post id")
        return {"id": str(post["id"]), "due_at": post.get("dueAt"), "mode": effective_mode}


def verify_channels(channels: list[dict[str, Any]], expected: dict[str, str]) -> list[str]:
    """Return human-readable problems with the configured channel ids."""
    problems: list[str] = []
    by_id = {str(channel.get("id")): channel for channel in channels}
    for target, channel_id in expected.items():
        channel = by_id.get(channel_id)
        if channel is None:
            problems.append(f"{target}: channel id {channel_id} not found in this Buffer account")
            continue
        service = str(channel.get("service", "")).lower()
        if service != target:
            problems.append(f"{target}: channel {channel_id} is a {service or 'unknown'} channel")
    return problems
