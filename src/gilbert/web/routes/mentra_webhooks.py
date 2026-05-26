"""HTTP webhook endpoint Mentra Cloud talks to.

One route — ``POST /api/mentra/webhook``. Mentra Cloud POSTs a
``session_request`` when a user launches the Gilbert Mentra app from
their phone, and a ``stop_request`` when they (or the system) stop
it. The route just resolves the ``mentra_webhook`` capability off
the live Gilbert app and hands the JSON to it.

All carrier-specific parsing (the websocket URL aliases, the
StopRequestReason enum, etc.) lives in the plugin so the route
stays plugin-agnostic. Same pattern as ``telnyx_webhooks.py`` and
the various carrier message webhooks.

Important: Mentra retries non-2xx responses, so we return 200
unconditionally with a status field. ``status=error`` lets the
operator notice the misconfiguration without making the cloud
back off and lose subsequent webhooks.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request

from gilbert.interfaces.mentra import MentraWebhookEndpoint, WebhookResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mentra")


def _get_endpoint(state: Any) -> MentraWebhookEndpoint | None:
    """Resolve the ``mentra_webhook`` capability off the live Gilbert
    app. Returns ``None`` if the Mentra plugin isn't registered.
    """
    gilbert = getattr(state, "gilbert", None)
    if gilbert is None:
        return None
    svc = gilbert.service_manager.get_capability("mentra_webhook")
    if svc is None or not isinstance(svc, MentraWebhookEndpoint):
        return None
    return svc


@router.post("/webhook")
async def mentra_webhook(request: Request) -> dict[str, str]:
    """Receive a Mentra Cloud webhook (session_request /
    stop_request).

    Always returns 200 with a status field — the cloud retries on
    non-2xx and we'd rather log a transient bug than back up
    Mentra's queue.
    """
    endpoint = _get_endpoint(request.app.state)
    if endpoint is None:
        logger.warning(
            "Mentra webhook arrived but plugin isn't loaded"
        )
        return WebhookResponse(
            status="error",
            message="mentra plugin not loaded",
        ).to_dict()

    try:
        payload = await request.json()
    except Exception:
        logger.warning("Mentra webhook with non-JSON body")
        return WebhookResponse(
            status="error", message="non-JSON body"
        ).to_dict()

    if not isinstance(payload, dict):
        logger.warning(
            "Mentra webhook with non-object JSON body: type=%s",
            type(payload).__name__,
        )
        return WebhookResponse(
            status="error", message="JSON body must be an object"
        ).to_dict()

    try:
        result = await endpoint.deliver_webhook_event(payload)
    except Exception:
        logger.exception("Mentra webhook dispatch raised")
        return WebhookResponse(
            status="error", message="dispatch raised"
        ).to_dict()

    # Normalize the response — the endpoint contract says
    # ``WebhookResponse``, but defend against a plugin returning
    # something else.
    if isinstance(result, WebhookResponse):
        return result.to_dict()
    return WebhookResponse(status="success").to_dict()
