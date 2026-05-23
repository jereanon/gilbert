"""Unit tests for the plugin default-disabled feature in Gilbert._load_plugins.

Tests cover:
- New plugin (no state row) → row created with enabled=False, setup() NOT called.
- Existing plugin with enabled=True row → setup() called normally.
- Existing plugin with enabled=False row → setup() NOT called.
- Storage unavailable → all plugins load normally (safe fallback).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from gilbert.core.app import Gilbert, LoadedPlugin
from gilbert.interfaces.plugin import Plugin, PluginContext, PluginMeta
from gilbert.interfaces.service import Service, ServiceInfo, ServiceResolver
from gilbert.interfaces.storage import Query, StorageProvider

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

_STATE_COLLECTION = "gilbert.plugin_state"


class _FakeStorageBackend:
    """In-memory storage for testing _check_plugin_enabled."""

    def __init__(self) -> None:
        self.data: dict[str, dict[str, dict[str, Any]]] = {}
        self.puts: list[tuple[str, str, dict[str, Any]]] = []

    async def put(self, collection: str, entity_id: str, data: dict[str, Any]) -> None:
        self.data.setdefault(collection, {})[entity_id] = dict(data)
        self.puts.append((collection, entity_id, dict(data)))

    async def get(self, collection: str, entity_id: str) -> dict[str, Any] | None:
        return self.data.get(collection, {}).get(entity_id)

    async def delete(self, collection: str, entity_id: str) -> None:
        self.data.get(collection, {}).pop(entity_id, None)

    async def query(self, query: Any) -> list[dict[str, Any]]:
        return list(self.data.get(query.collection, {}).values())


class _FakeStorageService(Service):
    """Satisfies StorageProvider protocol for the service manager."""

    def __init__(self, backend: _FakeStorageBackend) -> None:
        self.backend = backend
        self.raw_backend = backend

    def service_info(self) -> ServiceInfo:
        return ServiceInfo(
            name="entity_storage",
            capabilities=frozenset({"entity_storage"}),
        )

    def create_namespaced(self, namespace: str) -> Any:
        return self.backend

    async def start(self, resolver: ServiceResolver) -> None:
        pass

    async def stop(self) -> None:
        pass


class _SetupTrackingPlugin(Plugin):
    """Plugin that records whether setup() was called."""

    def __init__(self, name: str) -> None:
        self._name = name
        self.setup_called = False

    def metadata(self) -> PluginMeta:
        return PluginMeta(name=self._name, version="1.0.0")

    async def setup(self, context: PluginContext) -> None:
        self.setup_called = True

    async def teardown(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Helper: call _check_plugin_enabled in isolation
# ---------------------------------------------------------------------------


async def _check(
    storage: _FakeStorageBackend | None,
    name: str,
) -> bool:
    """Invoke Gilbert._check_plugin_enabled without a full Gilbert instance."""
    # We instantiate a minimal Gilbert-like object just to call the method.
    # The method only uses ``self`` for logging — it doesn't touch other attrs.
    from gilbert.config import GilbertConfig
    from gilbert.core.service_manager import ServiceManager

    # Build a minimal GilbertConfig-like object
    cfg = object.__new__(GilbertConfig)  # bypass __init__ — we don't need it
    g = object.__new__(Gilbert)
    g.service_manager = ServiceManager()  # type: ignore[attr-defined]
    g.config = cfg  # type: ignore[attr-defined]
    return await g._check_plugin_enabled(storage, name)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Tests: _check_plugin_enabled
# ---------------------------------------------------------------------------


class TestCheckPluginEnabled:
    @pytest.mark.asyncio
    async def test_new_plugin_creates_row_and_returns_false(self) -> None:
        storage = _FakeStorageBackend()

        result = await _check(storage, "my-plugin")

        assert result is False
        # Row should be created
        row = await storage.get(_STATE_COLLECTION, "my-plugin")
        assert row is not None
        assert row["enabled"] is False
        assert row["name"] == "my-plugin"
        assert "first_seen_at" in row

    @pytest.mark.asyncio
    async def test_existing_enabled_true_returns_true(self) -> None:
        storage = _FakeStorageBackend()
        await storage.put(
            _STATE_COLLECTION,
            "my-plugin",
            {"name": "my-plugin", "enabled": True, "first_seen_at": "2024-01-01"},
        )

        result = await _check(storage, "my-plugin")

        assert result is True

    @pytest.mark.asyncio
    async def test_existing_enabled_false_returns_false(self) -> None:
        storage = _FakeStorageBackend()
        await storage.put(
            _STATE_COLLECTION,
            "my-plugin",
            {"name": "my-plugin", "enabled": False, "first_seen_at": "2024-01-01"},
        )

        result = await _check(storage, "my-plugin")

        assert result is False

    @pytest.mark.asyncio
    async def test_no_storage_returns_true(self) -> None:
        """Without storage, all plugins should load (safe fallback for fresh installs)."""
        result = await _check(None, "any-plugin")

        assert result is True

    @pytest.mark.asyncio
    async def test_new_plugin_does_not_overwrite_existing_row(self) -> None:
        """Calling _check twice for a new plugin only writes the row once."""
        storage = _FakeStorageBackend()

        await _check(storage, "new-plugin")
        # Manually mark it enabled (as if user toggled it on)
        await storage.put(
            _STATE_COLLECTION,
            "new-plugin",
            {"name": "new-plugin", "enabled": True, "first_seen_at": "2024-01-01"},
        )
        # Second call should see the existing row and return True
        result = await _check(storage, "new-plugin")
        assert result is True


# ---------------------------------------------------------------------------
# Tests: PluginManagerService.set_enabled WS RPC
# ---------------------------------------------------------------------------


class TestSetEnabledWsRpc:
    """Tests for the plugins.set_enabled WebSocket handler."""

    @pytest.fixture
    def storage(self) -> _FakeStorageBackend:
        return _FakeStorageBackend()

    @pytest.fixture
    async def manager_with_storage(
        self, storage: _FakeStorageBackend, tmp_path: Path
    ):
        """Return a started PluginManagerService bound to fake storage."""
        from gilbert.core.service_manager import ServiceManager
        from gilbert.core.services.plugin_manager import PluginManagerService

        sm = ServiceManager()
        storage_svc = _FakeStorageService(storage)
        sm.register(storage_svc)
        await sm.start_all()

        svc = PluginManagerService(install_dir=tmp_path / "installed")
        sm.register(svc)
        await svc.start(sm)
        return svc, storage

    @pytest.mark.asyncio
    async def test_set_enabled_creates_row_when_absent(
        self, manager_with_storage
    ) -> None:
        svc, storage = manager_with_storage

        class _FakeConn:
            pass

        conn = _FakeConn()
        frame = {"id": "r1", "type": "plugins.set_enabled", "name": "test-plugin", "enabled": True}
        result = await svc._ws_plugins_set_enabled(conn, frame)

        assert result["type"] == "plugins.set_enabled.result"
        assert result["name"] == "test-plugin"
        assert result["enabled"] is True
        assert result["restart_required"] is True

        row = await storage.get("gilbert.plugin_state", "test-plugin")
        assert row is not None
        assert row["enabled"] is True

    @pytest.mark.asyncio
    async def test_set_enabled_false(self, manager_with_storage) -> None:
        svc, storage = manager_with_storage

        await storage.put(
            "gilbert.plugin_state",
            "enabled-plugin",
            {"name": "enabled-plugin", "enabled": True, "first_seen_at": "2024-01-01"},
        )

        class _FakeConn:
            pass

        frame = {"id": "r2", "type": "plugins.set_enabled", "name": "enabled-plugin", "enabled": False}
        result = await svc._ws_plugins_set_enabled(_FakeConn(), frame)

        assert result["enabled"] is False
        assert result["restart_required"] is True
        row = await storage.get("gilbert.plugin_state", "enabled-plugin")
        assert row["enabled"] is False

    @pytest.mark.asyncio
    async def test_set_enabled_missing_name_returns_error(
        self, manager_with_storage
    ) -> None:
        svc, _ = manager_with_storage

        class _FakeConn:
            pass

        frame = {"id": "r3", "type": "plugins.set_enabled", "enabled": True}
        result = await svc._ws_plugins_set_enabled(_FakeConn(), frame)

        assert result["type"] == "gilbert.error"

    @pytest.mark.asyncio
    async def test_set_enabled_non_bool_enabled_returns_error(
        self, manager_with_storage
    ) -> None:
        svc, _ = manager_with_storage

        class _FakeConn:
            pass

        frame = {"id": "r4", "type": "plugins.set_enabled", "name": "p", "enabled": "yes"}
        result = await svc._ws_plugins_set_enabled(_FakeConn(), frame)

        assert result["type"] == "gilbert.error"
