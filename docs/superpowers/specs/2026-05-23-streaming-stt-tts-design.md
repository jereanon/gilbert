# Streaming TTS (and STT parity) — Design

**Status:** draft
**Date:** 2026-05-23
**Author:** Brian + Claude (brainstorming session)

## Problem

The current TTS path is bytes-only: `TTSBackend.synthesize()` returns a complete `SynthesisResult` and consumers (`SpeakerService._announce_inner`, `AudioOutputService`) write the full buffer to a file before playback. This blocks several use cases:

1. **Low-latency speaker announce** — first-audio latency is the whole synthesis time.
2. **LLM token → TTS pipeline** — can't start speaking until the model finishes the reply.
3. **Browser playback over WebSocket** — the SPA has to buffer the whole MP3 before it can begin.
4. **Phone calls** (no plugin yet, but a planned consumer) — phone bridges (Twilio Media Streams, etc.) need continuous audio frames.
5. **Web-chat conversations** — same browser path, per-conversation.

Streaming must be **optional**: not every backend supports it (`openai`, `bedrock`, etc. stay batch-only; ElevenLabs and Kokoro gain streaming).

## STT parity

STT already has streaming wired and we are **not** changing it in this design:

- Three sibling ABCs (`BatchTranscriptionBackend`, `StreamingTranscriptionBackend`, `WakeWordBackend`) live in `interfaces/transcription.py`, each with its own registry.
- `TranscriptionService` aggregates all three, with per-role `default` and per-backend `enabled` config.
- `Deepgram` and `ElevenLabsScribeLive` already implement `StreamingTranscriptionBackend`; `LocalWhisper` and `ElevenLabsScribe` are batch-only.
- WS plumbing exists (`transcription.start_session` / `send_chunk` / `close_session` + server-pushed `transcription.event`).

The TTS design draws on this for naming and wire-frame shape, but **does not** copy the three-ABC split (see "Approach decision" below).

## Approach decision — capability protocols, not sibling ABCs

Three alternatives were considered for how a TTS backend declares streaming support:

- **A.** Sibling ABCs with their own registries (strict STT parity).
- **B.** `@runtime_checkable` Protocols opt-in on a single `TTSBackend` class. ← **chosen**
- **C.** Default-`NotImplementedError` methods on `TTSBackend`.

**Why B over A:** STT's three-ABC split exists because batch / streaming / wake-word are genuinely different **roles** with different consumer code paths and different default selections. TTS variants (`batch`, `streaming`, `bidirectional`) are different **IO shapes on the same role** — same vendor, same client, same voice catalog, just different latencies. Forcing ElevenLabs into 2–3 sibling classes that share initialize / config / HTTP session adds friction without payoff, and inflates `TTSService` config with per-role enable/default toggles that aren't needed. The existing `AICapableTTSBackend` protocol pattern (also in `interfaces/tts.py`) is the closest precedent and is the model B follows.

**Why B over C:** C reduces capability detection to try/except, which can't drive a settings-page "Streaming: ✓ / ✗" badge and muddies the `TTSBackend` contract (the ABC then advertises methods that may always raise).

## Interface additions — `src/gilbert/interfaces/tts.py`

```python
@dataclass(frozen=True)
class TTSStreamConfig:
    """Config for a bidirectional TTS session."""
    voice_id: str
    output_format: AudioFormat = AudioFormat.MP3
    speed: float = 1.0
    context: str = ""
    sample_rate: int = 44100   # PCM-only; phone-friendly preset is 8000

@dataclass(frozen=True)
class TTSAudioChunk:
    audio: bytes

@dataclass(frozen=True)
class TTSWordTiming:
    word: str
    start_seconds: float
    end_seconds: float

@dataclass(frozen=True)
class TTSFlushed:
    at_seconds: float          # backend finished synthesizing one flush boundary

@dataclass(frozen=True)
class TTSStreamError:
    message: str
    recoverable: bool = False

TTSEvent = TTSAudioChunk | TTSWordTiming | TTSFlushed | TTSStreamError


class TTSStream(ABC):
    """Bidirectional TTS session. Push text, read TTSEvents."""

    @abstractmethod
    async def send_text(self, text: str) -> None: ...

    @abstractmethod
    async def flush(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    def events(self) -> AsyncIterator[TTSEvent]: ...


@runtime_checkable
class StreamingTTSCapability(Protocol):
    """One-shot text in, chunked audio out. Optional on TTSBackend."""

    def synthesize_stream(
        self, request: SynthesisRequest,
    ) -> AsyncIterator[bytes]: ...


@runtime_checkable
class BidirectionalTTSCapability(Protocol):
    """Push-text / read-audio session. Optional on TTSBackend."""

    async def open_stream(self, config: TTSStreamConfig) -> TTSStream: ...


class TTSCapabilityError(RuntimeError):
    """Raised when a consumer requests a capability the active backend
    doesn't implement. Distinct from the generic ``RuntimeError`` so
    callers (chat / phone / speaker integrations) can ``except`` it for
    graceful batch fallback."""
```

Plus two consumer-side protocols so consumers don't depend on the concrete `TTSService`:

```python
@runtime_checkable
class StreamingTTSProvider(Protocol):
    def synthesize_stream(self, request: SynthesisRequest) -> AsyncIterator[bytes]: ...

@runtime_checkable
class BidirectionalTTSProvider(Protocol):
    async def open_stream(self, config: TTSStreamConfig) -> TTSStream: ...
```

**Notes:**
- `synthesize_stream` is `def` returning `AsyncIterator[bytes]`, not `async def` — same shape transcription uses for `TranscriptionStream.events()`. Caller does `async for chunk in backend.synthesize_stream(req)`.
- `flush()` is the key bit for phone/LLM pipelines: most vendor APIs need an explicit "I'm done with this sentence, render now" signal so audio comes out before the conversation ends.
- `TTSEvent` is a union mirroring `TranscriptionEvent` — easy to JSON-encode and easy to extend.
- No `silence_padding` in `TTSStreamConfig`: padding is a finished-buffer concept.

## `TTSService` API additions — `src/gilbert/core/services/tts.py`

```python
# Existing — unchanged.
async def synthesize(self, request: SynthesisRequest) -> SynthesisResult: ...

# New — synchronous wrapper so the capability check fires at the call
# site, not on the consumer's first ``async for``. If this were an
# ``async def`` with ``yield``, the body wouldn't execute until first
# iteration and consumers would see the error mid-loop.
def synthesize_stream(
    self, request: SynthesisRequest,
) -> AsyncIterator[bytes]:
    if self._backend is None:
        raise RuntimeError("TTS service is not enabled")
    if not isinstance(self._backend, StreamingTTSCapability):
        raise TTSCapabilityError(
            f"backend {self._backend_name!r} does not support streaming synthesis"
        )
    self._ensure_ai_injection()
    # Delegate; no silence padding — streaming consumers control their own tail.
    return self._backend.synthesize_stream(request)

async def open_stream(self, config: TTSStreamConfig) -> TTSStream:
    if self._backend is None:
        raise RuntimeError("TTS service is not enabled")
    if not isinstance(self._backend, BidirectionalTTSCapability):
        raise TTSCapabilityError(
            f"backend {self._backend_name!r} does not support bidirectional streaming"
        )
    self._ensure_ai_injection()
    return await self._backend.open_stream(config)

def supported_capabilities(self) -> frozenset[str]:
    caps = {"batch"}
    if isinstance(self._backend, StreamingTTSCapability):
        caps.add("streaming")
    if isinstance(self._backend, BidirectionalTTSCapability):
        caps.add("bidirectional")
    return frozenset(caps)
```

**Service-level decisions:**
- `synthesize_stream` is a synchronous `def` returning the backend's `AsyncIterator[bytes]` — the capability check raises at the call site, not mid-iteration. (An `async def` with `yield` would defer the check to first `__anext__` because async generator bodies don't run until iteration starts; that's the trap we're avoiding.)
- `silence_padding` continues to apply to `synthesize()` and explicitly does NOT apply to `synthesize_stream` / `open_stream`.
- No new `ConfigParam`s — streaming is a per-backend capability, not a service setting. The settings page can use `supported_capabilities()` to render a badge next to the backend selector.

## WebSocket plumbing

Mirror the `TranscriptionService` WS pattern.

### Handlers

```python
def get_ws_handlers(self) -> dict[str, Any]:
    return {
        "tts.start_stream":  self._handle_start_stream,
        "tts.send_text":     self._handle_send_text,
        "tts.flush":         self._handle_flush,
        "tts.close_stream":  self._handle_close_stream,
    }
```

### Session record

```python
@dataclass
class _ActiveTTSSession:
    session_id: str
    conn_id: str
    user_id: str
    mode: str                        # "oneshot" | "bidirectional"
    primitive: TTSStream | None      # None for oneshot
    pump_task: asyncio.Task[None] | None = None
```

Stored on `self._sessions: dict[str, _ActiveTTSSession]`, guarded by `self._sessions_guard`, cleaned up via `conn.add_close_callback(...)` on socket drop.

### Client → server frames

```jsonc
// Open. mode="oneshot" calls synthesize_stream(request) with the included text.
// mode="bidirectional" calls open_stream(config) and arms send_text/flush.
{"type": "tts.start_stream",
 "mode": "oneshot" | "bidirectional",
 "format": "mp3" | "wav" | "ogg" | "pcm",
 "voice_id": "...",
 "speed": 1.0,
 "context": "...",
 "sample_rate": 44100,             // PCM only
 "text": "..."                     // oneshot only
}
// Response: {"session_id": "<uuid>"} | {"ok": false, "error": "..."}

// Bidirectional only.
{"type": "tts.send_text", "session_id": "<uuid>", "text": "..."}
{"type": "tts.flush",     "session_id": "<uuid>"}

// Either mode.
{"type": "tts.close_stream", "session_id": "<uuid>"}
```

### Server → client frames

One unified event frame:

```jsonc
{"type": "tts.event",
 "session_id": "<uuid>",
 "event": {"type": "audio",   "audio_b64": "...", "format": "mp3"}
        | {"type": "word",    "word": "hello", "start_seconds": 0.12, "end_seconds": 0.41}
        | {"type": "flushed", "at_seconds": 1.20}
        | {"type": "error",   "message": "...", "recoverable": false}
        | {"type": "end"}     // server-emitted when synth completes / iterator drains
}
```

A `_event_to_json(ev)` helper lives next to the same-named transcription helper. Auth: all four handlers require an authenticated `UserContext`, matching transcription.

### Oneshot pump

```python
async def _pump_oneshot(self, conn, session_id, request, fmt):
    try:
        async for chunk in self.synthesize_stream(request):
            conn.enqueue({
                "type": "tts.event",
                "session_id": session_id,
                "event": {"type": "audio",
                          "audio_b64": base64.b64encode(chunk).decode(),
                          "format": fmt.value},
            })
        conn.enqueue({"type": "tts.event", "session_id": session_id,
                      "event": {"type": "end"}})
    except TTSCapabilityError as e:
        conn.enqueue({"type": "tts.event", "session_id": session_id,
                      "event": {"type": "error", "message": str(e),
                                "recoverable": False}})
    finally:
        async with self._sessions_guard:
            self._sessions.pop(session_id, None)
```

### Bidirectional pump

Mirrors `TranscriptionService._pump_events`: drains `TTSStream.events()`, encodes each `TTSEvent` via `_event_to_json`, enqueues a `tts.event` frame.

### Wire-format choices

- **One unified frame type** (`tts.event`) — keeps SPA dispatch trivial.
- **Base64 audio** — ~33% overhead, but matches the existing `transcription.event` inbound path. Raw binary frames can be added later if chat/phone consumers need it, without rewriting the JSON path.
- **`text` on `tts.start_stream` for oneshot** — saves a round trip for the SPA's "give me the whole sentence, stream me audio" case.

## Backend implementations

### ElevenLabs (`std-plugins/elevenlabs/elevenlabs_tts.py`)

- **`StreamingTTSCapability`** — `synthesize_stream(request)` uses their `text-to-speech/{voice_id}/stream` HTTP endpoint, iterating `client.aiter_bytes(...)`.
- **`BidirectionalTTSCapability`** — `open_stream(config)` opens their `text-to-speech/{voice_id}/stream-input` WebSocket and returns an `ElevenLabsTTSStream` wrapping the WS. Maps:
  - `audio` frames → `TTSAudioChunk`
  - `alignment` frames → `TTSWordTiming`
  - error / disconnect → `TTSStreamError`
- **Audio-tag director** — `_inject_audio_tags` runs once per `flush()`, not per token, so the small-model cost stays bounded.

### Kokoro (`std-plugins/kokoro/kokoro_tts.py`)

- **`StreamingTTSCapability` only.** Kokoro is local CPU-bound model inference; there's no network connection to keep open and bidirectional adds no value.
- `synthesize_stream(request)` splits input into sentences and yields each sentence's synthesized bytes as a chunk. Long replies get useful first-audio latency: speaker hears sentence 1 while sentence 2 renders.

### Other backends

`openai`, `bedrock`, `andon-fm`, etc. stay batch-only. `supported_capabilities()` reports `{batch}` for them. Adding more streaming backends later is purely additive.

## Consumer integration scope

### In scope (this design / plan)

1. The interface additions, `TTSService` API, WS handlers, the two backend implementations, and tests.
2. A focused SPA hook (`useTTSStream`) and a single demo entry point in the `/tts` settings page's existing "synthesize" test button — adds a "Stream" toggle that exercises the WS oneshot path. Just enough to prove the wire works in a browser.

### Out of scope — each its own future design

3. **Web-chat conversation streaming.** Chat SPA needs a TTS toggle and a player that consumes `tts.event` audio frames. Touches the chat UI, not these interfaces.
4. **LLM token → TTS pipeline.** Wiring `core/chat.py`'s streaming completion through `BidirectionalTTSCapability` involves sentence-boundary detection on the LLM stream and per-conversation config (which voice, when to enable). Its own design.
5. **Phone-call adapter.** No phone plugin exists yet. When one is built (Twilio Media Streams, etc.), it consumes `BidirectionalTTSCapability` directly. `TTSStreamConfig.sample_rate` + PCM output format are the hooks it'll need.
6. **Sonos / speaker low-latency announce.** Speakers expect a URL. Streaming-to-speaker requires either (a) writing chunks to a file and serving via HTTP chunked response, or (b) a different speaker API. Material work, separate design.

The interfaces are shaped to support all of (3)–(6); we're just not building those consumers in this pass.

## Testing strategy

### Unit tests (`tests/unit/`)

- **`test_tts_capabilities.py`** — fake `BatchOnlyBackend`, `StreamingBackend`, `BidirectionalBackend`. Assert `supported_capabilities()` is `{batch}` / `{batch, streaming}` / `{batch, streaming, bidirectional}`. Assert `TTSService.synthesize_stream` raises `TTSCapabilityError` for batch-only; assert `open_stream` raises unless bidirectional capability is present.
- **`test_tts_stream_primitive.py`** — `FakeTTSStream` records `send_text` / `flush` / `close` calls, emits a scripted event sequence. Assert `events()` is drainable, `close()` is idempotent, `send_text` after `close` raises.
- **`test_tts_service_streaming.py`** — `synthesize_stream` does NOT apply `silence_padding` (chunks match backend's raw yield). `_ensure_ai_injection` is called on both streaming entry points. Backend-not-loaded raises `RuntimeError`; capability missing raises `TTSCapabilityError`.
- **`test_tts_ws_handlers.py`** — fake `WsConnection` (mirror transcription's WS test fixture). Drive each handler: `start_stream` returns `{session_id}`; `send_text` / `flush` route to the primitive; `close_stream` cleans up. Socket-close callback removes the session, cancels the pump, calls `primitive.close()`. Oneshot pump emits `audio` then `end`. Capability error during pump emits `error` and tears down.

### Integration tests (gated, opt-in)

- **`std-plugins/elevenlabs/tests/test_elevenlabs_streaming.py`** (`@pytest.mark.slow`, requires API key):
  - `test_synthesize_stream_yields_chunks` — short text, ≥ 2 chunks, total bytes decodable as MP3.
  - `test_open_stream_bidirectional` — open session, `send_text("Hello. ")`, `flush()`, drain events until a `TTSFlushed` and ≥ 1 `TTSAudioChunk`s, then `close()`. Word-timing assertions only if the API returns them.
- **`std-plugins/kokoro/tests/test_kokoro_streaming.py`** (`@pytest.mark.slow`):
  - `test_synthesize_stream_yields_per_sentence` — 3-sentence input, 3 chunks, each decodes to non-empty audio.

### Regression coverage

- Run the full `uv run pytest` at the end — every existing TTS test must pass unmodified (changes are purely additive on `TTSBackend` + `TTSService`).
- Add an explicit test asserting `synthesize()` still applies `silence_padding` and `synthesize_stream()` does NOT.

### Not tested in this pass

- SPA end-to-end browser → audio playback (the "Stream" demo button is a smoke test, not a covered surface — calling that out so we don't claim coverage we don't have).
- Phone-bridge integration (no phone plugin).
- Speaker-stream integration (deferred).

## Files touched

**New / modified core:**
- `src/gilbert/interfaces/tts.py` — new dataclasses, `TTSStream` ABC, two capability protocols, two consumer protocols, `TTSCapabilityError`.
- `src/gilbert/core/services/tts.py` — three new methods (`synthesize_stream`, `open_stream`, `supported_capabilities`), four new WS handlers, `_ActiveTTSSession`, `_pump_oneshot`, `_pump_events`, `_event_to_json`.

**New / modified backends:**
- `std-plugins/elevenlabs/elevenlabs_tts.py` — `synthesize_stream`, `open_stream`, `ElevenLabsTTSStream` class.
- `std-plugins/kokoro/kokoro_tts.py` — `synthesize_stream`.

**Frontend:**
- One new hook `src/gilbert/web/spa/.../useTTSStream.ts` (exact location TBD against the existing SPA structure).
- One small edit to the `/tts` settings test button to add a "Stream" toggle.

**Tests:**
- 4 new unit test files in `tests/unit/`.
- 2 new integration test files in plugin `tests/` dirs.

**Documentation:**
- Update `README.md` and/or `docs/architecture/` if there's an existing TTS architecture doc that needs to mention the optional streaming capability protocols.
- `validate-architecture` skill audit at the end (it'll flag the README freshness rule).

## Open questions

- **Should `TTSStreamConfig` carry a `language` hint?** ElevenLabs and Cartesia accept one. Not needed for the first cut — adding later is additive — but flag it during implementation in case the bidirectional WS open frame needs it sooner.
- **SPA hook location.** Exact path depends on the existing `web/spa/` layout; the implementation plan will pin it.
