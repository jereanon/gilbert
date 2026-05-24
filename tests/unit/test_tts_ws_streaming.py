"""Tests for TTSService WebSocket streaming handlers and helpers."""

import asyncio
import base64

import pytest

from gilbert.core.services.tts import TTSService, _event_to_json
from gilbert.interfaces.tts import (
    AudioFormat,
    TTSAudioChunk,
    TTSFlushed,
    TTSStreamError,
    TTSWordTiming,
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
