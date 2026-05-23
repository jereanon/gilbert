"""Tests for PluginManagerService — install/uninstall/list_installed flows."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

from gilbert.core.app import LoadedPlugin
from gilbert.core.service_manager import ServiceManager
from gilbert.core.services.plugin_manager import (
    _INSTALL_COLLECTION,
    PluginManagerService,
)
from gilbert.interfaces.plugin import Plugin, PluginContext, PluginMeta
from gilbert.interfaces.service import Service, ServiceInfo
from gilbert.plugins.loader import PluginError

# ── Fakes ────────────────────────────────────────────────────────────


class _FakeStorageBackend:
    """Minimal in-memory storage that satisfies the calls PluginManagerService
    actually makes (put/get/delete/query). Not a full StorageBackend."""

    def __init__(self) -> None:
        self.data: dict[str, dict[str, dict[str, Any]]] = {}

    async def put(self, collection: str, entity_id: str, data: dict[str, Any]) -> None:
        self.data.setdefault(collection, {})[entity_id] = dict(data)

    async def get(self, collection: str, entity_id: str) -> dict[str, Any] | None:
        return self.data.get(collection, {}).get(entity_id)

    async def delete(self, collection: str, entity_id: str) -> None:
        self.data.get(collection, {}).pop(entity_id, None)

    async def query(self, query: Any) -> list[dict[str, Any]]:
        return list(self.data.get(query.collection, {}).values())


class _FakeStorageService(Service):
    """Service shell exposing the StorageProvider protocol for the manager."""

    def __init__(self) -> None:
        self.backend = _FakeStorageBackend()
        self.raw_backend = self.backend

    def service_info(self) -> ServiceInfo:
        return ServiceInfo(
            name="entity_storage",
            capabilities=frozenset({"entity_storage"}),
        )

    def create_namespaced(self, namespace: str) -> Any:
        # Not used by PluginManagerService; satisfies the protocol.
        return self.backend


@dataclass
class _FakePluginConfig:
    config: dict[str, dict[str, Any]] = field(default_factory=dict)
    directories: list[str] = field(default_factory=list)


@dataclass
class _FakeGilbertConfig:
    plugins: _FakePluginConfig = field(default_factory=_FakePluginConfig)


class _FakeGilbert:
    """Minimal stand-in for ``Gilbert`` with the surface the manager needs."""

    def __init__(
        self,
        service_manager: ServiceManager,
        install_dir: Path,
    ) -> None:
        self.service_manager = service_manager
        self.config = _FakeGilbertConfig(
            plugins=_FakePluginConfig(directories=[str(install_dir)]),
        )
        self._loaded: list[LoadedPlugin] = []

    def make_plugin_context(self, name: str) -> PluginContext:
        return PluginContext(
            services=self.service_manager,
            config={},
            data_dir=Path("/tmp/plugin-data") / name,
            storage=None,
        )

    def list_loaded_plugins(self) -> list[LoadedPlugin]:
        return list(self._loaded)

    def find_loaded_plugin(self, name: str) -> LoadedPlugin | None:
        for entry in self._loaded:
            if entry.plugin.metadata().name == name:
                return entry
        return None

    def add_loaded_plugin(self, entry: LoadedPlugin) -> None:
        self._loaded.append(entry)

    def remove_loaded_plugin(self, name: str) -> LoadedPlugin | None:
        for i, entry in enumerate(self._loaded):
            if entry.plugin.metadata().name == name:
                return self._loaded.pop(i)
        return None

    def list_discovered_manifests(self) -> list[Any]:
        return []


# ── Plugin source helpers ────────────────────────────────────────────


PLUGIN_PY_TEMPLATE = """
from gilbert.interfaces.plugin import Plugin, PluginMeta, PluginContext
from gilbert.interfaces.service import Service, ServiceInfo

class _DummySvc(Service):
    def service_info(self) -> ServiceInfo:
        return ServiceInfo(
            name="{svc_name}",
            capabilities=frozenset({{"{svc_name}_cap"}}),
        )
    async def start(self, resolver) -> None:
        pass
    async def stop(self) -> None:
        pass

class _P(Plugin):
    def metadata(self) -> PluginMeta:
        return PluginMeta(name="{name}", version="{version}")
    async def setup(self, context: PluginContext) -> None:
        context.services.register(_DummySvc())
    async def teardown(self) -> None:
        pass

def create_plugin() -> Plugin:
    return _P()
"""


PLUGIN_PY_BROKEN_SETUP = """
from gilbert.interfaces.plugin import Plugin, PluginMeta, PluginContext
from gilbert.interfaces.service import Service, ServiceInfo

class _DummySvc(Service):
    def service_info(self) -> ServiceInfo:
        return ServiceInfo(
            name="broken_svc",
            capabilities=frozenset({"broken_svc_cap"}),
        )
    async def start(self, resolver) -> None:
        pass
    async def stop(self) -> None:
        pass

class _P(Plugin):
    def metadata(self) -> PluginMeta:
        return PluginMeta(name="broken-plugin", version="1.0.0")
    async def setup(self, context: PluginContext) -> None:
        context.services.register(_DummySvc())
        raise RuntimeError("setup blew up")
    async def teardown(self) -> None:
        pass

def create_plugin() -> Plugin:
    return _P()
"""


def _build_plugin_source(parent: Path, name: str, version: str = "1.0.0") -> Path:
    """Build a real plugin directory we can hand the loader."""
    plugin_dir = parent / name
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.yaml").write_text(
        yaml.safe_dump(
            {
                "name": name,
                "version": version,
                "description": f"{name} for tests",
            }
        )
    )
    svc_name = name.replace("-", "_") + "_svc"
    (plugin_dir / "plugin.py").write_text(
        PLUGIN_PY_TEMPLATE.format(name=name, version=version, svc_name=svc_name),
    )
    return plugin_dir


def _build_broken_plugin_source(parent: Path) -> Path:
    plugin_dir = parent / "broken-plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "broken-plugin",
                "version": "1.0.0",
                "description": "intentionally broken",
            }
        )
    )
    (plugin_dir / "plugin.py").write_text(PLUGIN_PY_BROKEN_SETUP)
    return plugin_dir


def _patch_loader_to_use_local_source(svc: PluginManagerService, source: Path) -> None:
    """Replace _fetch_to so install_from_url copies a local dir instead of
    going to the network."""

    async def fake_fetch_to(url: str, stage_path: Path) -> Path:
        import shutil

        target = stage_path / "fetched"
        shutil.copytree(source, target)
        return target

    svc._loader._fetch_to = fake_fetch_to  # type: ignore[method-assign]


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
async def setup(tmp_path: Path) -> tuple[PluginManagerService, _FakeGilbert, _FakeStorageService]:
    install_dir = tmp_path / "installed"
    sm = ServiceManager()
    storage = _FakeStorageService()
    sm.register(storage)
    await sm.start_all()

    svc = PluginManagerService(install_dir=install_dir)
    sm.register(svc)
    await svc.start(sm)

    gilbert = _FakeGilbert(sm, install_dir)
    svc.bind_gilbert(gilbert)
    return svc, gilbert, storage


# ── Tests ────────────────────────────────────────────────────────────


class TestInstall:
    @pytest.mark.asyncio
    async def test_install_loads_plugin_and_starts_services(
        self,
        setup: tuple[PluginManagerService, _FakeGilbert, _FakeStorageService],
        tmp_path: Path,
    ) -> None:
        svc, gilbert, storage = setup
        source = _build_plugin_source(tmp_path / "src", "demo-plugin")
        _patch_loader_to_use_local_source(svc, source)

        record = await svc.install(gilbert, "https://example.com/x.zip")

        assert record.name == "demo-plugin"
        assert record.version == "1.0.0"
        assert record.registered_services == ["demo_plugin_svc"]
        # Service is started in the manager.
        assert "demo_plugin_svc" in gilbert.service_manager.started_services
        # LoadedPlugin entry was added to the gilbert app.
        loaded = gilbert.find_loaded_plugin("demo-plugin")
        assert loaded is not None
        assert loaded.registered_services == ["demo_plugin_svc"]
        # Registry row persisted.
        row = await storage.backend.get(_INSTALL_COLLECTION, "demo-plugin")
        assert row is not None
        assert row["source_url"] == "https://example.com/x.zip"
        assert row["registered_services"] == ["demo_plugin_svc"]

    @pytest.mark.asyncio
    async def test_install_rolls_back_on_setup_failure(
        self,
        setup: tuple[PluginManagerService, _FakeGilbert, _FakeStorageService],
        tmp_path: Path,
    ) -> None:
        svc, gilbert, storage = setup
        source = _build_broken_plugin_source(tmp_path / "src")
        _patch_loader_to_use_local_source(svc, source)

        with pytest.raises(RuntimeError, match="setup blew up"):
            await svc.install(gilbert, "https://example.com/broken.zip")

        # Install directory was cleaned up.
        assert not (svc._install_dir / "broken-plugin").exists()
        # No registry row.
        assert await storage.backend.get(_INSTALL_COLLECTION, "broken-plugin") is None
        # broken_svc was registered during setup() before the raise; rollback
        # should have torn it down.
        assert "broken_svc" not in gilbert.service_manager.list_services()
        # No LoadedPlugin entry.
        assert gilbert.find_loaded_plugin("broken-plugin") is None
        # No record in the manager.
        assert "broken-plugin" not in svc._records

    @pytest.mark.asyncio
    async def test_install_duplicate_raises_without_force(
        self,
        setup: tuple[PluginManagerService, _FakeGilbert, _FakeStorageService],
        tmp_path: Path,
    ) -> None:
        svc, gilbert, _ = setup
        source = _build_plugin_source(tmp_path / "src", "dupe")
        _patch_loader_to_use_local_source(svc, source)

        await svc.install(gilbert, "https://example.com/dupe.zip")

        with pytest.raises(PluginError, match="already installed"):
            await svc.install(gilbert, "https://example.com/dupe.zip")


class TestUninstall:
    @pytest.mark.asyncio
    async def test_uninstall_removes_services_and_registry_row(
        self,
        setup: tuple[PluginManagerService, _FakeGilbert, _FakeStorageService],
        tmp_path: Path,
    ) -> None:
        svc, gilbert, storage = setup
        source = _build_plugin_source(tmp_path / "src", "uninstall-me")
        _patch_loader_to_use_local_source(svc, source)
        await svc.install(gilbert, "https://example.com/x.zip")

        await svc.uninstall(gilbert, "uninstall-me")

        # Service unregistered.
        assert "uninstall_me_svc" not in gilbert.service_manager.list_services()
        # Plugin no longer in the loaded list.
        assert gilbert.find_loaded_plugin("uninstall-me") is None
        # Registry row gone.
        assert await storage.backend.get(_INSTALL_COLLECTION, "uninstall-me") is None
        # In-memory record gone.
        assert "uninstall-me" not in svc._records
        # Directory removed from disk.
        assert not (svc._install_dir / "uninstall-me").exists()

    @pytest.mark.asyncio
    async def test_uninstall_unknown_raises(
        self,
        setup: tuple[PluginManagerService, _FakeGilbert, _FakeStorageService],
    ) -> None:
        svc, gilbert, _ = setup
        with pytest.raises(LookupError):
            await svc.uninstall(gilbert, "ghost")


class TestListInstalled:
    @pytest.mark.asyncio
    async def test_list_includes_runtime_installed(
        self,
        setup: tuple[PluginManagerService, _FakeGilbert, _FakeStorageService],
        tmp_path: Path,
    ) -> None:
        svc, gilbert, _ = setup
        source = _build_plugin_source(tmp_path / "src", "listed-plugin")
        _patch_loader_to_use_local_source(svc, source)
        await svc.install(gilbert, "https://example.com/x.zip")

        rows = await svc.list_installed(gilbert)
        names = [r["name"] for r in rows]
        assert "listed-plugin" in names
        row = next(r for r in rows if r["name"] == "listed-plugin")
        assert row["source"] == "installed"
        assert row["running"] is True
        assert row["uninstallable"] is True
        assert row["source_url"] == "https://example.com/x.zip"

    @pytest.mark.asyncio
    async def test_list_includes_boot_loaded_only(
        self,
        setup: tuple[PluginManagerService, _FakeGilbert, _FakeStorageService],
        tmp_path: Path,
    ) -> None:
        svc, gilbert, _ = setup

        # Simulate a plugin that was loaded at boot from std-plugins.
        std_dir = tmp_path / "std-plugins"
        std_dir.mkdir()
        plugin_path = std_dir / "boot-plugin"
        plugin_path.mkdir()

        class _BootPlugin(Plugin):
            def metadata(self) -> PluginMeta:
                return PluginMeta(name="boot-plugin", version="0.5.0")

            async def setup(self, context: PluginContext) -> None:
                pass

            async def teardown(self) -> None:
                pass

        gilbert.add_loaded_plugin(
            LoadedPlugin(
                plugin=_BootPlugin(),
                install_path=plugin_path,
                registered_services=[],
            )
        )
        gilbert.config.plugins.directories = [str(std_dir), str(svc._install_dir)]

        rows = await svc.list_installed(gilbert)
        row = next(r for r in rows if r["name"] == "boot-plugin")
        assert row["source"] == "std"
        assert row["uninstallable"] is False
        assert row["source_url"] is None
