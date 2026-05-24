# Default plugins ON, default services OFF

**Date:** 2026-05-24
**Status:** Design approved verbally; ready for implementation plan.

## Problem

When a new plugin lands in `std-plugins/` (e.g. a fresh submodule update),
the current first-discovery flow writes a `gilbert.plugin_state` row with
`enabled=False` and **skips `setup()` entirely**. The plugin's UI panels,
settings page, slash commands, and services are invisible until the user
finds the plugin in `/plugins`, toggles it on, and restarts.

This made the recently-added `voice-agent` plugin silently absent for the
user: it shipped, the submodule updated, but `/voice` never appeared in
the nav because the discovery default kept the plugin asleep.

The asymmetric problem: a brand-new plugin's *services* might do
real-world work the moment they start (poll APIs, hold STT streams open,
make outbound calls). Auto-loading the plugin should not also
auto-enable its services.

## Goal

Flip the two defaults independently:

1. **Plugins** default to **enabled** on first discovery — load their
   `setup()`, register everything, surface their UI.
2. **Toggleable services** default to **disabled** when no config row
   exists — the user opts each one in from `/settings → Services` after
   reading what it does.

User can `git pull` a new plugin, restart, see the new feature in the
nav and settings, configure its credentials, then turn its service on.

## Non-goals

- **No migration / backfill.** Existing rows keep their explicit state.
  A plugin previously disabled stays disabled; a service with
  `enabled: true` already in its config keeps running.
- **No central enforcement.** Service-level defaults stay per-service.
  Pushing the default into the `Service` base class would be more code
  than this change touches and would force every future service to
  remember an opt-in pattern.
- **No retroactive enable.** Plugins / services already in the DB with
  `enabled=False` rows are not touched.

## Changes

### 1. Plugin discovery default — `src/gilbert/core/app.py`

In `_check_plugin_enabled` (≈ line 593), the missing-row branch
currently writes `enabled=False` and returns `False`. Flip both:

```python
# Before
await storage.put(_STATE_COLLECTION, name, {
    "_id": name,
    "name": name,
    "enabled": False,
    "first_seen_at": now,
})
logger.info("New plugin discovered: %s — defaulting to disabled. ...")
return False

# After
await storage.put(_STATE_COLLECTION, name, {
    "_id": name,
    "name": name,
    "enabled": True,
    "first_seen_at": now,
})
logger.info("New plugin discovered: %s — defaulting to enabled.")
return True
```

Update the surrounding docstring's decision table to match.

### 2. Service-level defaults — flip the four outliers

Audit of `section.get("enabled", …)` and `_DEFAULT_ENABLED` constants
across `src/gilbert/core/services/` and `std-plugins/` shows almost all
toggleable services already default to `False`. Four exceptions need
flipping:

| File | Line | Change |
|---|---|---|
| `src/gilbert/core/services/ocr.py` | 57 | `section.get("enabled", True)` → `False` |
| `src/gilbert/core/services/inbox.py` | 265 | `section.get("enabled", True)` → `False` |
| `std-plugins/voice-agent/voice_agent_service.py` | 1225–1232 | Flip `section.get("enabled", True)` → `False`. Rewrite the surrounding 5-line comment (which currently explains why the default mirrors plugin.yaml's `enabled: true`) — the new rationale is "toggleable services default off; user opts in via `/settings → Services`." |
| `src/gilbert/core/services/proposals.py` | 339 | `_DEFAULT_ENABLED = True` → `False` (auto-propagates to `__init__`, the `ConfigParam` `default=`, and `start()` via `config.get("enabled", self._DEFAULT_ENABLED)`) |

### 3. Drop `enabled: true` from voice-agent's plugin.yaml

`std-plugins/voice-agent/plugin.yaml` is the only plugin manifest that
seeds `config.enabled: true`. Every other plugin omits the key and lets
its service decide. Remove the line so the new default-off rule isn't
undone the first time the plugin loads on a fresh install.

## Testing

- **Unit test** for `_check_plugin_enabled`: missing row → writes
  `enabled=True`, returns `True`. (Existing tests cover the
  row-exists-True and row-exists-False branches.)
- **Spot-check service tests:** the proposals test suite very likely
  asserts the old default-on behavior; update.
- **Manual verification (this install):** the plugin-default change is
  a no-op for already-known plugins like `voice-agent` (their existing
  `enabled=False` rows win). To verify the plugin path, either (a)
  delete the `voice-agent` row from the `gilbert.plugin_state`
  collection before restart and confirm it now loads, or (b) verify on
  a clean install. To verify the service path, restart and confirm
  ocr / inbox / voice-agent / proposals all appear as off in
  `/settings → Services`.

## Risk

Low but visible. On this install (which has explicit `enabled=False`
rows for previously-disabled plugins) the plugin change is a no-op for
already-known plugins — only future plugins benefit. The service flips
will stop four services on next restart; user accepted this
("just flip it; accept that existing services stop").
