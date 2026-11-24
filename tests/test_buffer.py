from __future__ import annotations

import json

import pytest
import requests

from src.buffer_client import BufferClient, BufferError, BufferUncertain, verify_channels


class FakeResponse:
    def __init__(self, status: int = 200, payload=None, text: str | None = None):
        self.status_code = status
        self._payload = payload if payload is not None else {}
        self.text = text if text is not None else json.dumps(self._payload)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, response: FakeResponse | Exception):
        self.response = response
        self.calls: list[dict] = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(
            {"url": url, "json": json, "headers": headers, "timeout": timeout}
        )
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def success(payload):
    return FakeResponse(payload={"data": payload})


def test_create_update_sends_graphql_mutation() -> None:
    session = FakeSession(
        success({"createPost": {"post": {"id": "post_1", "dueAt": None}}})
    )
    client = BufferClient("token-123456", session=session)  # type: ignore[arg-type]

    payload = client.create_update(
        "chan_1", "hello", image_url="https://example.com/a.png"
    )

    assert payload["id"] == "post_1"
    assert len(session.calls) == 1
    call = session.calls[0]
    assert call["url"] == "https://api.buffer.com"
    assert call["headers"]["Authorization"] == "Bearer token-123456"
    query = call["json"]["query"]
    assert "createPost" in query
    assert 'channelId: "chan_1"' in query
    assert 'mode: addToQueue' in query
    assert "https://example.com/a.png" in query
    assert "dueAt:" not in query


def test_due_at_switches_to_custom_scheduling() -> None:
    session = FakeSession(
        success({"createPost": {"post": {"id": "post_2", "dueAt": "2026-11-24T04:00:00Z"}}})
    )
    client = BufferClient("token-123456", session=session)  # type: ignore[arg-type]

    payload = client.create_update(
        "chan_1",
        "hello",
        image_url="https://example.com/a.png",
        due_at="2026-11-24T04:00:00Z",
    )

    query = session.calls[0]["json"]["query"]
    assert "mode: customScheduled" in query
    assert 'dueAt: "2026-11-24T04:00:00Z"' in query
    assert payload["due_at"] == "2026-11-24T04:00:00Z"


def test_typed_mutation_error_is_definite() -> None:
    session = FakeSession(success({"createPost": {"message": "Channel not found"}}))
    client = BufferClient("token-123456", session=session)  # type: ignore[arg-type]

    with pytest.raises(BufferError) as info:
        client.create_update("chan_1", "hello", image_url="https://example.com/a.png")
    assert not isinstance(info.value, BufferUncertain)
    assert "Channel not found" in str(info.value)
    assert "token-123456" not in str(info.value)


def test_graphql_errors_are_definite() -> None:
    session = FakeSession(
        FakeResponse(payload={"errors": [{"message": "Invalid input"}], "data": None})
    )
    client = BufferClient("token-123456", session=session)  # type: ignore[arg-type]

    with pytest.raises(BufferError) as info:
        client.create_update("chan_1", "hello", image_url="https://example.com/a.png")
    assert not isinstance(info.value, BufferUncertain)
    assert "Invalid input" in str(info.value)


def test_rejected_key_points_at_settings_page() -> None:
    session = FakeSession(FakeResponse(status=401, text="unauthorized"))
    client = BufferClient("token-123456", session=session)  # type: ignore[arg-type]

    with pytest.raises(BufferError) as info:
        client.create_update("chan_1", "hello", image_url="https://example.com/a.png")
    assert not isinstance(info.value, BufferUncertain)
    assert "publish.buffer.com/settings/api" in str(info.value)
    assert "token-123456" not in str(info.value)


def test_timeout_is_uncertain() -> None:
    session = FakeSession(requests.Timeout("timed out"))
    client = BufferClient("token-123456", session=session)  # type: ignore[arg-type]
    with pytest.raises(BufferUncertain):
        client.create_update("chan_1", "hello", image_url="https://example.com/a.png")


def test_server_error_is_uncertain() -> None:
    session = FakeSession(FakeResponse(status=503, text="unavailable"))
    client = BufferClient("token-123456", session=session)  # type: ignore[arg-type]
    with pytest.raises(BufferUncertain):
        client.create_update("chan_1", "hello", image_url="https://example.com/a.png")


def test_image_url_is_required() -> None:
    client = BufferClient("token-123456", session=FakeSession(FakeResponse()))  # type: ignore[arg-type]
    with pytest.raises(BufferError):
        client.create_update("chan_1", "hello", image_url="")


def test_organizations_are_listed() -> None:
    session = FakeSession(
        success({"account": {"organizations": [{"id": "org_1", "name": "Khuje Nao"}]}})
    )
    client = BufferClient("token-123456", session=session)  # type: ignore[arg-type]
    assert client.organizations() == [{"id": "org_1", "name": "Khuje Nao"}]
    assert "organizations" in session.calls[0]["json"]["query"]


def test_channels_use_the_configured_organization() -> None:
    session = FakeSession(
        success({"channels": [{"id": "fb1", "name": "Page", "service": "facebook"}]})
    )
    client = BufferClient("token-123456", session=session)  # type: ignore[arg-type]
    channels = client.channels("org_1")
    assert channels == [{"id": "fb1", "name": "Page", "service": "facebook"}]
    assert 'organizationId: "org_1"' in session.calls[0]["json"]["query"]


def test_verify_channels_detects_mismatch() -> None:
    channels = [
        {"id": "fb1", "service": "facebook"},
        {"id": "ig1", "service": "instagram"},
    ]
    assert verify_channels(channels, {"facebook": "fb1", "instagram": "ig1"}) == []
    problems = verify_channels(channels, {"facebook": "ig1", "instagram": "ig1"})
    assert problems and "facebook" in problems[0]
    missing = verify_channels(channels, {"facebook": "missing", "instagram": "ig1"})
    assert "not found" in missing[0]
