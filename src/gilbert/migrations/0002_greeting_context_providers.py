"""Translate greeting.include_* + per-source templates onto the
GreetingContextProvider model.

Idempotent: re-running computes the same outputs from the same inputs.
After translation, the old keys are removed from greeting's config.
"""

from __future__ import annotations

from gilbert.migrations.runner import MigrationContext

description = "Translate greeting include_* flags to enabled_context_providers"


async def up(ctx: MigrationContext) -> None:
    storage = ctx.storage
    greeting = await storage.get("gilbert.config", "greeting")
    if greeting is None:
        return

    old_include_weather = greeting.pop("include_weather", None)
    old_include_briefing = greeting.pop("include_briefing", None)
    old_include_health = greeting.pop("include_health_brief", None)
    old_weather_template = greeting.pop("weather_hint_template", None)
    old_briefing_max = greeting.pop("briefing_max_seconds", None)

    # Only emit enabled_context_providers if at least one old flag was
    # set explicitly. If none were set, leave the new key absent so the
    # service falls back to its "all discovered" default.
    explicit_flags = any(
        v is not None
        for v in (old_include_weather, old_include_briefing, old_include_health)
    )
    if explicit_flags:
        enabled: list[str] = []
        if old_include_weather is not False:  # treat None as default-on (matches pre-migration default)
            enabled.append("weather")
        if old_include_briefing is True:  # default-off, only include when explicitly True
            enabled.append("briefing")
        if old_include_health is not False:
            enabled.append("health")
        greeting["enabled_context_providers"] = enabled

    await storage.put("gilbert.config", "greeting", greeting)

    if old_weather_template:
        weather = await storage.get("gilbert.config", "weather") or {}
        weather["weather_hint_template"] = old_weather_template
        await storage.put("gilbert.config", "weather", weather)

    if old_briefing_max is not None:
        feed_briefing = await storage.get("gilbert.config", "feed_briefing") or {}
        feed_briefing["briefing_max_seconds"] = old_briefing_max
        await storage.put("gilbert.config", "feed_briefing", feed_briefing)
