"""Public routes that expose the server's TLS certificate.

These are intentionally **unauthenticated** — a user can't log in
to Gilbert until they've trusted the cert, so the routes that
bootstrap that trust must be reachable without a session. Only
the public half (the cert PEM) and metadata are served; the
private key is never touched here.

The corresponding allowlist entries live in ``gilbert.web.auth``.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter(prefix="/api/tls", tags=["tls"])


def _tls_info(request: Request) -> Any:
    info = getattr(request.app.state, "tls_info", None)
    if info is None:
        raise HTTPException(status_code=404, detail="TLS disabled")
    return info


@router.get("/cert.crt")
async def download_cert(request: Request) -> FileResponse:
    info = _tls_info(request)
    if not info.cert_path.exists():
        raise HTTPException(status_code=404, detail="cert file missing")
    return FileResponse(
        path=str(info.cert_path),
        media_type="application/x-x509-ca-cert",
        filename="gilbert.crt",
    )


@router.get("/info")
async def get_info(request: Request) -> JSONResponse:
    info = _tls_info(request)
    return JSONResponse(
        {
            "san": list(info.san_entries),
            "not_valid_after": info.not_valid_after.isoformat(),
            "sha256_fingerprint": info.sha256_fingerprint,
        }
    )
