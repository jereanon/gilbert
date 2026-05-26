"""Tests for ``POST /api/mentra/webhook``.

Same routing pattern as the Telnyx webhook routes — the route is a
thin dispatcher that resolves the ``mentra_webhook`` capability off
the live Gilbert app and hands the JSON payload to it. The
capability provider (the Mentra plugin's ``MentraService``) is what
parses the payload and decides how to react.

All states return 200; the body's ``status`` field carries the
outcome. Mentra Cloud retries non-2xx responses, so we cover every
branch with explicit ``status=error`` rather than letting a stack
trace leak as a 500.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gilbert.interfaces.mentra import WebhookResponse
from gilbert.web.routes.mentra_webhooks import router as mentra_router


class _CapableEndpoint:
    """Stub that satisfies the ``MentraWebhookEndpoint`` Protocol
    (the runtime_checkable shape is one async method)."""

    def __init__(self) -> None:
        self.delivered: list[dict[str, Any]] = []
        self.raise_on_deliver = False
        self.response = WebhookResponse(status="success")

    async def deliver_webhook_event(
        self, payload: dict[str, object]
    ) -> WebhookResponse:
        if self.raise_on_deliver:
            raise RuntimeError("simulated dispatch error")
        self.delivered.append(dict(payload))
        return self.response


def _make_app(endpoint: Any | None) -> FastAPI:
    """Stand up a minimal FastAPI app with the Mentra router mounted
    against a stub service manager."""
    app = FastAPI()

    class _SM:
        def get_capability(self, name: str) -> Any:
            if name == "mentra_webhook":
                return endpoint
            return None

    app.state.gilbert = SimpleNamespace(service_manager=_SM())
    app.include_router(mentra_router)
    return app


def test_webhook_dispatches_session_request_to_capability() -> None:
    endpoint = _CapableEndpoint()
    client = TestClient(_make_app(endpoint))

    payload = {
        "type": "session_request",
        "sessionId": "sess_001",
        "userId": "alice@example.com",
        "timestamp": "2099-01-01T00:00:00Z",
        "websocketUrl": "wss://cloud.mentra.glass/app-ws",
    }
    response = client.post("/api/mentra/webhook", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert endpoint.delivered == [payload]


def test_webhook_returns_no_plugin_when_capability_absent() -> None:
    """If the Mentra plugin isn't loaded the capability is missing —
    return ``status=error`` rather than 500ing."""
    client = TestClient(_make_app(None))

    response = client.post(
        "/api/mentra/webhook",
        json={
            "type": "session_request",
            "sessionId": "x",
            "userId": "x",
            "timestamp": "x",
            "websocketUrl": "ws://x",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert "not loaded" in body["message"]


def test_webhook_returns_error_on_non_json_body() -> None:
    """Mentra Cloud sometimes retries with garbage when its own state
    is bad — we still return 200 so the cloud doesn't back off."""
    endpoint = _CapableEndpoint()
    client = TestClient(_make_app(endpoint))

    response = client.post(
        "/api/mentra/webhook",
        content=b"not json",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert endpoint.delivered == []


def test_webhook_returns_error_on_dispatch_raise() -> None:
    """If the plugin's handler crashes mid-dispatch we still 200 —
    the cloud retries on non-2xx and we'd rather log + recover."""
    endpoint = _CapableEndpoint()
    endpoint.raise_on_deliver = True
    client = TestClient(_make_app(endpoint))

    response = client.post(
        "/api/mentra/webhook",
        json={
            "type": "session_request",
            "sessionId": "x",
            "userId": "x",
            "timestamp": "x",
            "websocketUrl": "ws://x",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert "dispatch raised" in body["message"]


def test_webhook_forwards_capability_error_response() -> None:
    """A capability that returns ``status=error`` (e.g. unknown user)
    has its response forwarded verbatim — the route doesn't
    second-guess the plugin's decision."""
    endpoint = _CapableEndpoint()
    endpoint.response = WebhookResponse(
        status="error", message="no Gilbert user mapping configured"
    )
    client = TestClient(_make_app(endpoint))

    response = client.post(
        "/api/mentra/webhook",
        json={
            "type": "session_request",
            "sessionId": "sess_x",
            "userId": "unknown@example.com",
            "timestamp": "2099-01-01T00:00:00Z",
            "websocketUrl": "ws://x",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert "mapping" in body["message"]


def test_webhook_returns_error_on_non_object_json() -> None:
    """JSON arrays / strings / numbers at the top level can't be a
    webhook payload — refuse cleanly."""
    endpoint = _CapableEndpoint()
    client = TestClient(_make_app(endpoint))

    response = client.post("/api/mentra/webhook", json=["not", "object"])
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert "object" in body["message"].lower()
