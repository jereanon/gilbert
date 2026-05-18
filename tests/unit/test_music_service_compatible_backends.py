"""Tests for MusicBackend.compatible_speaker_backends classmethod
and MusicService._validate_compatible_speakers enforcement."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from gilbert.interfaces.music import MusicBackend, MusicItemKind, MusicSearchUnavailableError


class _DemoMusic(MusicBackend):
    """Minimal concrete subclass for default-behavior testing."""
    backend_name = "demo"

    async def initialize(self, config: dict) -> None:
        pass

    async def close(self) -> None:
        pass

    async def list_favorites(self):
        return []

    async def list_playlists(self):
        return []

    async def search(self, query: str, *, kind: MusicItemKind = MusicItemKind.TRACK, limit: int = 10):
        return []

    async def resolve_playable(self, item):
        pass


def test_default_compatible_speaker_backends_is_wildcard():
    assert _DemoMusic.compatible_speaker_backends() == frozenset({"*"})


# --- helpers for service-level tests ---


class _SonosOnlyMusic(MusicBackend):
    """Music backend that only works with sonos speakers."""

    backend_name = "_sonos_only_test"

    async def initialize(self, config: dict) -> None:
        pass

    async def close(self) -> None:
        pass

    async def list_favorites(self):
        return []

    async def list_playlists(self):
        return []

    async def search(self, query: str, *, kind: MusicItemKind = MusicItemKind.TRACK, limit: int = 10):
        return []

    async def resolve_playable(self, item):
        from gilbert.interfaces.music import Playable
        return Playable(uri=item.uri or "x-sonos:track", title=item.title)

    @classmethod
    def compatible_speaker_backends(cls) -> frozenset[str]:
        return frozenset({"sonos"})


class _WildcardMusic(MusicBackend):
    """Music backend that works with any speaker backend."""

    backend_name = "_wildcard_test"

    async def initialize(self, config: dict) -> None:
        pass

    async def close(self) -> None:
        pass

    async def list_favorites(self):
        return []

    async def list_playlists(self):
        return []

    async def search(self, query: str, *, kind: MusicItemKind = MusicItemKind.TRACK, limit: int = 10):
        return []

    async def resolve_playable(self, item):
        from gilbert.interfaces.music import Playable
        return Playable(uri=item.uri or "http://stream/track", title=item.title)

    @classmethod
    def compatible_speaker_backends(cls) -> frozenset[str]:
        return frozenset({"*"})


def _make_speaker_svc(resolved: dict[str, str]) -> MagicMock:
    """Return a speaker service mock whose resolve_names returns ``resolved``."""
    from gilbert.interfaces.speaker import SpeakerProvider

    svc = MagicMock(spec=SpeakerProvider)
    svc.resolve_names = AsyncMock(return_value=resolved)
    svc.play_on_speakers = AsyncMock()
    svc.enqueue_on_speakers = AsyncMock()
    svc.play_queue_on_speakers = AsyncMock(return_value=True)
    return svc


def _make_music_service(backend: MusicBackend, speaker_svc: MagicMock):
    """Build a MusicService directly wired to the given backend and speaker svc."""
    from gilbert.core.services.music import MusicService

    svc = MusicService()
    svc._backend = backend
    svc._enabled = True
    svc._speaker_svc = speaker_svc
    return svc


# --- Tests ---


@pytest.mark.asyncio
async def test_music_service_rejects_incompatible_speaker_target():
    """MusicService.play_item should raise when target speaker's backend isn't compatible."""
    from gilbert.interfaces.music import MusicItem

    backend = _SonosOnlyMusic()
    speaker_svc = _make_speaker_svc({"My Browser": "browser:abc123"})
    svc = _make_music_service(backend, speaker_svc)

    item = MusicItem(
        id="track-1",
        title="Test Track",
        kind=MusicItemKind.TRACK,
        uri="x-sonos:track",
    )
    with pytest.raises(MusicSearchUnavailableError, match="can't play"):
        await svc.play_item(item, speaker_names=["My Browser"])


@pytest.mark.asyncio
async def test_music_service_wildcard_compatibility_accepts_any_speaker():
    """MusicService with wildcard music backend accepts any speaker target."""
    from gilbert.interfaces.music import MusicItem, Playable

    backend = _WildcardMusic()
    speaker_svc = _make_speaker_svc({"My Browser": "browser:abc123"})
    svc = _make_music_service(backend, speaker_svc)

    item = MusicItem(
        id="track-1",
        title="Test Track",
        kind=MusicItemKind.TRACK,
        uri="http://stream/track",
    )
    # Should not raise — wildcard backend accepts browser speakers
    result = await svc.play_item(item, speaker_names=["My Browser"])
    assert isinstance(result, Playable)
    speaker_svc.play_on_speakers.assert_awaited_once()


@pytest.mark.asyncio
async def test_music_service_accepts_compatible_speaker():
    """MusicService.play_item succeeds when the speaker backend is in compatible set."""
    from gilbert.interfaces.music import MusicItem, Playable

    backend = _SonosOnlyMusic()
    speaker_svc = _make_speaker_svc({"Kitchen": "sonos:RINCON_abc"})
    svc = _make_music_service(backend, speaker_svc)

    item = MusicItem(
        id="track-1",
        title="Test Track",
        kind=MusicItemKind.TRACK,
        uri="x-sonos:track",
    )
    result = await svc.play_item(item, speaker_names=["Kitchen"])
    assert isinstance(result, Playable)
    speaker_svc.play_on_speakers.assert_awaited_once()


@pytest.mark.asyncio
async def test_music_service_empty_speaker_names_skips_validation():
    """Empty or None speaker_names bypasses validation (no speakers to check)."""
    from gilbert.interfaces.music import MusicItem, Playable

    backend = _SonosOnlyMusic()
    # resolve_names won't be called so anything in the mock is fine
    speaker_svc = _make_speaker_svc({})
    svc = _make_music_service(backend, speaker_svc)

    item = MusicItem(
        id="track-1",
        title="Test Track",
        kind=MusicItemKind.TRACK,
        uri="x-sonos:track",
    )
    # None speaker_names — should not raise
    result = await svc.play_item(item, speaker_names=None)
    assert isinstance(result, Playable)


@pytest.mark.asyncio
async def test_music_service_rejects_incompatible_speaker_in_add_to_queue():
    """add_to_queue also validates speaker compatibility."""
    from gilbert.interfaces.music import MusicItem

    backend = _SonosOnlyMusic()
    backend.supports_queue = True
    speaker_svc = _make_speaker_svc({"My Browser": "browser:abc123"})
    svc = _make_music_service(backend, speaker_svc)

    item = MusicItem(
        id="track-1",
        title="Test Track",
        kind=MusicItemKind.TRACK,
        uri="x-sonos:track",
    )
    with pytest.raises(MusicSearchUnavailableError, match="can't play"):
        await svc.add_to_queue(item, speaker_names=["My Browser"])


@pytest.mark.asyncio
async def test_music_service_rejects_incompatible_speaker_in_play_queue():
    """play_queue also validates speaker compatibility."""
    backend = _SonosOnlyMusic()
    backend.supports_queue = True
    speaker_svc = _make_speaker_svc({"My Browser": "browser:abc123"})
    svc = _make_music_service(backend, speaker_svc)

    with pytest.raises(MusicSearchUnavailableError, match="can't play"):
        await svc.play_queue(speaker_names=["My Browser"])


@pytest.mark.asyncio
async def test_music_service_rejects_incompatible_speaker_in_start_station():
    """start_station also validates speaker compatibility (via play_item delegation)."""
    from gilbert.interfaces.music import MusicItem

    backend = _SonosOnlyMusic()
    backend.supports_stations = True

    async def fake_start_station(seed, limit=30):
        return [MusicItem(id="t1", title="Track 1", kind=MusicItemKind.TRACK, uri="x-sonos:t1")]

    backend.start_station = fake_start_station  # type: ignore[method-assign]
    speaker_svc = _make_speaker_svc({"My Browser": "browser:abc123"})
    svc = _make_music_service(backend, speaker_svc)

    with pytest.raises(MusicSearchUnavailableError, match="can't play"):
        await svc.start_station(seed="some artist", speaker_names=["My Browser"])


@pytest.mark.asyncio
async def test_validate_compatible_speakers_returns_resolved_mapping():
    """_validate_compatible_speakers returns the resolved {name: id} dict."""
    backend = _SonosOnlyMusic()
    speaker_svc = _make_speaker_svc({"Kitchen": "sonos:RINCON_abc"})
    svc = _make_music_service(backend, speaker_svc)

    result = await svc._validate_compatible_speakers(["Kitchen"])
    assert result == {"Kitchen": "sonos:RINCON_abc"}


@pytest.mark.asyncio
async def test_validate_compatible_speakers_empty_input_returns_empty():
    """_validate_compatible_speakers with empty list returns empty dict."""
    backend = _SonosOnlyMusic()
    speaker_svc = _make_speaker_svc({})
    svc = _make_music_service(backend, speaker_svc)

    result = await svc._validate_compatible_speakers([])
    assert result == {}

    result = await svc._validate_compatible_speakers(None)
    assert result == {}


# --- Tests for supports_loop filtering by compatible backends ---


def test_supports_loop_false_when_no_compatible_speaker_loaded():
    """A Sonos music backend with only a browser speaker loaded reports supports_loop=False."""
    from gilbert.core.services.music import MusicService
    from gilbert.interfaces.speaker import SpeakerProvider

    music_svc = MusicService()
    music_svc._backend = MagicMock(supports_loop=True)
    music_svc._backend.compatible_speaker_backends.return_value = frozenset({"sonos"})

    # Speaker service with a browser backend that supports_repeat=True; sonos not loaded
    fake_speaker_svc = MagicMock(spec=SpeakerProvider)
    fake_browser_backend = MagicMock(supports_repeat=True)
    fake_speaker_svc.backends = {"browser": fake_browser_backend}
    music_svc._speaker_svc = fake_speaker_svc

    assert music_svc.supports_loop is False


def test_supports_loop_true_when_compatible_speaker_with_repeat_loaded():
    """A Sonos music backend with a Sonos speaker backend loaded reports supports_loop=True."""
    from gilbert.core.services.music import MusicService
    from gilbert.interfaces.speaker import SpeakerProvider

    music_svc = MusicService()
    music_svc._backend = MagicMock(supports_loop=True)
    music_svc._backend.compatible_speaker_backends.return_value = frozenset({"sonos"})

    fake_speaker_svc = MagicMock(spec=SpeakerProvider)
    fake_sonos_backend = MagicMock(supports_repeat=True)
    fake_speaker_svc.backends = {"sonos": fake_sonos_backend}
    music_svc._speaker_svc = fake_speaker_svc

    assert music_svc.supports_loop is True


def test_supports_loop_wildcard_compat_any_repeat_capable_backend_qualifies():
    """A wildcard music backend reports supports_loop=True if any loaded speaker backend supports repeat."""
    from gilbert.core.services.music import MusicService
    from gilbert.interfaces.speaker import SpeakerProvider

    music_svc = MusicService()
    music_svc._backend = MagicMock(supports_loop=True)
    music_svc._backend.compatible_speaker_backends.return_value = frozenset({"*"})

    fake_speaker_svc = MagicMock(spec=SpeakerProvider)
    fake_browser_backend = MagicMock(supports_repeat=True)
    fake_speaker_svc.backends = {"browser": fake_browser_backend}
    music_svc._speaker_svc = fake_speaker_svc

    assert music_svc.supports_loop is True
