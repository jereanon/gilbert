"""End-to-end HTTPS boot test."""
from __future__ import annotations

import asyncio
import socket
import ssl
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI

from gilbert.core.tls import ensure_self_signed_cert


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@asynccontextmanager  # type: ignore[arg-type]
async def _running_server(cert_path: Path, key_path: Path, port: int) -> None:  # type: ignore[misc]
    app = FastAPI()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        ssl_certfile=str(cert_path),
        ssl_keyfile=str(key_path),
    )
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None  # type: ignore[attr-defined]
    task = asyncio.create_task(server.serve())
    for _ in range(50):
        if server.started:
            break
        await asyncio.sleep(0.05)
    assert server.started, "uvicorn HTTPS server failed to start"
    try:
        yield
    finally:
        server.should_exit = True
        await task


async def test_https_listener_serves_traffic(tmp_path: Path) -> None:
    cert_path = tmp_path / "tls.crt"
    key_path = tmp_path / "tls.key"
    ensure_self_signed_cert(cert_path, key_path)
    port = _free_port()

    async with _running_server(cert_path, key_path, port):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        async with httpx.AsyncClient(verify=ctx) as client:
            resp = await client.get(f"https://127.0.0.1:{port}/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
