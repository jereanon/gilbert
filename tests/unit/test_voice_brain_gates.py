"""Unit tests for the voice_brain noise filter + addressing gate.

The full ``run_conversation`` loop is integration-shaped (needs a
session, AI, TTS, STT — fakes for each), so these tests target the
isolated bits:

- ``_is_noise_utterance`` — pure function, tests in isolation.
- ``ConversationConfig`` — defaults preserve legacy behaviour
  (every transcript dispatches) so existing wrappers don't regress.

The address-gate LLM call itself is exercised at the voice-agent
plugin level (``test_voice_agent_noise_words.py``) — here we just
pin the contract that having ``address_gate_enabled=False`` skips
it entirely.
"""

from __future__ import annotations

from gilbert.core.services.voice_brain import _is_noise_utterance
from gilbert.interfaces.conversation import ConversationConfig


# ── _is_noise_utterance ───────────────────────────────────────────────


_NOISE: frozenset[str] = frozenset(
    {"uh", "um", "hmm", "huh", "yeah", "ok", "okay"}
)


def test_noise_filter_disabled_passes_everything() -> None:
    """Defaults — ``min_chars=0`` AND empty noise set — match the
    legacy behaviour where every committed transcript dispatches."""
    assert _is_noise_utterance("uh", min_chars=0, noise_words=frozenset()) == ""
    assert _is_noise_utterance("", min_chars=0, noise_words=frozenset()) == ""


def test_noise_filter_min_chars_drops_short() -> None:
    """Stripping punctuation, anything under the threshold drops."""
    assert _is_noise_utterance("a", min_chars=2, noise_words=frozenset()) == "too_short"
    assert _is_noise_utterance("a.", min_chars=2, noise_words=frozenset()) == "too_short"
    assert _is_noise_utterance("...", min_chars=2, noise_words=frozenset()) == "too_short"
    # Two chars passes.
    assert _is_noise_utterance("ok", min_chars=2, noise_words=frozenset()) == ""


def test_noise_filter_noise_only_drops() -> None:
    """A transcript whose tokens are ALL in the noise set drops."""
    assert _is_noise_utterance("uh", min_chars=0, noise_words=_NOISE) == "noise_only"
    assert _is_noise_utterance("uh um", min_chars=0, noise_words=_NOISE) == "noise_only"
    assert _is_noise_utterance("hmm.", min_chars=0, noise_words=_NOISE) == "noise_only"
    # Case-insensitive.
    assert _is_noise_utterance("UH HMM", min_chars=0, noise_words=_NOISE) == "noise_only"


def test_noise_filter_real_question_passes_through() -> None:
    """Adding noise tokens to a real question doesn't drop it — only
    transcripts that are ENTIRELY noise count."""
    assert _is_noise_utterance(
        "uh what time is it", min_chars=0, noise_words=_NOISE
    ) == ""
    assert _is_noise_utterance(
        "set a timer for ten minutes", min_chars=2, noise_words=_NOISE
    ) == ""


def test_noise_filter_punctuation_only_treated_as_empty() -> None:
    """Just punctuation strips to nothing — should NOT be tagged
    noise_only (the token set is empty, not a subset of noise)."""
    # min_chars=0 + empty noise → passes through. The recording happens
    # before this filter, so the SPA still sees the punctuation-only
    # transcript; the filter just stops the engine from dispatching it
    # as a turn.
    assert _is_noise_utterance("...", min_chars=0, noise_words=_NOISE) == ""


def test_noise_filter_layered_min_chars_first() -> None:
    """When BOTH gates are on, length runs first — a tiny noise word
    is reported as too_short (more specific) rather than noise_only."""
    assert _is_noise_utterance("uh", min_chars=3, noise_words=_NOISE) == "too_short"


# ── ConversationConfig defaults ──────────────────────────────────────


def test_config_defaults_preserve_legacy() -> None:
    """Existing wrappers (phone) must NOT pick up the new behaviour
    by accident. All four addressing knobs default OFF."""
    cfg = ConversationConfig(
        system_prompt="x",
        brain_tool_provider=_DummyBrain(),  # type: ignore[arg-type]
    )
    assert cfg.min_address_chars == 0
    assert cfg.noise_words == frozenset()
    assert cfg.address_gate_enabled is False
    assert cfg.address_gate_prompt == ""


class _DummyBrain:
    """Minimal stub to satisfy the dataclass — not used in these tests."""

    def get_brain_tools(self) -> list:  # type: ignore[type-arg]
        return []

    async def handle_brain_tool(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        return None
