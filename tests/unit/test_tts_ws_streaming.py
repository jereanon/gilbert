"""Tests for TTSService WebSocket streaming handlers and helpers."""

import asyncio
import base64
from collections.abc import AsyncIterator
from contextlib import suppress

import pytest

from gilbert.core.services.tts import TTSService, _event_to_json
from gilbert.interfaces.tts import (
    AudioFormat,
    StreamingTTSCapability,
    SynthesisRequest,
    SynthesisResult,
    TTSAudioChunk,
    TTSBackend,
    TTSFlushed,
    TTSStreamError,
    TTSWordTiming,
    Voice,
)


def test_event_to_json_audio_chunk_uses_base64():
    ev = TTSAudioChunk(audio=b"\x00\x01\x02")
    j = _event_to_json(ev, AudioFormat.MP3)
    assert j == {
        "type": "audio",
        "audio_b64": base64.b64encode(b"\x00\x01\x02").decode(),
        "format": "mp3",
    }


def test_event_to_json_word_timing():
    ev = TTSWordTiming(word="hi", start_seconds=0.10, end_seconds=0.30)
    assert _event_to_json(ev, AudioFormat.MP3) == {
        "type": "word",
        "word": "hi",
        "start_seconds": 0.10,
        "end_seconds": 0.30,
    }


def test_event_to_json_flushed():
    assert _event_to_json(TTSFlushed(at_seconds=2.5), AudioFormat.MP3) == {
        "type": "flushed",
        "at_seconds": 2.5,
    }


def test_event_to_json_error():
    assert _event_to_json(TTSStreamError("oops", recoverable=True), AudioFormat.MP3) == {
        "type": "error",
        "message": "oops",
        "recoverable": True,
    }


def test_event_to_json_unknown_returns_unknown_type():
    # Defensive: pass an arbitrary object that's not a TTSEvent variant.
    class _Other:
        pass
    assert _event_to_json(_Other(), AudioFormat.MP3) == {"type": "unknown"}


# ---------------------------------------------------------------------------
# WS handler helpers
# ---------------------------------------------------------------------------

class _OneshotBackend(TTSBackend):
    """Backend that yields three audio chunks on synthesize_stream.

    No ``backend_name`` — keeps the global registry clean across tests."""

    chunks_to_emit = [b"AAA", b"BBB", b"CCC"]

    async def initialize(self, config): pass
    async def close(self): pass
    async def synthesize(self, request):
        return SynthesisResult(audio=b"".join(self.chunks_to_emit), format=request.output_format)
    async def list_voices(self):
        return []
    async def get_voice(self, voice_id):
        return None

    def synthesize_stream(self, request: SynthesisRequest) -> AsyncIterator[bytes]:
        chunks = list(self.chunks_to_emit)

        async def _gen():
            for c in chunks:
                yield c

        return _gen()


def _make_svc_with_oneshot_backend() -> TTSService:
    svc = TTSService()
    svc._backend = _OneshotBackend()
    svc._backend_name = "_oneshot_ws_test"
    svc._enabled = True
    svc._silence_padding = 0.0
    return svc


class _FakeConn:
    def __init__(self, conn_id: str = "c1", user_id: str = "u1"):
        self.connection_id = conn_id
        self._user_id = user_id
        self.enqueued: list[dict] = []
        self.close_cbs: list = []

    @property
    def user_id(self) -> str:
        return self._user_id

    def enqueue(self, msg):
        self.enqueued.append(msg)

    def add_close_callback(self, cb):
        self.close_cbs.append(cb)


@pytest.mark.asyncio
async def test_start_stream_oneshot_pumps_audio_and_end():
    svc = _make_svc_with_oneshot_backend()
    conn = _FakeConn()

    res = await svc._handle_start_stream(conn, {
        "type": "tts.start_stream",
        "mode": "oneshot",
        "format": "mp3",
        "voice_id": "v1",
        "text": "hello world",
    })
    assert "session_id" in res
    session_id = res["session_id"]

    # Drain the pump task.
    sess = svc._sessions[session_id]
    assert sess.pump_task is not None
    await sess.pump_task

    events = [m for m in conn.enqueued if m.get("type") == "tts.event"]
    assert len(events) == 4  # 3 audio + 1 end
    assert all(m["session_id"] == session_id for m in events)
    assert [e["event"]["type"] for e in events] == ["audio", "audio", "audio", "end"]
    audio_b64s = [base64.b64decode(e["event"]["audio_b64"]) for e in events[:3]]
    assert audio_b64s == [b"AAA", b"BBB", b"CCC"]
    # Session is cleaned up after pump finishes.
    assert session_id not in svc._sessions


@pytest.mark.asyncio
async def test_start_stream_oneshot_capability_error_emits_error_event_and_cleans_up():
    svc = TTSService()
    # Batch-only backend: lacks StreamingTTSCapability.
    class _BatchOnly(TTSBackend):
        async def initialize(self, config): pass
        async def close(self): pass
        async def synthesize(self, request):
            return SynthesisResult(audio=b"", format=request.output_format)
        async def list_voices(self): return []
        async def get_voice(self, vid): return None

    svc._backend = _BatchOnly()
    svc._backend_name = "_batch_only_ws_test"
    svc._enabled = True

    conn = _FakeConn()
    res = await svc._handle_start_stream(conn, {
        "type": "tts.start_stream",
        "mode": "oneshot",
        "format": "mp3",
        "voice_id": "v1",
        "text": "hello",
    })
    # Pre-pump capability check happens *inside* the pump, so the
    # handler still returns a session_id; the error surfaces as a
    # tts.event with type=error.
    session_id = res["session_id"]
    await svc._sessions[session_id].pump_task
    error_events = [
        m for m in conn.enqueued
        if m.get("type") == "tts.event" and m["event"]["type"] == "error"
    ]
    assert len(error_events) == 1
    assert "_batch_only_ws_test" in error_events[0]["event"]["message"]
    assert session_id not in svc._sessions
