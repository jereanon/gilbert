"""Unit tests for transcription interface dataclasses, helpers, and ABCs."""

from gilbert.interfaces.transcription import (
    AudioEncoding,
    AudioFormat,
    FinalTranscript,
    PartialTranscript,
    SpeechEnded,
    SpeechStarted,
    TranscriptionError,
    TranscriptionRequest,
    TranscriptionResult,
    TranscriptSegment,
    WakeEvent,
    WakeWordConfig,
)


def test_audio_format_defaults():
    fmt = AudioFormat(AudioEncoding.PCM_S16LE)
    assert fmt.sample_rate == 16000
    assert fmt.channels == 1
    assert fmt.encoding == AudioEncoding.PCM_S16LE


def test_transcription_request_defaults():
    req = TranscriptionRequest(audio=b"abc")
    assert req.format.encoding == AudioEncoding.AUTO
    assert req.language is None
    assert req.diarize is False
    assert req.word_timestamps is False
    assert req.context == ""
    assert req.prompt == ""


def test_transcription_result_default_segments():
    r = TranscriptionResult(text="hi")
    assert r.segments == []
    assert r.language == ""
    assert r.duration_seconds is None


def test_transcript_segment_round_trip():
    seg = TranscriptSegment(
        text="hello", start_seconds=0.0, end_seconds=1.5,
        speaker_label="speaker_0", confidence=0.97,
    )
    assert seg.text == "hello"
    assert seg.speaker_label == "speaker_0"


def test_streaming_event_shapes():
    p = PartialTranscript(text="hel", speaker_label="speaker_0")
    f = FinalTranscript(text="hello", start_seconds=0.0, end_seconds=0.5)
    s = SpeechStarted(at_seconds=0.0)
    e = SpeechEnded(at_seconds=0.5)
    err = TranscriptionError(message="boom")
    assert p.start_seconds == 0.0
    assert f.confidence is None
    assert err.recoverable is False
    assert s.at_seconds == 0.0 and e.at_seconds == 0.5


def test_wake_word_config_and_event():
    cfg = WakeWordConfig(keywords=["hey gilbert"], format=AudioFormat(AudioEncoding.PCM_S16LE))
    assert cfg.sensitivity == 0.5
    ev = WakeEvent(keyword="hey gilbert", at_seconds=1.23)
    assert ev.confidence is None
