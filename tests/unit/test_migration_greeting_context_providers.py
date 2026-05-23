"""Translates greeting.include_* flags and per-source templates into
the new shape. Idempotent — re-running yields the same end state.

Migration modules whose filename starts with a digit can't be imported
via dotted syntax, so we load by path with ``importlib.util`` — the
same pattern the migration runner uses.
"""

import importlib.util
from pathlib import Path

import pytest

from gilbert.migrations.runner import MigrationContext


def _load_migration():
    repo_root = Path(__file__).resolve().parents[2]
    path = repo_root / "src/gilbert/migrations/0002_greeting_context_providers.py"
    spec = importlib.util.spec_from_file_location("m0002", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ctx(storage):
    """Minimal MigrationContext — only the ``storage`` field is read."""
    import logging
    return MigrationContext(
        storage=storage,
        log=logging.getLogger("test"),
        repo_root=Path("."),
    )


async def test_migration_translates_per_source_flags(sqlite_storage) -> None:
    M = _load_migration()
    await sqlite_storage.put("gilbert.config", "greeting", {
        "include_weather": True,
        "include_briefing": False,
        "include_health_brief": True,
        "weather_hint_template": "custom template {temperature}",
        "briefing_max_seconds": 45,
    })
    await M.up(_ctx(sqlite_storage))
    greeting = await sqlite_storage.get("gilbert.config", "greeting")
    assert "include_weather" not in greeting
    assert "include_briefing" not in greeting
    assert "include_health_brief" not in greeting
    assert "weather_hint_template" not in greeting
    assert "briefing_max_seconds" not in greeting
    assert greeting["enabled_context_providers"] == ["weather", "health"]

    weather = await sqlite_storage.get("gilbert.config", "weather")
    assert weather["weather_hint_template"] == "custom template {temperature}"

    feed_briefing = await sqlite_storage.get("gilbert.config", "feed_briefing")
    assert feed_briefing["briefing_max_seconds"] == 45


async def test_migration_is_idempotent(sqlite_storage) -> None:
    M = _load_migration()
    await sqlite_storage.put("gilbert.config", "greeting", {
        "include_weather": True,
        "include_briefing": True,
        "include_health_brief": False,
    })
    await M.up(_ctx(sqlite_storage))
    snapshot1 = await sqlite_storage.get("gilbert.config", "greeting")
    await M.up(_ctx(sqlite_storage))  # apply again
    snapshot2 = await sqlite_storage.get("gilbert.config", "greeting")
    assert snapshot1 == snapshot2


async def test_migration_handles_missing_greeting_config(sqlite_storage) -> None:
    """Fresh install — no greeting config row yet. Migration must not crash."""
    M = _load_migration()
    await M.up(_ctx(sqlite_storage))  # should be a no-op
    assert await sqlite_storage.get("gilbert.config", "greeting") is None
