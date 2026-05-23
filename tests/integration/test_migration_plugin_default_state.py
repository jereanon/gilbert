"""Integration tests for migration 0003 (plugin_default_state).

Uses a real SQLite storage backend.  The migration is loaded directly
via importlib (same approach as the 0001 migration tests) so the 4-digit
prefix in the filename doesn't break normal import machinery.
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any

import pytest
import yaml

from gilbert.migrations.runner import MigrationContext
from gilbert.storage.sqlite import SQLiteStorage

# --- Load the migration module ---

_MIGRATION_PATH = (
    Path(__file__).parent.parent.parent
    / "src/gilbert/migrations/0003_plugin_default_state.py"
)
_spec = importlib.util.spec_from_file_location(
    "gilbert.migrations.__test__.0003_plugin_default_state",
    _MIGRATION_PATH,
)
assert _spec is not None and _spec.loader is not None, (
    f"Could not load migration from {_MIGRATION_PATH}"
)
_migration_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_migration_module)  # type: ignore[union-attr]
_up = _migration_module.up

_STATE_COLLECTION = "gilbert.plugin_state"


def _make_ctx(storage: SQLiteStorage, repo_root: Path) -> MigrationContext:
    return MigrationContext(
        storage=storage,
        repo_root=repo_root,
        log=logging.getLogger("test"),
    )


def _write_plugin(parent: Path, name: str, version: str = "1.0.0") -> Path:
    plugin_dir = parent / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.yaml").write_text(
        yaml.safe_dump({"name": name, "version": version, "description": f"{name} plugin"})
    )
    return plugin_dir


def _write_gilbert_yaml(repo_root: Path, directories: list[str]) -> None:
    (repo_root / "gilbert.yaml").write_text(
        yaml.safe_dump({"plugins": {"directories": directories}})
    )


# --- Tests ---


@pytest.mark.asyncio
async def test_migration_seeds_discovered_plugins_as_enabled(
    sqlite_storage: SQLiteStorage, tmp_path: Path
) -> None:
    """Plugins on disk with no existing state row are seeded with enabled=True."""
    plugin_dir = tmp_path / "std-plugins"
    plugin_dir.mkdir()
    _write_plugin(plugin_dir, "alpha-plugin")
    _write_plugin(plugin_dir, "beta-plugin")
    _write_gilbert_yaml(tmp_path, [str(plugin_dir)])

    ctx = _make_ctx(sqlite_storage, tmp_path)
    await _up(ctx)

    row_a = await sqlite_storage.get(_STATE_COLLECTION, "alpha-plugin")
    row_b = await sqlite_storage.get(_STATE_COLLECTION, "beta-plugin")
    assert row_a is not None and row_a["enabled"] is True
    assert row_b is not None and row_b["enabled"] is True


@pytest.mark.asyncio
async def test_migration_is_idempotent(
    sqlite_storage: SQLiteStorage, tmp_path: Path
) -> None:
    """Running the migration twice produces the same result."""
    plugin_dir = tmp_path / "std-plugins"
    plugin_dir.mkdir()
    _write_plugin(plugin_dir, "idempotent-plugin")
    _write_gilbert_yaml(tmp_path, [str(plugin_dir)])

    ctx = _make_ctx(sqlite_storage, tmp_path)
    await _up(ctx)
    await _up(ctx)  # second run

    row = await sqlite_storage.get(_STATE_COLLECTION, "idempotent-plugin")
    assert row is not None
    assert row["enabled"] is True


@pytest.mark.asyncio
async def test_migration_does_not_overwrite_existing_false_row(
    sqlite_storage: SQLiteStorage, tmp_path: Path
) -> None:
    """An existing enabled=False row (e.g. user disabled the plugin) is left alone."""
    plugin_dir = tmp_path / "std-plugins"
    plugin_dir.mkdir()
    _write_plugin(plugin_dir, "user-disabled-plugin")
    _write_gilbert_yaml(tmp_path, [str(plugin_dir)])

    # Simulate the user having already disabled this plugin before the migration.
    await sqlite_storage.put(
        _STATE_COLLECTION,
        "user-disabled-plugin",
        {
            "name": "user-disabled-plugin",
            "enabled": False,
            "first_seen_at": "2024-01-01T00:00:00+00:00",
        },
    )

    ctx = _make_ctx(sqlite_storage, tmp_path)
    await _up(ctx)

    row = await sqlite_storage.get(_STATE_COLLECTION, "user-disabled-plugin")
    assert row is not None
    assert row["enabled"] is False, "Migration must not overwrite an existing row"


@pytest.mark.asyncio
async def test_migration_handles_missing_config_gracefully(
    sqlite_storage: SQLiteStorage, tmp_path: Path
) -> None:
    """When gilbert.yaml doesn't exist, the migration falls back to
    conventional directories and runs without error."""
    # No gilbert.yaml written — migration should not crash.
    ctx = _make_ctx(sqlite_storage, tmp_path)
    await _up(ctx)  # Should not raise


@pytest.mark.asyncio
async def test_migration_seeds_plugins_from_multiple_directories(
    sqlite_storage: SQLiteStorage, tmp_path: Path
) -> None:
    """Plugins in std-plugins, local-plugins, and installed-plugins are all seeded."""
    std_dir = tmp_path / "std-plugins"
    local_dir = tmp_path / "local-plugins"
    std_dir.mkdir()
    local_dir.mkdir()
    _write_plugin(std_dir, "std-plugin")
    _write_plugin(local_dir, "local-plugin")
    _write_gilbert_yaml(tmp_path, [str(std_dir), str(local_dir)])

    ctx = _make_ctx(sqlite_storage, tmp_path)
    await _up(ctx)

    assert (await sqlite_storage.get(_STATE_COLLECTION, "std-plugin")) is not None
    assert (await sqlite_storage.get(_STATE_COLLECTION, "local-plugin")) is not None
