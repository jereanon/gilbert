# Kokoro TTS Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new `std-plugins/kokoro/` plugin that registers a `KokoroTTSBackend` for local, open-weights text-to-speech via the `kokoro` Python package — default-disabled, in-process, PyAV-encoded.

**Architecture:** Standard backend-only std-plugin. `KokoroTTSBackend(TTSBackend)` self-registers via `__init_subclass__`. Plugin lazily builds one `KPipeline` per language code (cached). Audio output is encoded to the caller's requested `AudioFormat` via PyAV and always resampled to 44.1 kHz mono int16 for parity with `interfaces/tts.py`.

**Tech Stack:** Python 3.12+, uv workspace, pytest (with `pytest-asyncio`), `kokoro>=0.9`, `torch>=2.4`, `av>=12` (PyAV), `numpy`, `soundfile` (only as backup, optional). No system ffmpeg required.

**Spec:** `docs/superpowers/specs/2026-05-23-kokoro-tts-integration-design.md`

---

## File Structure

To be created:
- `std-plugins/kokoro/plugin.yaml` — plugin manifest
- `std-plugins/kokoro/pyproject.toml` — uv workspace member declaring kokoro/torch/av deps
- `std-plugins/kokoro/__init__.py` — empty package marker
- `std-plugins/kokoro/plugin.py` — `KokoroPlugin(Plugin)` with `setup`, `teardown`, `metadata`, `runtime_dependencies`
- `std-plugins/kokoro/kokoro_tts.py` — `KokoroTTSBackend(TTSBackend)` + voice catalog + `_encode` helper
- `std-plugins/kokoro/tests/__init__.py` — empty
- `std-plugins/kokoro/tests/conftest.py` — gilbert_plugin_kokoro shim
- `std-plugins/kokoro/tests/test_kokoro_tts.py` — unit tests with mocked `KPipeline`

To be modified:
- `pyproject.toml` (Gilbert root) — add `gilbert-plugin-kokoro` to `dependencies` list and `[tool.uv.sources]` block
- `std-plugins/README.md` — add row + per-plugin detail section under `## Available plugins`

---

## Task 1: Scaffold plugin directory with manifest and pyproject

**Files:**
- Create: `std-plugins/kokoro/plugin.yaml`
- Create: `std-plugins/kokoro/pyproject.toml`
- Create: `std-plugins/kokoro/__init__.py`
- Create: `std-plugins/kokoro/tests/__init__.py`

- [ ] **Step 1: Create `plugin.yaml`**

```yaml
name: kokoro
version: "1.0.0"
description: "Kokoro local TTS backend — open-weights, in-process synthesis"

provides:
  - kokoro_tts

requires: []

depends_on: []
```

- [ ] **Step 2: Create `pyproject.toml`**

```toml
[project]
name = "gilbert-plugin-kokoro"
version = "1.0.0"
description = "Kokoro local TTS backend for Gilbert"
requires-python = ">=3.12"
dependencies = [
    "kokoro>=0.9",
    "torch>=2.4",
    "av>=12",
    "numpy>=1.26",
]

[tool.uv]
package = false
```

- [ ] **Step 3: Create empty package markers**

Write `std-plugins/kokoro/__init__.py` with no content.
Write `std-plugins/kokoro/tests/__init__.py` with no content.

- [ ] **Step 4: Commit**

```bash
git add std-plugins/kokoro/plugin.yaml std-plugins/kokoro/pyproject.toml std-plugins/kokoro/__init__.py std-plugins/kokoro/tests/__init__.py
git commit -m "kokoro: scaffold plugin directory with manifest and pyproject"
```

---

## Task 2: Add tests/conftest.py and a sanity import test

**Files:**
- Create: `std-plugins/kokoro/tests/conftest.py`
- Create: `std-plugins/kokoro/tests/test_kokoro_tts.py` (initial smoke test only)

- [ ] **Step 1: Write the failing test**

Create `std-plugins/kokoro/tests/test_kokoro_tts.py`:

```python
"""Tests for the Kokoro TTS backend."""

from __future__ import annotations


def test_module_imports() -> None:
    """The package shim from conftest.py makes the plugin importable."""
    import gilbert_plugin_kokoro  # noqa: F401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest std-plugins/kokoro/tests/test_kokoro_tts.py::test_module_imports -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gilbert_plugin_kokoro'`

- [ ] **Step 3: Write conftest.py**

Create `std-plugins/kokoro/tests/conftest.py` (copy of the tesseract conftest, adapted):

```python
"""Register the kokoro plugin as a Python package for tests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_plugin_dir = Path(__file__).resolve().parent.parent
_pkg_name = "gilbert_plugin_kokoro"

if _pkg_name not in sys.modules:
    pkg = ModuleType(_pkg_name)
    pkg.__path__ = [str(_plugin_dir)]
    pkg.__package__ = _pkg_name
    sys.modules[_pkg_name] = pkg

    for _mod_name in ("kokoro_tts", "plugin"):
        _spec = importlib.util.spec_from_file_location(
            f"{_pkg_name}.{_mod_name}",
            _plugin_dir / f"{_mod_name}.py",
            submodule_search_locations=[],
        )
        assert _spec is not None and _spec.loader is not None
        _mod = importlib.util.module_from_spec(_spec)
        sys.modules[f"{_pkg_name}.{_mod_name}"] = _mod
        _spec.loader.exec_module(_mod)
        setattr(pkg, _mod_name, _mod)
```

This conftest also needs `kokoro_tts.py` and `plugin.py` to exist — create minimal stubs that the next tasks will flesh out:

Create `std-plugins/kokoro/kokoro_tts.py`:

```python
"""Kokoro TTS backend — local synthesis via the kokoro package."""

from __future__ import annotations
```

Create `std-plugins/kokoro/plugin.py`:

```python
"""Kokoro TTS plugin — registers the KokoroTTSBackend backend."""

from __future__ import annotations
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest std-plugins/kokoro/tests/test_kokoro_tts.py::test_module_imports -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add std-plugins/kokoro/tests/conftest.py std-plugins/kokoro/tests/test_kokoro_tts.py std-plugins/kokoro/kokoro_tts.py std-plugins/kokoro/plugin.py
git commit -m "kokoro: add test conftest shim and stub modules"
```

---

## Task 3: Define the voice catalog

**Files:**
- Modify: `std-plugins/kokoro/kokoro_tts.py`
- Modify: `std-plugins/kokoro/tests/test_kokoro_tts.py`

The Kokoro voice catalog is static and known at compile time. The first character of `voice_id` encodes the language pipeline. Define it as a module-level `_VOICES: list[Voice]`.

- [ ] **Step 1: Write the failing tests**

Append to `std-plugins/kokoro/tests/test_kokoro_tts.py`:

```python
import pytest

from gilbert.interfaces.tts import Voice


def test_voice_catalog_is_nonempty() -> None:
    from gilbert_plugin_kokoro.kokoro_tts import _VOICES

    assert len(_VOICES) >= 20
    assert all(isinstance(v, Voice) for v in _VOICES)


def test_voice_catalog_unique_ids() -> None:
    from gilbert_plugin_kokoro.kokoro_tts import _VOICES

    ids = [v.voice_id for v in _VOICES]
    assert len(ids) == len(set(ids)), "voice_id must be unique across the catalog"


def test_voice_catalog_labels_populated() -> None:
    """Every voice has language, region, and gender labels for filtering."""
    from gilbert_plugin_kokoro.kokoro_tts import _VOICES

    for v in _VOICES:
        assert v.labels.get("language"), f"missing language label on {v.voice_id}"
        assert v.labels.get("gender") in ("female", "male"), f"bad gender on {v.voice_id}"


@pytest.mark.parametrize(
    "voice_id, expected_lang_code",
    [
        ("af_heart", "a"),
        ("am_adam", "a"),
        ("bf_emma", "b"),
        ("bm_george", "b"),
        ("jf_alpha", "j"),
        ("jm_kumo", "j"),
        ("zf_xiaoxiao", "z"),
        ("zm_yunjian", "z"),
        ("ef_dora", "e"),
        ("em_alex", "e"),
        ("ff_siwis", "f"),
        ("hf_alpha", "h"),
        ("hm_omega", "h"),
        ("if_sara", "i"),
        ("im_nicola", "i"),
        ("pf_dora", "p"),
        ("pm_alex", "p"),
    ],
)
def test_voice_id_first_char_encodes_lang_code(voice_id: str, expected_lang_code: str) -> None:
    from gilbert_plugin_kokoro.kokoro_tts import _lang_code_for_voice

    assert _lang_code_for_voice(voice_id) == expected_lang_code
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest std-plugins/kokoro/tests/test_kokoro_tts.py -v`
Expected: FAIL with `ImportError` / `AttributeError` for `_VOICES` and `_lang_code_for_voice`.

- [ ] **Step 3: Write the catalog and helper**

Replace `std-plugins/kokoro/kokoro_tts.py` with:

```python
"""Kokoro TTS backend — local synthesis via the kokoro package."""

from __future__ import annotations

from gilbert.interfaces.tts import Voice


def _v(voice_id: str, name: str, language: str, region: str, gender: str) -> Voice:
    return Voice(
        voice_id=voice_id,
        name=name,
        language=language,
        labels={"language": language, "region": region, "gender": gender},
    )


# Kokoro v1.0 voice catalog. The first character of voice_id encodes the
# language pipeline (a=American English, b=British, j=Japanese, z=Chinese,
# e=Spanish, f=French, h=Hindi, i=Italian, p=Portuguese). The second
# character is gender (f=female, m=male).
_VOICES: list[Voice] = [
    # American English (a)
    _v("af_alloy",   "Alloy",   "en-US", "American", "female"),
    _v("af_aoede",   "Aoede",   "en-US", "American", "female"),
    _v("af_bella",   "Bella",   "en-US", "American", "female"),
    _v("af_heart",   "Heart",   "en-US", "American", "female"),
    _v("af_jessica", "Jessica", "en-US", "American", "female"),
    _v("af_kore",    "Kore",    "en-US", "American", "female"),
    _v("af_nicole",  "Nicole",  "en-US", "American", "female"),
    _v("af_nova",    "Nova",    "en-US", "American", "female"),
    _v("af_river",   "River",   "en-US", "American", "female"),
    _v("af_sarah",   "Sarah",   "en-US", "American", "female"),
    _v("af_sky",     "Sky",     "en-US", "American", "female"),
    _v("am_adam",    "Adam",    "en-US", "American", "male"),
    _v("am_echo",    "Echo",    "en-US", "American", "male"),
    _v("am_eric",    "Eric",    "en-US", "American", "male"),
    _v("am_fenrir",  "Fenrir",  "en-US", "American", "male"),
    _v("am_liam",    "Liam",    "en-US", "American", "male"),
    _v("am_michael", "Michael", "en-US", "American", "male"),
    _v("am_onyx",    "Onyx",    "en-US", "American", "male"),
    _v("am_puck",    "Puck",    "en-US", "American", "male"),
    _v("am_santa",   "Santa",   "en-US", "American", "male"),
    # British English (b)
    _v("bf_alice",    "Alice",    "en-GB", "British", "female"),
    _v("bf_emma",     "Emma",     "en-GB", "British", "female"),
    _v("bf_isabella", "Isabella", "en-GB", "British", "female"),
    _v("bf_lily",     "Lily",     "en-GB", "British", "female"),
    _v("bm_daniel",   "Daniel",   "en-GB", "British", "male"),
    _v("bm_fable",    "Fable",    "en-GB", "British", "male"),
    _v("bm_george",   "George",   "en-GB", "British", "male"),
    _v("bm_lewis",    "Lewis",    "en-GB", "British", "male"),
    # Japanese (j)
    _v("jf_alpha",    "Alpha",    "ja", "Japan", "female"),
    _v("jf_gongitsune", "Gongitsune", "ja", "Japan", "female"),
    _v("jf_nezumi",   "Nezumi",   "ja", "Japan", "female"),
    _v("jf_tebukuro", "Tebukuro", "ja", "Japan", "female"),
    _v("jm_kumo",     "Kumo",     "ja", "Japan", "male"),
    # Mandarin Chinese (z)
    _v("zf_xiaobei",  "Xiaobei",  "zh", "Mainland", "female"),
    _v("zf_xiaoni",   "Xiaoni",   "zh", "Mainland", "female"),
    _v("zf_xiaoxiao", "Xiaoxiao", "zh", "Mainland", "female"),
    _v("zf_xiaoyi",   "Xiaoyi",   "zh", "Mainland", "female"),
    _v("zm_yunjian",  "Yunjian",  "zh", "Mainland", "male"),
    _v("zm_yunxi",    "Yunxi",    "zh", "Mainland", "male"),
    _v("zm_yunxia",   "Yunxia",   "zh", "Mainland", "male"),
    _v("zm_yunyang",  "Yunyang",  "zh", "Mainland", "male"),
    # Spanish (e)
    _v("ef_dora",     "Dora",     "es", "Spain", "female"),
    _v("em_alex",     "Alex",     "es", "Spain", "male"),
    _v("em_santa",    "Santa",    "es", "Spain", "male"),
    # French (f)
    _v("ff_siwis",    "Siwis",    "fr", "France", "female"),
    # Hindi (h)
    _v("hf_alpha",    "Alpha",    "hi", "India", "female"),
    _v("hf_beta",     "Beta",     "hi", "India", "female"),
    _v("hm_omega",    "Omega",    "hi", "India", "male"),
    _v("hm_psi",      "Psi",      "hi", "India", "male"),
    # Italian (i)
    _v("if_sara",     "Sara",     "it", "Italy", "female"),
    _v("im_nicola",   "Nicola",   "it", "Italy", "male"),
    # Portuguese (p)
    _v("pf_dora",     "Dora",     "pt", "Brazil", "female"),
    _v("pm_alex",     "Alex",     "pt", "Brazil", "male"),
    _v("pm_santa",    "Santa",    "pt", "Brazil", "male"),
]


_VOICES_BY_ID: dict[str, Voice] = {v.voice_id: v for v in _VOICES}


def _lang_code_for_voice(voice_id: str) -> str:
    """Return the kokoro KPipeline lang_code for a voice ID.

    The first character of the voice_id is the lang code (a/b/j/z/e/f/h/i/p).
    """
    if not voice_id:
        raise ValueError("voice_id is empty")
    return voice_id[0]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest std-plugins/kokoro/tests/test_kokoro_tts.py -v`
Expected: PASS for all catalog tests.

- [ ] **Step 5: Commit**

```bash
git add std-plugins/kokoro/kokoro_tts.py std-plugins/kokoro/tests/test_kokoro_tts.py
git commit -m "kokoro: define static voice catalog and lang_code helper"
```

---

## Task 4: Backend class skeleton with config params and registration

**Files:**
- Modify: `std-plugins/kokoro/kokoro_tts.py`
- Modify: `std-plugins/kokoro/tests/test_kokoro_tts.py`

- [ ] **Step 1: Write the failing tests**

Append to `std-plugins/kokoro/tests/test_kokoro_tts.py`:

```python
from gilbert.interfaces.tts import TTSBackend


def test_backend_registered() -> None:
    """Importing the module registers the backend in the ABC's registry."""
    import gilbert_plugin_kokoro.kokoro_tts  # noqa: F401
    backends = TTSBackend.registered_backends()
    assert "kokoro" in backends


def test_backend_config_params_keys() -> None:
    from gilbert_plugin_kokoro.kokoro_tts import KokoroTTSBackend

    params = KokoroTTSBackend.backend_config_params()
    keys = [p.key for p in params]
    assert keys == ["device", "default_voice", "speed", "preload"]


def test_backend_config_param_defaults() -> None:
    from gilbert_plugin_kokoro.kokoro_tts import KokoroTTSBackend

    by_key = {p.key: p for p in KokoroTTSBackend.backend_config_params()}
    assert by_key["device"].default == "cpu"
    assert by_key["device"].choices == ("cpu", "cuda", "mps", "auto")
    assert by_key["device"].restart_required is True
    assert by_key["default_voice"].default == "af_heart"
    assert by_key["default_voice"].choices is not None
    assert "af_heart" in by_key["default_voice"].choices
    assert "jf_alpha" in by_key["default_voice"].choices
    assert by_key["speed"].default == 1.0
    assert by_key["preload"].default is False
    assert by_key["preload"].restart_required is True


async def test_list_voices_returns_catalog() -> None:
    from gilbert_plugin_kokoro.kokoro_tts import KokoroTTSBackend, _VOICES

    backend = KokoroTTSBackend()
    voices = await backend.list_voices()
    assert voices == _VOICES


async def test_get_voice_known() -> None:
    from gilbert_plugin_kokoro.kokoro_tts import KokoroTTSBackend

    backend = KokoroTTSBackend()
    v = await backend.get_voice("af_heart")
    assert v is not None
    assert v.voice_id == "af_heart"
    assert v.labels["gender"] == "female"


async def test_get_voice_unknown() -> None:
    from gilbert_plugin_kokoro.kokoro_tts import KokoroTTSBackend

    backend = KokoroTTSBackend()
    v = await backend.get_voice("nope")
    assert v is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest std-plugins/kokoro/tests/test_kokoro_tts.py -v -k "backend or list_voices or get_voice"`
Expected: FAIL — `KokoroTTSBackend` does not exist.

- [ ] **Step 3: Add the backend class**

Append to `std-plugins/kokoro/kokoro_tts.py` (above the `_lang_code_for_voice` helper if you like, or at the bottom — order doesn't matter for module-level code):

```python
import logging
from typing import Any

from gilbert.interfaces.configuration import ConfigParam
from gilbert.interfaces.tools import ToolParameterType
from gilbert.interfaces.tts import (
    SynthesisRequest,
    SynthesisResult,
    TTSBackend,
)

logger = logging.getLogger(__name__)


class KokoroTTSBackend(TTSBackend):
    """Local TTS via the open-weights Kokoro-82M model.

    Lazily instantiates one ``kokoro.KPipeline`` per language code on
    first use and caches them. Synthesis runs in a thread executor
    because kokoro is sync/blocking. Output is always resampled to
    44.1 kHz mono int16 before encoding to the caller's requested
    AudioFormat via PyAV.
    """

    backend_name = "kokoro"

    @classmethod
    def backend_config_params(cls) -> list[ConfigParam]:
        return [
            ConfigParam(
                key="device",
                type=ToolParameterType.STRING,
                description="Inference device.",
                default="cpu",
                choices=("cpu", "cuda", "mps", "auto"),
                restart_required=True,
            ),
            ConfigParam(
                key="default_voice",
                type=ToolParameterType.STRING,
                description="Voice ID used when the caller does not specify one.",
                default="af_heart",
                choices=tuple(v.voice_id for v in _VOICES),
            ),
            ConfigParam(
                key="speed",
                type=ToolParameterType.NUMBER,
                description="Default speech rate multiplier (0.5 = slow, 2.0 = fast).",
                default=1.0,
            ),
            ConfigParam(
                key="preload",
                type=ToolParameterType.BOOLEAN,
                description=(
                    "Load the default-language Kokoro pipeline at startup. "
                    "When false (default), the model loads on the first "
                    "synthesis request, which adds ~5-10 s to that call."
                ),
                default=False,
                restart_required=True,
            ),
        ]

    def __init__(self) -> None:
        self._device: str = "cpu"
        self._default_voice: str = "af_heart"
        self._speed: float = 1.0
        self._preload: bool = False
        self._pipelines: dict[str, Any] = {}

    async def initialize(self, config: dict[str, object]) -> None:
        self._device = str(config.get("device", "cpu"))
        self._default_voice = str(config.get("default_voice", "af_heart"))
        self._speed = float(config.get("speed", 1.0))  # type: ignore[arg-type]
        self._preload = bool(config.get("preload", False))
        logger.info(
            "KokoroTTSBackend initialized: device=%s default_voice=%s speed=%s preload=%s",
            self._device, self._default_voice, self._speed, self._preload,
        )

    async def close(self) -> None:
        self._pipelines.clear()

    async def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        raise NotImplementedError("Task 7 implements this")

    async def list_voices(self) -> list[Voice]:
        return list(_VOICES)

    async def get_voice(self, voice_id: str) -> Voice | None:
        return _VOICES_BY_ID.get(voice_id)
```

Also adjust the import order at the top of the file so the `Voice` import is shared between the catalog and the backend (it already is — just confirm no duplicate imports).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest std-plugins/kokoro/tests/test_kokoro_tts.py -v`
Expected: PASS for the new tests. The `synthesize` tests don't exist yet, so this should be all-green except the smoke tests.

- [ ] **Step 5: Commit**

```bash
git add std-plugins/kokoro/kokoro_tts.py std-plugins/kokoro/tests/test_kokoro_tts.py
git commit -m "kokoro: add KokoroTTSBackend skeleton with config and voice methods"
```

---

## Task 5: Lifecycle — initialize values, close clears pipelines

**Files:**
- Modify: `std-plugins/kokoro/tests/test_kokoro_tts.py`

The backend class already has `initialize` / `close`. Add tests that lock in the behaviour.

- [ ] **Step 1: Write the failing tests**

Append:

```python
async def test_initialize_stores_config() -> None:
    from gilbert_plugin_kokoro.kokoro_tts import KokoroTTSBackend

    backend = KokoroTTSBackend()
    await backend.initialize({
        "device": "cuda",
        "default_voice": "bm_george",
        "speed": 1.25,
        "preload": False,
    })
    assert backend._device == "cuda"
    assert backend._default_voice == "bm_george"
    assert backend._speed == 1.25
    assert backend._preload is False


async def test_initialize_defaults_when_keys_missing() -> None:
    from gilbert_plugin_kokoro.kokoro_tts import KokoroTTSBackend

    backend = KokoroTTSBackend()
    await backend.initialize({})
    assert backend._device == "cpu"
    assert backend._default_voice == "af_heart"
    assert backend._speed == 1.0
    assert backend._preload is False


async def test_close_clears_pipelines() -> None:
    from gilbert_plugin_kokoro.kokoro_tts import KokoroTTSBackend

    backend = KokoroTTSBackend()
    await backend.initialize({})
    backend._pipelines["a"] = object()  # simulate a cached pipeline
    await backend.close()
    assert backend._pipelines == {}
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest std-plugins/kokoro/tests/test_kokoro_tts.py -v -k "initialize or close"`
Expected: PASS (the implementation from Task 4 already does this).

- [ ] **Step 3: Commit**

```bash
git add std-plugins/kokoro/tests/test_kokoro_tts.py
git commit -m "kokoro: lock in initialize/close lifecycle with tests"
```

---

## Task 6: Audio encoding helper for all four formats

**Files:**
- Modify: `std-plugins/kokoro/kokoro_tts.py`
- Modify: `std-plugins/kokoro/tests/test_kokoro_tts.py`

The encoder takes a float32 numpy array at 24 kHz mono and the desired `AudioFormat`, and returns encoded bytes resampled to 44.1 kHz mono int16. All four formats use PyAV.

- [ ] **Step 1: Write the failing tests**

Append:

```python
import numpy as np

from gilbert.interfaces.tts import AudioFormat


def _fake_pcm(seconds: float = 0.25, freq: float = 440.0, sr: int = 24000) -> np.ndarray:
    """Generate a short float32 sine wave for encoder testing."""
    t = np.arange(int(seconds * sr)) / sr
    return (0.2 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_encode_wav_starts_with_riff() -> None:
    from gilbert_plugin_kokoro.kokoro_tts import _encode

    out = _encode(_fake_pcm(), AudioFormat.WAV)
    assert out[:4] == b"RIFF"
    assert out[8:12] == b"WAVE"


def test_encode_mp3_has_mp3_magic() -> None:
    from gilbert_plugin_kokoro.kokoro_tts import _encode

    out = _encode(_fake_pcm(), AudioFormat.MP3)
    # MP3 streams start with either an ID3 tag (b"ID3") or an MPEG
    # frame sync (b"\xff\xfb" / b"\xff\xfa" / b"\xff\xf3" / b"\xff\xf2").
    assert out[:3] == b"ID3" or (out[0] == 0xFF and (out[1] & 0xE0) == 0xE0)
    assert len(out) > 100


def test_encode_ogg_starts_with_oggs() -> None:
    from gilbert_plugin_kokoro.kokoro_tts import _encode

    out = _encode(_fake_pcm(), AudioFormat.OGG)
    assert out[:4] == b"OggS"


def test_encode_pcm_is_int16_at_44100() -> None:
    from gilbert_plugin_kokoro.kokoro_tts import _encode

    out = _encode(_fake_pcm(seconds=1.0), AudioFormat.PCM)
    # 1 second of mono int16 at 44100 Hz = 88200 bytes.
    # PyAV resampling may produce slight off-by-one due to fractional
    # rates, so allow a few samples of slack.
    assert 88000 <= len(out) <= 88400
    samples = np.frombuffer(out, dtype="<i2")
    # Non-silent — at least one sample is well above zero.
    assert int(np.max(np.abs(samples))) > 1000


def test_encode_empty_input_returns_short_output() -> None:
    from gilbert_plugin_kokoro.kokoro_tts import _encode

    out = _encode(np.zeros(0, dtype=np.float32), AudioFormat.WAV)
    # Header-only WAV is OK; just don't crash.
    assert out[:4] == b"RIFF"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest std-plugins/kokoro/tests/test_kokoro_tts.py -v -k "encode"`
Expected: FAIL — `_encode` does not exist.

- [ ] **Step 3: Implement `_encode`**

Add to `std-plugins/kokoro/kokoro_tts.py` (top of file with the other imports, then the function near the bottom):

Imports to add at the top:

```python
import io

import numpy as np
```

Function (place above the class, after the catalog):

```python
_OUT_SAMPLE_RATE = 44100  # matches interfaces/tts.py _PCM_SAMPLE_RATE


def _encode(samples_24k_f32: np.ndarray, fmt: AudioFormat) -> bytes:
    """Resample float32 24kHz mono to 44.1kHz mono int16 and encode.

    PCM returns raw little-endian int16 bytes. WAV/MP3/OGG are produced
    by PyAV's in-memory muxer. All output is mono.
    """
    import av  # local import: heavy dep, only needed at synthesis time

    # Resample 24000 -> 44100 in float32 using PyAV's audio resampler.
    # We could do it ourselves with audioop, but PyAV already handles
    # rate conversion cleanly and avoids a second dependency path.
    src_layout = "mono"
    src_format = "flt"

    if samples_24k_f32.size == 0:
        resampled = np.zeros(0, dtype=np.int16)
    else:
        # Build a single input frame.
        in_frame = av.AudioFrame.from_ndarray(
            samples_24k_f32.reshape(1, -1),
            format=src_format,
            layout=src_layout,
        )
        in_frame.sample_rate = 24000
        resampler = av.AudioResampler(format="s16", layout=src_layout, rate=_OUT_SAMPLE_RATE)
        chunks: list[np.ndarray] = []
        for out_frame in resampler.resample(in_frame):
            chunks.append(out_frame.to_ndarray().reshape(-1))
        # Flush.
        for out_frame in resampler.resample(None):
            chunks.append(out_frame.to_ndarray().reshape(-1))
        resampled = (
            np.concatenate(chunks).astype(np.int16)
            if chunks
            else np.zeros(0, dtype=np.int16)
        )

    if fmt == AudioFormat.PCM:
        return resampled.tobytes()

    # Mux to MP3 / WAV / OGG via PyAV.
    codec_for_format = {
        AudioFormat.MP3: ("mp3", "libmp3lame"),
        AudioFormat.WAV: ("wav", "pcm_s16le"),
        AudioFormat.OGG: ("ogg", "libvorbis"),
    }
    container_fmt, codec_name = codec_for_format[fmt]

    buf = io.BytesIO()
    output = av.open(buf, mode="w", format=container_fmt)
    try:
        stream = output.add_stream(codec_name, rate=_OUT_SAMPLE_RATE)
        stream.layout = "mono"  # type: ignore[assignment]

        # Re-frame as int16 mono at 44.1kHz so the encoder accepts it.
        if resampled.size > 0:
            frame = av.AudioFrame.from_ndarray(
                resampled.reshape(1, -1),
                format="s16",
                layout="mono",
            )
            frame.sample_rate = _OUT_SAMPLE_RATE
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode(None):  # flush
            output.mux(packet)
    finally:
        output.close()
    return buf.getvalue()
```

(The `AudioFormat` import already exists in the file from Task 4's `from gilbert.interfaces.tts import ...`. If not, add it: `from gilbert.interfaces.tts import AudioFormat, SynthesisRequest, SynthesisResult, TTSBackend, Voice`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest std-plugins/kokoro/tests/test_kokoro_tts.py -v -k "encode"`
Expected: PASS for all five encoder tests.

- [ ] **Step 5: Commit**

```bash
git add std-plugins/kokoro/kokoro_tts.py std-plugins/kokoro/tests/test_kokoro_tts.py
git commit -m "kokoro: add PyAV-based audio encoder for MP3/WAV/OGG/PCM at 44.1kHz"
```

---

## Task 7: Synthesize — pipeline cache + executor + encoding

**Files:**
- Modify: `std-plugins/kokoro/kokoro_tts.py`
- Modify: `std-plugins/kokoro/tests/test_kokoro_tts.py`

This task wires `synthesize()` together. The kokoro `KPipeline` is mocked in tests; the integration test in Task 11 exercises the real one.

- [ ] **Step 1: Write the failing tests**

Append:

```python
from unittest.mock import MagicMock, patch


def _mock_pipeline_yielding(samples_per_chunk: list[int]):
    """Build a mock KPipeline whose call returns float32 chunks."""
    rng = np.random.default_rng(0)
    chunks = [
        (None, None, rng.standard_normal(n).astype(np.float32) * 0.1)
        for n in samples_per_chunk
    ]
    pipeline = MagicMock()
    pipeline.return_value = iter(chunks)
    return pipeline


async def test_synthesize_uses_pipeline_for_voice_lang() -> None:
    from gilbert_plugin_kokoro import kokoro_tts as kt

    backend = kt.KokoroTTSBackend()
    await backend.initialize({})
    fake_pipeline = _mock_pipeline_yielding([2400, 2400])  # 0.2s of audio

    with patch.object(kt, "_build_pipeline", return_value=fake_pipeline) as build:
        request = SynthesisRequest(
            text="Hello world.",
            voice_id="af_heart",
            output_format=AudioFormat.MP3,
        )
        result = await backend.synthesize(request)

    build.assert_called_once_with("a", "cpu")
    fake_pipeline.assert_called_once()
    call_kwargs = fake_pipeline.call_args.kwargs
    call_args = fake_pipeline.call_args.args
    # Implementation may pass text positionally; check both.
    assert "Hello world." in (call_args + tuple(call_kwargs.values()))
    assert call_kwargs.get("voice") == "af_heart"
    assert call_kwargs.get("speed") == 1.0

    assert result.format == AudioFormat.MP3
    assert result.audio[:3] == b"ID3" or result.audio[0] == 0xFF
    assert result.characters_used == len("Hello world.")


async def test_synthesize_caches_pipeline_per_language() -> None:
    from gilbert_plugin_kokoro import kokoro_tts as kt

    backend = kt.KokoroTTSBackend()
    await backend.initialize({})
    pipeline_a = _mock_pipeline_yielding([2400])
    pipeline_b = _mock_pipeline_yielding([2400])

    def _build(lang_code: str, device: str):
        return pipeline_a if lang_code == "a" else pipeline_b

    # Reset between calls so the mock can be invoked twice.
    pipeline_a.return_value = iter(
        [(None, None, np.zeros(2400, dtype=np.float32))]
    )
    with patch.object(kt, "_build_pipeline", side_effect=_build) as build:
        await backend.synthesize(SynthesisRequest(text="hi", voice_id="af_heart"))
        # Second call same language -> pipeline factory not invoked again.
        pipeline_a.return_value = iter(
            [(None, None, np.zeros(2400, dtype=np.float32))]
        )
        await backend.synthesize(SynthesisRequest(text="hi", voice_id="am_adam"))
        # Different language -> new pipeline built.
        await backend.synthesize(SynthesisRequest(text="hi", voice_id="bf_emma"))

    assert build.call_count == 2
    assert {c.args[0] for c in build.call_args_list} == {"a", "b"}


async def test_synthesize_uses_request_voice_speed_format() -> None:
    from gilbert_plugin_kokoro import kokoro_tts as kt

    backend = kt.KokoroTTSBackend()
    await backend.initialize({"speed": 1.5})
    fake_pipeline = _mock_pipeline_yielding([2400])

    with patch.object(kt, "_build_pipeline", return_value=fake_pipeline):
        request = SynthesisRequest(
            text="x",
            voice_id="bm_george",
            output_format=AudioFormat.WAV,
            speed=0.75,  # request speed overrides config
        )
        result = await backend.synthesize(request)

    assert fake_pipeline.call_args.kwargs.get("speed") == 0.75
    assert result.format == AudioFormat.WAV
    assert result.audio[:4] == b"RIFF"


async def test_synthesize_unknown_voice_raises_valueerror() -> None:
    from gilbert_plugin_kokoro.kokoro_tts import KokoroTTSBackend

    backend = KokoroTTSBackend()
    await backend.initialize({})
    with pytest.raises(ValueError, match="Unknown Kokoro voice"):
        await backend.synthesize(
            SynthesisRequest(text="x", voice_id="xx_nope")
        )


async def test_synthesize_preload_builds_default_lang_pipeline() -> None:
    """preload=True should build the default-voice's pipeline in initialize()."""
    from gilbert_plugin_kokoro import kokoro_tts as kt

    backend = kt.KokoroTTSBackend()
    with patch.object(kt, "_build_pipeline", return_value=MagicMock()) as build:
        await backend.initialize({"preload": True, "default_voice": "jf_alpha"})
    build.assert_called_once_with("j", "cpu")
    assert "j" in backend._pipelines
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest std-plugins/kokoro/tests/test_kokoro_tts.py -v -k "synthesize or preload"`
Expected: FAIL — `synthesize` raises `NotImplementedError`, `_build_pipeline` doesn't exist.

- [ ] **Step 3: Implement `_build_pipeline`, `synthesize`, and preload hook**

In `std-plugins/kokoro/kokoro_tts.py`, add this helper above the class:

```python
import asyncio


def _build_pipeline(lang_code: str, device: str) -> Any:
    """Construct a kokoro.KPipeline. Isolated so tests can patch it."""
    from kokoro import KPipeline  # type: ignore[import-untyped]

    # device="auto" lets kokoro pick — pass-through otherwise.
    if device == "auto":
        return KPipeline(lang_code=lang_code)
    return KPipeline(lang_code=lang_code, device=device)
```

Replace the entire `KokoroTTSBackend` class body so it includes the new `_get_pipeline` method and the working `initialize` / `synthesize`. The `backend_config_params` classmethod from Task 4 stays unchanged — it's repeated below in full so you can replace the whole class body in one shot:

```python
class KokoroTTSBackend(TTSBackend):
    backend_name = "kokoro"

    @classmethod
    def backend_config_params(cls) -> list[ConfigParam]:
        return [
            ConfigParam(
                key="device",
                type=ToolParameterType.STRING,
                description="Inference device.",
                default="cpu",
                choices=("cpu", "cuda", "mps", "auto"),
                restart_required=True,
            ),
            ConfigParam(
                key="default_voice",
                type=ToolParameterType.STRING,
                description="Voice ID used when the caller does not specify one.",
                default="af_heart",
                choices=tuple(v.voice_id for v in _VOICES),
            ),
            ConfigParam(
                key="speed",
                type=ToolParameterType.NUMBER,
                description="Default speech rate multiplier (0.5 = slow, 2.0 = fast).",
                default=1.0,
            ),
            ConfigParam(
                key="preload",
                type=ToolParameterType.BOOLEAN,
                description=(
                    "Load the default-language Kokoro pipeline at startup. "
                    "When false (default), the model loads on the first "
                    "synthesis request, which adds ~5-10 s to that call."
                ),
                default=False,
                restart_required=True,
            ),
        ]

    def __init__(self) -> None:
        self._device: str = "cpu"
        self._default_voice: str = "af_heart"
        self._speed: float = 1.0
        self._preload: bool = False
        self._pipelines: dict[str, Any] = {}

    async def initialize(self, config: dict[str, object]) -> None:
        self._device = str(config.get("device", "cpu"))
        self._default_voice = str(config.get("default_voice", "af_heart"))
        self._speed = float(config.get("speed", 1.0))  # type: ignore[arg-type]
        self._preload = bool(config.get("preload", False))
        logger.info(
            "KokoroTTSBackend initialized: device=%s default_voice=%s speed=%s preload=%s",
            self._device, self._default_voice, self._speed, self._preload,
        )
        if self._preload:
            lang = _lang_code_for_voice(self._default_voice)
            self._pipelines[lang] = _build_pipeline(lang, self._device)

    async def close(self) -> None:
        self._pipelines.clear()

    def _get_pipeline(self, lang_code: str) -> Any:
        pipeline = self._pipelines.get(lang_code)
        if pipeline is None:
            pipeline = _build_pipeline(lang_code, self._device)
            self._pipelines[lang_code] = pipeline
        return pipeline

    async def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        if request.voice_id not in _VOICES_BY_ID:
            raise ValueError(f"Unknown Kokoro voice: {request.voice_id!r}")
        lang = _lang_code_for_voice(request.voice_id)
        pipeline = self._get_pipeline(lang)
        speed = float(request.speed) if request.speed else self._speed

        loop = asyncio.get_running_loop()

        def _run_sync() -> np.ndarray:
            chunks: list[np.ndarray] = []
            for _g, _p, audio in pipeline(
                request.text, voice=request.voice_id, speed=speed
            ):
                arr = np.asarray(audio, dtype=np.float32).reshape(-1)
                chunks.append(arr)
            if not chunks:
                return np.zeros(0, dtype=np.float32)
            return np.concatenate(chunks)

        samples = await loop.run_in_executor(None, _run_sync)
        audio_bytes = _encode(samples, request.output_format)
        duration = float(samples.size) / 24000.0 if samples.size else 0.0
        return SynthesisResult(
            audio=audio_bytes,
            format=request.output_format,
            duration_seconds=duration,
            characters_used=len(request.text),
        )

    async def list_voices(self) -> list[Voice]:
        return list(_VOICES)

    async def get_voice(self, voice_id: str) -> Voice | None:
        return _VOICES_BY_ID.get(voice_id)
```

Also ensure `Voice` is imported at the top of the file:

```python
from gilbert.interfaces.tts import (
    AudioFormat,
    SynthesisRequest,
    SynthesisResult,
    TTSBackend,
    Voice,
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest std-plugins/kokoro/tests/test_kokoro_tts.py -v`
Expected: PASS — all synthesize, preload, and unknown-voice tests green; encoder + catalog + registration tests still green.

- [ ] **Step 5: Commit**

```bash
git add std-plugins/kokoro/kokoro_tts.py std-plugins/kokoro/tests/test_kokoro_tts.py
git commit -m "kokoro: implement synthesize with cached per-language pipelines"
```

---

## Task 8: Plugin module and runtime_dependencies probe

**Files:**
- Modify: `std-plugins/kokoro/plugin.py`
- Modify: `std-plugins/kokoro/tests/test_kokoro_tts.py`

- [ ] **Step 1: Write the failing tests**

Append:

```python
def test_plugin_metadata() -> None:
    from gilbert_plugin_kokoro.plugin import KokoroPlugin

    meta = KokoroPlugin().metadata()
    assert meta.name == "kokoro"
    assert "kokoro_tts" in meta.provides
    assert meta.requires == []


def test_plugin_runtime_dependencies() -> None:
    from gilbert_plugin_kokoro.plugin import KokoroPlugin

    deps = KokoroPlugin().runtime_dependencies()
    assert len(deps) == 1
    dep = deps[0]
    assert "kokoro" in dep.name.lower() or "tts" in dep.name.lower()
    # The check actually exercises kokoro+av, not just `which python`.
    assert "kokoro" in dep.check_cmd
    assert "av" in dep.check_cmd
    assert dep.install_hint  # non-empty hint


def test_create_plugin_returns_kokoro_plugin() -> None:
    from gilbert_plugin_kokoro.plugin import KokoroPlugin, create_plugin

    p = create_plugin()
    assert isinstance(p, KokoroPlugin)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest std-plugins/kokoro/tests/test_kokoro_tts.py -v -k "plugin"`
Expected: FAIL — `plugin.py` is still just a docstring stub.

- [ ] **Step 3: Write `plugin.py`**

Replace `std-plugins/kokoro/plugin.py`:

```python
"""Kokoro TTS plugin — registers the KokoroTTSBackend backend."""

from __future__ import annotations

from gilbert.interfaces.plugin import (
    Plugin,
    PluginContext,
    PluginMeta,
    RuntimeDependency,
)


class KokoroPlugin(Plugin):
    """Side-effect plugin: importing ``kokoro_tts`` registers the backend."""

    def metadata(self) -> PluginMeta:
        return PluginMeta(
            name="kokoro",
            version="1.0.0",
            description="Kokoro local TTS backend (open-weights, in-process)",
            provides=["kokoro_tts"],
            requires=[],
        )

    def runtime_dependencies(self) -> list[RuntimeDependency]:
        # Exercise the full stack (kokoro + torch + av) with a tiny synth.
        # The python -c string imports both libraries and runs one phoneme
        # through a KPipeline so a misconfigured torch/CUDA/libgomp install
        # fails here instead of at first user request.
        probe = (
            "python -c \"import av, kokoro; "
            "p = kokoro.KPipeline(lang_code='a'); "
            "list(p('hi', voice='af_heart'))\""
        )
        return [
            RuntimeDependency(
                name="kokoro-tts stack",
                description=(
                    "Verifies torch + kokoro + PyAV import and that a "
                    "minimal end-to-end synthesis completes."
                ),
                check_cmd=probe,
                install_hint=(
                    "Enable the kokoro plugin (default-disabled) so "
                    "`uv sync` resolves kokoro, torch, and av. First "
                    "synthesis downloads the ~327MB Kokoro-82M model."
                ),
                auto_install_cmd="",
            ),
        ]

    async def setup(self, context: PluginContext) -> None:
        # Importing the module triggers TTSBackend.__init_subclass__,
        # registering "kokoro" in the backend registry.
        from . import kokoro_tts  # noqa: F401

    async def teardown(self) -> None:
        pass


def create_plugin() -> Plugin:
    return KokoroPlugin()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest std-plugins/kokoro/tests/test_kokoro_tts.py -v -k "plugin"`
Expected: PASS for all three plugin tests.

- [ ] **Step 5: Commit**

```bash
git add std-plugins/kokoro/plugin.py std-plugins/kokoro/tests/test_kokoro_tts.py
git commit -m "kokoro: add Plugin class with runtime_dependencies probe"
```

---

## Task 9: Wire the plugin into the Gilbert root uv workspace

**Files:**
- Modify: `pyproject.toml` (Gilbert root)

- [ ] **Step 1: Add `gilbert-plugin-kokoro` to the `dependencies` list**

Open `pyproject.toml`. In the `[project]` `dependencies` array, the plugin entries are roughly alphabetical. Insert `"gilbert-plugin-kokoro",` between `"gilbert-plugin-hk-webhook",` and `"gilbert-plugin-lutron-radiora",`. The block should look like:

```toml
    "gilbert-plugin-hk-webhook",
    "gilbert-plugin-kokoro",
    "gilbert-plugin-lutron-radiora",
```

- [ ] **Step 2: Add the source entry**

In the `[tool.uv.sources]` block, insert between `gilbert-plugin-hk-webhook` and `gilbert-plugin-lutron-radiora`:

```toml
gilbert-plugin-hk-webhook = { workspace = true }
gilbert-plugin-kokoro = { workspace = true }
gilbert-plugin-lutron-radiora = { workspace = true }
```

- [ ] **Step 3: Run uv sync to verify the workspace resolves**

Run: `uv sync 2>&1 | tail -20`
Expected: No errors; the resolver picks up `gilbert-plugin-kokoro` and installs `kokoro`, `torch`, `av`, `numpy`.

If this fails because torch wheels can't be resolved on the host, document the failure in the commit message rather than continuing — the plan from this point assumes uv sync succeeded. Re-run `uv run pytest std-plugins/kokoro/tests/` after sync to confirm tests still pass with the real deps.

- [ ] **Step 4: Confirm all tests still pass**

Run: `uv run pytest std-plugins/kokoro/tests/ -v`
Expected: PASS — every test from Tasks 2-8.

Also run the full suite to catch any plugin-loader regressions:

Run: `uv run pytest tests/unit/test_plugins.py -v 2>&1 | tail -20`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "kokoro: wire plugin into root uv workspace"
```

---

## Task 10: Default-disabled state

**Files:**
- Modify: `std-plugins/kokoro/plugin.yaml` (only if defaults need extra fields)

The recent commits (`17aa1f6`, `4d0f9e5`) set up default-disabled behaviour. Confirm new plugins inherit this with no extra config.

- [ ] **Step 1: Check how default-disabled is enforced**

Run: `git log --oneline -20 | head -20`
Read the commits `17aa1f6` and `4d0f9e5` to see whether disable-by-default is driven by the plugin loader (no plugin.yaml change needed) or by a per-plugin `enabled: false` field.

Run: `git show 17aa1f6 -- std-plugins/`
Expected: shows the mechanism used to default plugins to disabled. If it's a global rule in the loader, no plugin.yaml change is needed for kokoro. If it requires `enabled: false` in `plugin.yaml`, add it now.

- [ ] **Step 2: Apply the mechanism**

If `plugin.yaml` needs an `enabled: false` field, add it. Otherwise no change.

- [ ] **Step 3: Verify by booting Gilbert**

This is a manual check — instruct the user to run `./gilbert.sh start` and confirm the kokoro plugin appears in the plugin list as disabled. If automated test exists, prefer that.

- [ ] **Step 4: Commit if changed**

```bash
git add std-plugins/kokoro/plugin.yaml
git commit -m "kokoro: ensure plugin defaults to disabled state"
```

If no change was needed, skip this commit.

---

## Task 11: Slow integration test — real model end-to-end

**Files:**
- Create: `std-plugins/kokoro/tests/test_kokoro_integration.py`

This test loads the real Kokoro model and runs synthesis. Marked `slow` so it's opt-in.

- [ ] **Step 1: Create the integration test file**

```python
"""Real-model integration tests for KokoroTTSBackend.

Marked ``slow`` because they download (~327MB on first run) and execute
the actual Kokoro pipeline on CPU. Run with:

    uv run pytest std-plugins/kokoro/tests/test_kokoro_integration.py -v -m slow

Skipped in default CI.
"""

from __future__ import annotations

import pytest

from gilbert.interfaces.tts import AudioFormat, SynthesisRequest


pytestmark = pytest.mark.slow


async def test_real_synth_mp3() -> None:
    from gilbert_plugin_kokoro.kokoro_tts import KokoroTTSBackend

    backend = KokoroTTSBackend()
    await backend.initialize({})
    try:
        result = await backend.synthesize(
            SynthesisRequest(text="Hello.", voice_id="af_heart", output_format=AudioFormat.MP3)
        )
    finally:
        await backend.close()

    # MP3 magic bytes (ID3 tag or MPEG frame sync).
    assert result.audio[:3] == b"ID3" or result.audio[0] == 0xFF
    assert result.format == AudioFormat.MP3
    # "Hello." is short — expect somewhere between 200ms and 2s of audio.
    assert result.duration_seconds is not None
    assert 0.2 <= result.duration_seconds <= 3.0
    assert result.characters_used == len("Hello.")


async def test_real_synth_wav() -> None:
    from gilbert_plugin_kokoro.kokoro_tts import KokoroTTSBackend

    backend = KokoroTTSBackend()
    await backend.initialize({})
    try:
        result = await backend.synthesize(
            SynthesisRequest(text="One two three.", voice_id="bm_george",
                             output_format=AudioFormat.WAV)
        )
    finally:
        await backend.close()

    assert result.audio[:4] == b"RIFF"
    assert result.format == AudioFormat.WAV
```

- [ ] **Step 2: Register the `slow` marker if not already present**

Run: `grep -n 'slow' /home/assistant/gilbert/pyproject.toml | head -5`

If `markers = [..., "slow:..."]` is not present, add to the `[tool.pytest.ini_options]` block:

```toml
markers = [
    "slow: marks tests as slow (deselect with '-m \"not slow\"')",
]
```

And confirm default test runs skip them by checking `addopts` or by running `uv run pytest std-plugins/kokoro/tests/ -v` and observing the integration tests are deselected.

If the marker already exists, no change needed.

- [ ] **Step 3: Verify integration test is opt-in**

Run: `uv run pytest std-plugins/kokoro/tests/ -v 2>&1 | tail -20`
Expected: The integration tests are deselected (default runs `-m "not slow"` or similar). If they ARE running by default, fix the `addopts` in `[tool.pytest.ini_options]` so they're skipped unless `-m slow` is passed.

- [ ] **Step 4: (Optional, only if user wants to verify) run the slow test**

Run: `uv run pytest std-plugins/kokoro/tests/test_kokoro_integration.py -v -m slow`
Expected: PASS — takes 30-60 s on first run (model download), faster after.

This step is optional in CI. Skip if hardware can't run torch.

- [ ] **Step 5: Commit**

```bash
git add std-plugins/kokoro/tests/test_kokoro_integration.py pyproject.toml
git commit -m "kokoro: add slow integration test with real model"
```

---

## Task 12: README updates

**Files:**
- Modify: `std-plugins/README.md`
- Modify: `README.md` (Gilbert root) — only if it enumerates TTS backends

This is the project's hard rule: README must reflect the actual plugin list.

- [ ] **Step 1: Read the current std-plugins README structure**

Run: `head -80 /home/assistant/gilbert/std-plugins/README.md`

Find the plugin table (probably markdown table near the top) and the per-plugin detail sections under `## Available plugins`.

- [ ] **Step 2: Add a table row for kokoro**

Insert (in alphabetical order, between `hk-webhook` and `lutron-radiora` or wherever the table sorts):

```markdown
| [kokoro](#kokoro)        | `kokoro_tts`           | Local open-weights TTS (Kokoro-82M, in-process) |
```

(Match the exact column layout of existing rows — copy `tesseract`'s row as a template and edit.)

- [ ] **Step 3: Add a per-plugin detail section**

In `## Available plugins`, insert (alphabetically, before `lutron-radiora` if it exists):

```markdown
### kokoro

Local text-to-speech backend powered by the open-weights [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) model. Runs entirely in-process — no cloud API, no HTTP server. Default-disabled because of heavyweight dependencies (PyTorch ~700 MB pip, ~327 MB model on first use).

**Provides:** `kokoro_tts` (TTSBackend)

**Dependencies:** `kokoro>=0.9`, `torch>=2.4`, `av>=12` (PyAV), `numpy>=1.26`

**Runtime check:** `./gilbert.sh doctor --plugin kokoro` runs a minimal end-to-end synthesis to verify the full stack (torch + kokoro + libgomp + PyAV) is functional.

**Configure** (`settings:` block under TTS Settings in the Gilbert UI):

| Key             | Type    | Default     | Notes |
|-----------------|---------|-------------|-------|
| `device`        | string  | `cpu`       | `cpu`, `cuda`, `mps`, or `auto`. Restart required. |
| `default_voice` | string  | `af_heart`  | One of the ~54 catalog voices (dropdown). |
| `speed`         | number  | `1.0`       | Default speech rate (0.5 – 2.0). Per-request `speed` on the synthesis call overrides this. |
| `preload`       | boolean | `false`     | Load the default-language pipeline at startup. Adds ~5-10 s to boot but avoids the latency on the first TTS call. Restart required. |

**Voices:** ~54 voices across American English, British English, Japanese, Mandarin, Spanish, French, Hindi, Italian, and Portuguese. The first character of each voice ID encodes the language (`a`=American, `b`=British, `j`=Japanese, `z`=Chinese, `e`=Spanish, `f`=French, `h`=Hindi, `i`=Italian, `p`=Portuguese); the second character is gender (`f`=female, `m`=male). Filter the Settings dropdown by `language`, `region`, or `gender` labels.

**Output formats:** MP3 (libmp3lame), WAV (PCM 16-bit LE), OGG (libvorbis), PCM (raw int16 LE). All output at 44.1 kHz mono, matching the rest of the TTS service.

**OS requirements:** None beyond what `uv sync` installs. PyAV ships its own ffmpeg shared libraries, so no system ffmpeg install is needed. On Linux, torch needs `libgomp1` (usually present); the runtime probe surfaces a clear error if it's missing.
```

- [ ] **Step 4: Check root README for TTS enumeration**

Run: `grep -n -i "tts\|elevenlabs\|speech" /home/assistant/gilbert/README.md | head -10`

If the root README lists TTS backends, add Kokoro to that list. If it doesn't enumerate them, no change needed.

- [ ] **Step 5: Run the validate-architecture audit**

This is a hard project requirement — the skill checks README freshness among other things.

Run: invoke the `validate-architecture` skill as a post-change audit and address any flagged issues.

- [ ] **Step 6: Commit**

```bash
git add std-plugins/README.md README.md
git commit -m "docs: document the kokoro TTS plugin in std-plugins README"
```

---

## Task 13: Final architecture validation and final commit

**Files:** (none — verification only)

- [ ] **Step 1: Run the full validate-architecture audit**

Invoke the `validate-architecture` skill on the changes and fix anything it flags. Specifically check:

- Plugin imports only from `gilbert.interfaces.*`
- Backend registration via `__init_subclass__`
- README freshness (already covered in Task 12)
- No business logic in routes (N/A here)
- No hardcoded AI prompts (N/A here)
- RBAC defaults (TTS goes through existing `audio_output` tool — no change needed)

- [ ] **Step 2: Run the full test suite**

Run: `uv run pytest 2>&1 | tail -20`
Expected: PASS for all tests, including the kokoro unit tests but excluding the slow integration tests.

- [ ] **Step 3: Run mypy and ruff**

Run: `uv run mypy src/ std-plugins/kokoro/ 2>&1 | tail -10`
Expected: No errors. If any, fix them.

Run: `uv run ruff check std-plugins/kokoro/`
Expected: No errors. If any, fix them.

Run: `uv run ruff format std-plugins/kokoro/ --check`
Expected: All files formatted. If not, run `uv run ruff format std-plugins/kokoro/` and commit.

- [ ] **Step 4: Final commit if anything was tweaked**

```bash
git add -A std-plugins/kokoro/
git commit -m "kokoro: lint and type-check fixes"
```

If nothing changed, skip this step.

---

## Done

Plan complete. After all 13 tasks the plugin should:

- Live at `std-plugins/kokoro/` with the standard structure
- Register `KokoroTTSBackend` (`backend_name="kokoro"`) on import
- Synthesize text to MP3 / WAV / OGG / PCM at 44.1 kHz via PyAV
- Cache one `KPipeline` per language, lazily by default
- Survive its own unit test suite with mocked pipelines
- Optionally exercise the real model under `pytest -m slow`
- Be wired into the root uv workspace
- Be documented in `std-plugins/README.md`
- Be default-disabled (per the recent project policy)
