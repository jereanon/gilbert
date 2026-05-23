"""GreetingService context discovery + assembly tests.

The wiring-into-the-prompt half lands in Task 6's tests; here we only
verify discovery + the assembled labeled block.
"""

import pytest

from gilbert.core.services.greeting import GreetingService
from gilbert.interfaces.greeting import GreetingContext, GreetingContextProvider


class FakeProvider:
    def __init__(self, provider_id: str, label: str, prose: str | None) -> None:
        self._id = provider_id
        self._label = label
        self._prose = prose

    @property
    def greeting_context_id(self) -> str:
        return self._id

    @property
    def greeting_context_label(self) -> str:
        return self._label

    async def greeting_context(self, user_id: str) -> GreetingContext | None:
        if self._prose is None:
            return None
        return GreetingContext(provider_id=self._id, label=self._label, prose=self._prose)


class FakeResolver:
    def __init__(self, providers: list[FakeProvider]) -> None:
        self._providers = providers

    def get_all(self, capability: str) -> list[object]:
        if capability == "greeting_context":
            return list(self._providers)
        return []

    def get_capability(self, name: str) -> object | None:
        return None


@pytest.fixture
def svc_with_providers() -> tuple[GreetingService, list[FakeProvider]]:
    weather = FakeProvider("weather", "Weather", "Sunny, 72°F.")
    briefing = FakeProvider("briefing", "News briefing", "Three items today.")
    health = FakeProvider("health", "Health", None)  # returns None
    providers = [weather, briefing, health]
    svc = GreetingService()
    svc._resolver = FakeResolver(providers)
    svc._discover_context_providers()  # populate _context_providers
    return svc, providers


def test_available_context_providers_lists_all_discovered(svc_with_providers) -> None:
    svc, _ = svc_with_providers
    entries = svc.available_context_providers()
    ids = [e["id"] for e in entries]
    assert ids == ["weather", "briefing", "health"]
    assert entries[0]["label"] == "Weather"


async def test_collect_context_returns_only_enabled_with_prose(svc_with_providers) -> None:
    """``health`` returned None — must be excluded.
    ``briefing`` is disabled via config — must be excluded."""
    svc, _ = svc_with_providers
    svc._enabled_context_providers = ["weather", "health"]  # briefing disabled
    block = await svc.collect_context_block(user_id="alice")
    assert "Weather:" in block
    assert "Sunny" in block
    assert "News briefing" not in block  # disabled
    assert "Health" not in block  # returned None


async def test_collect_context_returns_empty_when_none_enabled(svc_with_providers) -> None:
    svc, _ = svc_with_providers
    svc._enabled_context_providers = []
    assert await svc.collect_context_block(user_id="alice") == ""


async def test_collect_context_survives_provider_exception(svc_with_providers) -> None:
    """A buggy provider must never block the greeting."""

    class _Boom:
        @property
        def greeting_context_id(self) -> str:
            return "boom"

        @property
        def greeting_context_label(self) -> str:
            return "Boom"

        async def greeting_context(self, user_id: str) -> GreetingContext | None:
            raise RuntimeError("provider crashed")

    svc, providers = svc_with_providers
    providers.append(_Boom())  # mutates the resolver-backed list
    svc._discover_context_providers()  # re-discover after appending
    svc._enabled_context_providers = ["weather", "boom"]
    block = await svc.collect_context_block(user_id="alice")
    assert "Sunny" in block
    assert "Boom" not in block  # crash suppressed
