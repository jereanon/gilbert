"""Tests for TTSService streaming capability checks and behavior."""

from collections.abc import AsyncIterator

import pytest

from gilbert.core.services.tts import TTSService
from gilbert.interfaces.tts import (
    AudioFormat,
    StreamingTTSCapability,
    SynthesisRequest,
    SynthesisResult,
    TTSBackend,
    TTSCapabilityError,
    Voice,
)


class _BatchOnlyBackend(TTSBackend):
    """Implements only the abstract TTSBackend surface.

    Deliberately NOT setting ``backend_name`` so ``__init_subclass__``
    doesn't pollute the global ``TTSBackend._registry`` for the rest
    of the test session. ``svc._backend_name`` is set on the fixture
    instead — that's what error messages reference."""

    async def initialize(self, config): pass
    async def close(self): pass
    async def synthesize(self, request):
        return SynthesisResult(audio=b"FULL", format=request.output_format)
    async def list_voices(self):
        return []
    async def get_voice(self, voice_id):
        return None


class _StreamingBackend(_BatchOnlyBackend):
    """Adds StreamingTTSCapability."""

    def __init__(self) -> None:
        super().__init__()
        self.chunks: list[bytes] = [b"AAA", b"BBB", b"CCC"]

    def synthesize_stream(self, request: SynthesisRequest) -> AsyncIterator[bytes]:
        chunks = self.chunks

        async def _gen() -> AsyncIterator[bytes]:
            for c in chunks:
                yield c

        return _gen()


@pytest.fixture
def svc_with_batch_only() -> TTSService:
    svc = TTSService()
    svc._backend = _BatchOnlyBackend()
    svc._backend_name = "_batch_only_test"
    svc._enabled = True
    svc._silence_padding = 0.5  # would normally pad
    return svc


@pytest.fixture
def svc_with_streaming() -> TTSService:
    svc = TTSService()
    svc._backend = _StreamingBackend()
    svc._backend_name = "_streaming_test"
    svc._enabled = True
    svc._silence_padding = 0.5  # must NOT be applied to streaming
    return svc


def test_synthesize_stream_raises_when_backend_lacks_capability(svc_with_batch_only):
    req = SynthesisRequest(text="hi", voice_id="v1", output_format=AudioFormat.MP3)
    with pytest.raises(TTSCapabilityError) as ei:
        svc_with_batch_only.synthesize_stream(req)
    assert "_batch_only_test" in str(ei.value)


def test_synthesize_stream_raises_synchronously_not_on_first_iter(svc_with_batch_only):
    # The check must happen at the call site, not when the consumer
    # starts iterating — otherwise consumers see the error mid-loop.
    req = SynthesisRequest(text="hi", voice_id="v1", output_format=AudioFormat.MP3)
    with pytest.raises(TTSCapabilityError):
        # If the implementation were ``async def`` with ``yield``,
        # the call itself would return a generator object without
        # raising, and this assertion would fail.
        svc_with_batch_only.synthesize_stream(req)


@pytest.mark.asyncio
async def test_synthesize_stream_yields_backend_chunks_without_padding(svc_with_streaming):
    req = SynthesisRequest(text="hi", voice_id="v1", output_format=AudioFormat.MP3)
    chunks: list[bytes] = []
    async for c in svc_with_streaming.synthesize_stream(req):
        chunks.append(c)
    # Exactly the backend's chunks — no silence padding appended.
    assert chunks == [b"AAA", b"BBB", b"CCC"]


@pytest.mark.asyncio
async def test_synthesize_stream_raises_when_backend_none():
    svc = TTSService()  # no backend set; _enabled stays False
    req = SynthesisRequest(text="hi", voice_id="v1", output_format=AudioFormat.MP3)
    with pytest.raises(RuntimeError, match="TTS service is not enabled"):
        svc.synthesize_stream(req)


from gilbert.interfaces.tts import BidirectionalTTSCapability, TTSStream, TTSStreamConfig


class _FakeBidirectionalStream(TTSStream):
    def __init__(self):
        self.sent: list[str] = []
        self.flushed = 0
        self.closed = False

    async def send_text(self, text: str) -> None:
        self.sent.append(text)

    async def flush(self) -> None:
        self.flushed += 1

    async def close(self) -> None:
        self.closed = True

    def events(self) -> AsyncIterator:
        async def _gen():
            if False:
                yield  # pragma: no cover — empty iterator
        return _gen()


class _BidirectionalBackend(_BatchOnlyBackend):
    last_config: TTSStreamConfig | None = None

    async def open_stream(self, config: TTSStreamConfig) -> TTSStream:
        type(self).last_config = config
        return _FakeBidirectionalStream()


@pytest.fixture
def svc_with_bidi() -> TTSService:
    svc = TTSService()
    svc._backend = _BidirectionalBackend()
    svc._backend_name = "_bidi_test"
    svc._enabled = True
    return svc


@pytest.mark.asyncio
async def test_open_stream_raises_when_backend_lacks_capability(svc_with_streaming):
    # _StreamingBackend implements streaming but NOT bidirectional.
    cfg = TTSStreamConfig(voice_id="v1")
    with pytest.raises(TTSCapabilityError) as ei:
        await svc_with_streaming.open_stream(cfg)
    assert "bidirectional" in str(ei.value).lower()


@pytest.mark.asyncio
async def test_open_stream_returns_backend_stream(svc_with_bidi):
    cfg = TTSStreamConfig(voice_id="v1", output_format=AudioFormat.PCM, sample_rate=8000)
    stream = await svc_with_bidi.open_stream(cfg)
    assert isinstance(stream, TTSStream)
    assert _BidirectionalBackend.last_config == cfg


@pytest.mark.asyncio
async def test_open_stream_raises_when_backend_none():
    svc = TTSService()
    cfg = TTSStreamConfig(voice_id="v1")
    with pytest.raises(RuntimeError, match="TTS service is not enabled"):
        await svc.open_stream(cfg)


def test_supported_capabilities_batch_only(svc_with_batch_only):
    assert svc_with_batch_only.supported_capabilities() == frozenset({"batch"})


def test_supported_capabilities_streaming(svc_with_streaming):
    assert svc_with_streaming.supported_capabilities() == frozenset({"batch", "streaming"})


def test_supported_capabilities_bidirectional(svc_with_bidi):
    # _BidirectionalBackend inherits from _BatchOnlyBackend, so "streaming"
    # is NOT present unless that class also adds synthesize_stream.
    assert svc_with_bidi.supported_capabilities() == frozenset({"batch", "bidirectional"})


def test_supported_capabilities_with_no_backend():
    svc = TTSService()
    # No backend loaded → empty set.
    assert svc.supported_capabilities() == frozenset()
