"""Seed ``gilbert.plugin_state`` so existing installs keep their plugins enabled.

Before this migration, no ``gilbert.plugin_state`` rows exist.  After
this migration:

- Every plugin *currently discoverable on disk* has a row with
  ``enabled=True``.  This ensures existing installations continue
  working — the new default-disabled load logic introduced in the same
  change only affects plugins that are added *after* this migration ran.

Idempotent: existing rows are left untouched (upsert only inserts when
the row is absent).  Running the migration twice on the same database
yields identical state.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from gilbert.migrations.runner import MigrationContext
from gilbert.plugins.loader import PluginLoader

logger = logging.getLogger(__name__)

description = "Seed plugin_state rows for existing plugins so they stay enabled after upgrade"

_STATE_COLLECTION = "gilbert.plugin_state"


async def up(ctx: MigrationContext) -> None:
    """Mark every currently-discoverable plugin as enabled=True.

    Reads the plugin directories from the running config (via
    ``ctx.repo_root`` to find ``gilbert.yaml``), scans them for
    manifests, and writes one ``gilbert.plugin_state`` row per plugin
    if no row already exists.
    """
    directories = _find_plugin_directories(ctx.repo_root)
    if not directories:
        ctx.log.info(
            "migration 0003: no plugin directories found — nothing to seed"
        )
        return

    loader = PluginLoader()
    manifests = loader.scan_directories([str(d) for d in directories])

    now = datetime.now(UTC).isoformat()
    seeded = 0
    skipped = 0

    for manifest in manifests:
        existing = await ctx.storage.get(_STATE_COLLECTION, manifest.name)
        if existing is not None:
            ctx.log.debug(
                "migration 0003: plugin %s already has a state row — skipping",
                manifest.name,
            )
            skipped += 1
            continue

        await ctx.storage.put(
            _STATE_COLLECTION,
            manifest.name,
            {
                "_id": manifest.name,
                "name": manifest.name,
                "enabled": True,
                "first_seen_at": now,
            },
        )
        ctx.log.info(
            "migration 0003: seeded plugin %s as enabled=True",
            manifest.name,
        )
        seeded += 1

    ctx.log.info(
        "migration 0003: done — seeded %d plugin(s), skipped %d existing row(s)",
        seeded,
        skipped,
    )


def _find_plugin_directories(repo_root: Path) -> list[Path]:
    """Return the list of plugin directories from gilbert.yaml.

    Falls back to the three conventional directories
    (``std-plugins/``, ``local-plugins/``, ``installed-plugins/``)
    if the config can't be parsed.  Only directories that actually
    exist on disk are returned.
    """
    config_path = repo_root / "gilbert.yaml"
    if config_path.is_file():
        try:
            import yaml  # type: ignore[import-untyped]

            with open(config_path) as f:
                raw = yaml.safe_load(f) or {}
            plugins_raw = raw.get("plugins", {})
            if isinstance(plugins_raw, dict):
                dirs_raw: list[str] = plugins_raw.get("directories", [])
                if dirs_raw:
                    return [
                        d
                        for raw_d in dirs_raw
                        if (d := Path(raw_d).expanduser().resolve()).is_dir()
                    ]
        except Exception as exc:
            logger.debug(
                "migration 0003: could not read gilbert.yaml (%s) — using defaults",
                exc,
            )

    # Fallback: conventional directory names relative to repo root.
    candidates = [
        repo_root / "std-plugins",
        repo_root / "local-plugins",
        repo_root / "installed-plugins",
    ]
    return [d for d in candidates if d.is_dir()]
