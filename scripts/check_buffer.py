"""Print the Buffer organizations and channels visible to your API key.

Creates nothing. Run this before enabling queueing.

    Copy-Item .env.example .env    # then fill BUFFER_API_KEY
    python scripts/check_buffer.py

Copy the facebook and instagram channel ids into BUFFER_CHANNEL_FB /
BUFFER_CHANNEL_IG, and the organization id into BUFFER_ORGANIZATION_ID.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.buffer_client import BufferClient, BufferError  # noqa: E402
from src.env_file import load_env_file  # noqa: E402

ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def _configure_console() -> None:
    """Channel names can be non-ASCII; do not crash on a legacy code page."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def _clean_id(value: str) -> str:
    """Reject obvious copy/paste damage such as 'abc123 name=My organization'."""
    value = value.strip().strip("'\"")
    if value and not ID_PATTERN.match(value):
        return ""
    return value


def main() -> int:
    _configure_console()
    load_env_file(ROOT / ".env")
    token = (os.environ.get("BUFFER_API_KEY") or os.environ.get("BUFFER_ACCESS_TOKEN") or "").strip()
    if not token:
        print("BUFFER_API_KEY is not set", file=sys.stderr)
        return 2

    client = BufferClient(token, timeout=20)
    try:
        organizations = client.organizations()
    except BufferError as exc:
        print(f"Buffer request failed: {exc}", file=sys.stderr)
        return 1

    if not organizations:
        print("No organizations returned. Create a Buffer account and connect channels first.")
        return 1

    raw_org = os.environ.get("BUFFER_ORGANIZATION_ID", "").strip()
    configured_org = _clean_id(raw_org)
    if raw_org and not configured_org:
        print(
            f"Warning: BUFFER_ORGANIZATION_ID looks malformed ({raw_org!r}); "
            "use the id only. Falling back to the first organization.",
            file=sys.stderr,
        )

    organization_ids = {str(o.get("id")) for o in organizations}
    if configured_org and configured_org not in organization_ids:
        print(
            f"Warning: BUFFER_ORGANIZATION_ID {configured_org} is not in this account; "
            "falling back to the first organization.",
            file=sys.stderr,
        )
        configured_org = ""

    print("Organizations:")
    for organization in organizations:
        marker = " <- configured" if str(organization.get("id")) == configured_org else ""
        print(f"  id={organization.get('id')} name={organization.get('name')}{marker}")

    org_id = configured_org or str(organizations[0]["id"])
    try:
        channels = client.channels(org_id)
    except BufferError as exc:
        print(f"Channel request failed: {exc}", file=sys.stderr)
        return 1

    if not channels:
        print("No channels in this organization. Connect Facebook and Instagram in Buffer first.")
        return 1

    print(f"\nChannels for organization {org_id}:")
    found = 0
    for channel in channels:
        service = str(channel.get("service", "")).lower()
        if service in ("facebook", "instagram"):
            found += 1
        paused = " (queue paused)" if channel.get("isQueuePaused") else ""
        print(f"  {service:10} id={channel.get('id')} name={channel.get('name')}{paused}")

    if not found:
        print("\nNo facebook or instagram channels found.", file=sys.stderr)
        return 1

    print("\nPut these in .env:")
    print(f"  BUFFER_ORGANIZATION_ID={org_id}")
    for channel in channels:
        service = str(channel.get("service", "")).lower()
        if service == "facebook":
            print(f"  BUFFER_CHANNEL_FB={channel.get('id')}")
        elif service == "instagram":
            print(f"  BUFFER_CHANNEL_IG={channel.get('id')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
