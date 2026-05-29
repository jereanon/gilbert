# Show5 Firmware — ESP32-P4 Rust Thin Client

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rust-based firmware for the IoTeikXgo 5" ESP32-P4 display (Amazon `B0GR5G2H41`, the same board the [`show5-enclosure`](../../hardware/show5-enclosure/) is built for) that acts as a thin, server-controlled UI surface for a Gilbert instance. The device boots, connects to a paired Gilbert over WebSocket, and renders whatever screen Gilbert sends — there is no UI logic on-device. Touch events round-trip back as tool/event calls.

**v1 scope is intentionally narrow:** Gilbert can push an arbitrary widget tree onto the screen via a new `show_on_display` AI tool. No bundled dashboards, no transcript view, no notification center on-device. Those are higher-level features built ON TOP of the push primitive — and they belong server-side so they're editable without flashing firmware.

**Why this shape**

- The Gilbert architecture already separates compose-the-UI (server, full Python) from render-it (web SPA or, here, a tiny client). Reusing that pattern keeps every iteration on the screen a Python edit, not a firmware build.
- A `show_on_display` tool means the LLM can decide to use the screen ("I'll show that on the kitchen display"). Higher-level dashboards/transcripts become Python callers of the same tool.
- Pushing structured widgets (vs. pre-rendered pixels) keeps bandwidth tiny, touch events localizable, and the screen content auditable from Gilbert's storage.

**Tech stack**

- **Firmware:** Rust. Runtime (`esp-idf-svc` std vs `esp-hal` no_std) decided after Phase 0 spike — see "Open decisions" below. LVGL via `lvgl-rs` bindings for rendering. JSON via `serde`. WebSocket client over TLS.
- **Hardware:** ESP32-P4 main MCU + ESP32-C6 hosted radio (Wi-Fi 6 + BLE 5.3), 800×480 IPS touch.
- **Gilbert side:** new `interfaces/display.py` capability, `std-plugins/display-kiosk/` plugin (Service + ToolProvider + WS server), `/displays` admin SPA page, per-device pairing entities in `gilbert.kiosk_devices` collection.

---

## Architecture overview

### Transport

- WebSocket over TLS to `wss://<gilbert>/api/display/connect`. Long-lived; firmware auto-reconnects with exponential backoff.
- Initial frame from firmware: `{type: "hello", device_id, fw_version, screen: {w, h, dpi}, caps: ["touch", "audio_in", "audio_out"]}`.
- Auth via per-device API key (provisioned out-of-band, stored in NVS). Sent as a `Authorization` header on the WS upgrade.

### UI protocol (declarative widget tree)

Server pushes a complete or partial widget tree; firmware materializes into LVGL widgets. Tree is small JSON — under 4 KB for any reasonable screen.

```jsonc
// server → firmware: set the whole screen
{
  "type": "set_screen",
  "screen_id": "weather_pop",
  "widgets": [
    {"type": "column", "id": "root", "pad": 16, "children": [
      {"type": "label", "id": "title", "text": "Tomorrow", "font": "lg"},
      {"type": "row", "id": "temps", "children": [
        {"type": "label", "id": "hi", "text": "72°", "font": "xl"},
        {"type": "label", "id": "lo", "text": "54°", "font": "md", "color": "gray"}
      ]},
      {"type": "button", "id": "dismiss", "text": "OK", "action": "dismiss"}
    ]}
  ]
}
```

```jsonc
// firmware → server: touch event
{"type": "touch", "widget_id": "dismiss", "action": "dismiss"}

// firmware → server: heartbeat (every 15s)
{"type": "heartbeat", "uptime_s": 4231}
```

**v1 widget vocabulary** (kept minimal — every widget must materialize trivially to LVGL):

| Widget | Fields | Notes |
|---|---|---|
| `label` | `text`, `font?` (sm/md/lg/xl), `color?`, `align?` | Single-line; multi-line via `text-block`. |
| `text-block` | `text`, `font?`, `color?` | Wraps. |
| `image` | `src` (URL or `data:` base64), `w?`, `h?` | Image cached by URL hash. |
| `button` | `text`, `id`, `action`, `kind?` (primary/secondary) | Touch emits `{type:"touch", widget_id, action}`. |
| `row` / `column` | `children[]`, `pad?`, `gap?`, `align?` | Flex-ish layout. |
| `spacer` | `flex?: int` | Eats space. |
| `divider` | — | Hairline. |
| `list` | `items[]`, `select_action?` | Each item: `{id, text, subtitle?}`. |
| `text-input` | `id`, `placeholder?`, `value?`, `submit_action` | Touch-keyboard handled on device. |
| `modal` | `children[]`, `dismiss_action?` | Overlays; backdrop dim. |

`action` is an opaque string the server interprets. Firmware doesn't know what `"dismiss"` means — it just round-trips it.

**Partial updates** (Phase 1.5 if needed): `{type: "update_widget", widget_id, patch: {…}}` lets the server change a single label/value without re-pushing the whole tree. v1 may skip this and re-push everything; the JSON is small.

### Pairing

Same model as the Mentra plugin's per-user pairing:

- Device boots un-paired → starts BLE GATT service advertising `"gilbert-pair"`.
- Admin opens `/displays/pair` in the SPA on a phone, scans, enters Wi-Fi creds + Gilbert URL + a one-time pair code.
- Phone sends those to the device over BLE. Device joins Wi-Fi, posts to `POST /api/display/pair` with the code, receives a permanent API key.
- API key + Gilbert URL + Wi-Fi creds saved in NVS.
- Subsequent boots skip BLE and go straight to the WebSocket.

Re-pair: physical button held 5s, or remote command from Gilbert that wipes NVS.

### The `show_on_display` AI tool

Lives in `display-kiosk/kiosk_service.py` as part of the plugin's `ToolProvider`:

```python
@dataclass
class ShowOnDisplayParams:
    device_id: str          # which display
    screen: dict            # the widget tree (validated against schema)
    duration_seconds: int   # auto-revert to default screen after this long (0 = permanent)
```

The LLM uses this when it would otherwise say "I'll send that to your phone" / "let me show you" — instead it composes the widget tree and pushes. The tool is exposed as `/display.show` slash command too, taking JSON.

### Default screen

What the screen shows when no `show_on_display` is active. Configured per device. v1: a small clock with "Connected to Gilbert" status — server pushes this on connect and after any pushed screen's `duration_seconds` expires.

(Dashboards / transcript / notifications come later as server-side composers that push to the same protocol. Not in v1.)

---

## File structure

**Create (firmware repo — separate or `firmware/show5-firmware/` in Gilbert root):**

- `firmware/show5-firmware/Cargo.toml` — workspace + esp-idf or esp-hal deps (pinned after Phase 0).
- `firmware/show5-firmware/src/main.rs` — entry, boot, NVS load, pair-or-connect branch.
- `firmware/show5-firmware/src/wifi.rs` — C6 hosted Wi-Fi bring-up.
- `firmware/show5-firmware/src/ws_client.rs` — WebSocket connect + send + recv loop with reconnect.
- `firmware/show5-firmware/src/protocol/mod.rs` — `serde` types for every message in the protocol.
- `firmware/show5-firmware/src/lvgl_render.rs` — widget-tree → LVGL materializer + touch event mapping.
- `firmware/show5-firmware/src/nvs.rs` — persistent settings load/save.
- `firmware/show5-firmware/src/provisioning.rs` — BLE pairing GATT service.
- `firmware/show5-firmware/sdkconfig.defaults` — ESP-IDF config (PSRAM, screen pins, partition table).
- `firmware/show5-firmware/partitions.csv` — app / OTA / NVS layout.
- `firmware/show5-firmware/README.md` — flash + provisioning instructions.

**Create (Gilbert):**

- `src/gilbert/interfaces/display.py` — `Widget`, `Screen`, `TouchEvent`, `KioskDevice` dataclasses. `DisplayProvider` Protocol (`push_screen`, `list_devices`, etc.). Pure interfaces.
- `std-plugins/display-kiosk/plugin.py` / `plugin.yaml` / `pyproject.toml` / `__init__.py` — plugin scaffold.
- `std-plugins/display-kiosk/kiosk_service.py` — `KioskService` (`Service` + `Configurable` + `ToolProvider` + `WsHandlerProvider`). Manages device registry, exposes `show_on_display` tool + slash command, serves the WebSocket endpoint, owns the device pair flow.
- `std-plugins/display-kiosk/widgets.py` — server-side `WidgetBuilder` helpers so Python callers compose trees without raw dicts.
- `std-plugins/display-kiosk/migrations/0001_kiosk_devices.py` — entity collection schema.
- `std-plugins/display-kiosk/frontend/DisplaysPage.tsx` — admin UI: list devices, pair a new one, preview last-pushed screen, force-reset.
- `std-plugins/display-kiosk/frontend/panels.ts` — registers the page.
- `src/gilbert/web/routes/display_ws.py` — WS endpoint (`/api/display/connect`) + pair endpoint (`/api/display/pair`).
- `tests/unit/test_display_protocol.py` — round-trip serialize/deserialize of every widget kind.
- `std-plugins/display-kiosk/tests/test_kiosk_service.py` — service tests with a fake WS connection.

**Modify:**

- `README.md` — short line about the display-kiosk plugin.
- `std-plugins/README.md` — full per-plugin section (config keys, slash commands, deps).
- `std-plugins/CLAUDE.md` — no changes anticipated unless the protocol-doc convention is new.

---

## Open decisions

These get answered as Phase 0 progresses. Capture the choice in this doc when made.

- **Runtime: `esp-idf-svc` vs `esp-hal`.** Spike both for 1–2 days, pick the one that gets Wi-Fi up + LVGL on screen + WS connected faster. Default leans `esp-idf-svc` for v1 (mature C6 hosted Wi-Fi, OTA, BLE provisioning); reserve `esp-hal` for v2 no_std rewrite if power/footprint justifies it.

  **Phase 0 spike result (esp-idf-svc track, 2026-05-29):** scaffolded, builds
  cleanly for `riscv32imafc-esp-espidf` on `esp-idf-svc 0.52` / `esp-idf-hal 0.46`
  / `esp-idf-sys 0.37` + ESP-IDF v5.4. First build (cold) ~5 min including ESP-IDF
  download + LLVM toolchain. Incremental rebuilds <50 s. Binary size 724 KB
  (debug-stripped release), comfortably inside a 2 MiB OTA slot. Toolchain cache
  is 5.1 GB under `.embuild/` (one-time). No hardware-in-the-loop yet — final
  pick happens after Phase 0 step 4 (Wi-Fi) and step 5 (WS echo) confirm the
  C6 hosted Wi-Fi path actually works. Plan B (esp-hal) deferred until either
  the C6 hosted path stalls or the no_std footprint becomes attractive.
- **TLS posture.** Self-signed cert + pinned root for an internal Gilbert? Or trust the system roots and require a real cert? Pick before Phase 1.
- **OTA channel.** Gilbert as OTA server (signed firmware blobs in entity storage) vs. point at a GitHub release URL? Phase 4 decision.
- **Multi-tenant.** Can one display serve multiple users (per-user lock-screens) or is it single-user device-only? Probably single-user-per-device for v1; multi-user is a Phase 5+ feature.

---

## Phase 0 — Spike + runtime decision (1–2 days)

**Goal:** Pick the Rust runtime and confirm the basic chain works end-to-end with a stubbed protocol.

- [ ] **Step 1: Toolchain install.** `espup install`, set up `cargo-espflash`, confirm both `esp-idf-template` and `esp-hal-template` build for the P4 target.
- [ ] **Step 2: Hello-screen (esp-idf-svc track).** Flash a binary that lights the screen with "Hello" via `lvgl-rs`. Record build time, binary size, RAM use.
- [ ] **Step 3: Hello-screen (esp-hal track).** Same goal via `esp-hal` + a no_std LVGL or embedded-graphics. Record same metrics.
- [ ] **Step 4: Wi-Fi up.** On whichever track reached a screen first, bring up Wi-Fi over the C6 (hosted). Connect to a hardcoded SSID, ping the dev Gilbert host. If the chosen track can't get C6 hosted up in a day, try the other.
- [ ] **Step 5: WebSocket echo.** Connect to a dummy `wss://` Gilbert endpoint, send `{type:"hello", …}`, receive a stub `set_screen`, log it.
- [ ] **Step 6: Record the decision in this doc** in the "Open decisions" section and update the file structure if it changes.

---

## Phase 0.5 — Minimum-viable OTA (1–2 days) ⭐ moved up from Phase 4

**Goal:** Stop USB-flashing. Every iteration after this lands over Wi-Fi, which is a 5–10× speedup on the dev loop.

This is intentionally **dev-grade, not production-grade**: unsigned binaries, simple dual-app partition layout, "just trust the Gilbert URL we paired with." Production hardening (signatures, rollback validation, anti-rollback nonces, secure boot) lives in Phase 4 and ships before the firmware leaves dev hands.

- [ ] **Step 1: Dual-app partition layout** in `partitions.csv` — two OTA slots (`ota_0`, `ota_1`) + `otadata` + NVS + factory app. Verify the build produces a binary small enough to fit one slot with headroom (P4 has plenty of flash, this is bookkeeping).
- [ ] **Step 2: OTA flow on device.** `esp_https_ota` (esp-idf-svc track) or rolled equivalent (esp-hal track). Fetch a firmware blob from a URL, write to the inactive slot, mark valid, reboot. Validate on next boot — if the new app doesn't ping back to Gilbert within N seconds, rollback to the old slot.
- [ ] **Step 3: OTA trigger over the WS.** Gilbert sends `{type: "ota_update", url: "https://…", expected_sha256: "…"}` (URL is on the Gilbert instance itself). Firmware downloads, verifies SHA, applies. No code signing yet — the SHA guards against transport corruption only.
- [ ] **Step 4: Gilbert hosts the binary.** `KioskService` accepts an uploaded `.bin` file (multipart POST or simple admin tool), stores it under the plugin data dir with a SHA256 sidecar, exposes `GET /api/display/firmware/<sha>.bin` for the device to download. No auth on the GET for v1 — the SHA is the secret.
- [ ] **Step 5: One-button dev workflow.** A shell script in `firmware/show5-firmware/` that: builds the binary, computes SHA256, uploads to Gilbert via REST, sends the OTA trigger over the WS to the named device. Target: `make ota DEVICE=test` lands the build on the screen in <30s.
- [ ] **Step 6: Rollback drill.** Intentionally push a broken binary (e.g. immediately panics). Confirm the device rolls back and reconnects with the old version. This is the single most important test in the phase — without it, a bad OTA bricks the device and you're back to USB.

**What Phase 4 ("OTA hardening") adds later:**
- Signed binaries (mbedtls signature verification on the device).
- Two-key rotation (current + next signing key).
- Stronger boot-validation: the new app must talk back over WS within 60s OR the bootloader rolls back, with no soft-failure mode.
- Anti-rollback counter so a known-compromised old version can't be re-applied.
- Audit log on Gilbert side of which device received which firmware when.

---

## Phase 1 — Protocol skeleton end-to-end (1 week)

**Goal:** A test Gilbert plugin can push a hardcoded screen to a paired device; touching a button comes back as a logged event.

### Gilbert side

- [ ] **Step 1: Define `interfaces/display.py`.** Dataclasses for every protocol message + widget kind. `DisplayProvider` Protocol with `push_screen`, `list_connected_devices`. Pure interfaces.
- [ ] **Step 2: Plugin scaffold.** `display-kiosk/` per `std-plugins/CLAUDE.md` conventions.
- [ ] **Step 3: KioskService skeleton.** Implements `Service` + `Configurable` + `ToolProvider`. Holds a `dict[device_id, WsConnection]` registry. No persistence yet — hardcode one device.
- [ ] **Step 4: WS endpoint at `/api/display/connect`.** Verifies a static API key for now. Adds the connection to the registry on `hello`, removes on disconnect.
- [ ] **Step 5: `show_on_display` AI tool.** Validates the widget tree against the protocol schema, sends `set_screen` to the named device. Returns success/error to the LLM.
- [ ] **Step 6: Slash command `/display.show`** that takes a device id + a JSON tree.
- [ ] **Step 7: Protocol round-trip tests** at `tests/unit/test_display_protocol.py` — every widget kind serializes and deserializes cleanly.

### Firmware side

- [ ] **Step 8: WS client with auth + reconnect.** Connects to a hardcoded Gilbert URL with a hardcoded API key. Exponential backoff on disconnect, capped at 30s.
- [ ] **Step 9: Protocol types.** `serde`-derived structs for `set_screen`, `update_widget` (stub), `touch`, `heartbeat`, `hello`.
- [ ] **Step 10: LVGL materializer.** Walk the widget tree, build LVGL objects, attach touch callbacks that emit `touch` messages.
- [ ] **Step 11: Heartbeat loop.** Every 15s emit a heartbeat with uptime.

### Demo

- [ ] **Step 12:** From the Gilbert chat / slash command, push a "Hello, Jeremy" screen with one button labelled "OK"; touching it logs the touch event on the server. Done = Phase 1 complete.

---

## Phase 2 — Pairing + persistence (3–4 days)

- [ ] **Step 1: NVS storage** for Wi-Fi creds, Gilbert URL, API key.
- [ ] **Step 2: BLE GATT pairing service** — `gilbert-pair` characteristic accepts a JSON blob with all four fields.
- [ ] **Step 3: `POST /api/display/pair`** server endpoint — accepts a pair code, returns an API key, writes a `KioskDevice` entity.
- [ ] **Step 4: Phone-side pairing UI** at `/displays/pair` — Wi-Fi creds form, generates pair code, polls until device joins.
- [ ] **Step 5: Re-pair button** — long-press a GPIO to wipe NVS and reboot into pair mode.

---

## Phase 3 — Server-side composers (1+ weeks, on top of v1 protocol)

Higher-level Python features that use `show_on_display`:

- [ ] **Dashboard composer** — periodically pushes weather/calendar/presence using the existing `greeting_context` providers.
- [ ] **Voice transcript composer** — subscribes to `conversation.*` bus events, pushes a transcript widget.
- [ ] **Notification composer** — listens to `NotificationProvider` events, pushes a modal with dismiss action.

(None of these need a firmware change. They're all `KioskService` consumers.)

---

## Phase 4 — OTA hardening + production polish (3–4 days)

Builds on the dev-grade OTA from Phase 0.5. By this phase the firmware ships out of dev hands so the security posture matters.

- [ ] Signed firmware blobs — mbedtls signature verification on device, key in NVS (or in eFuse on production).
- [ ] Two-key rotation flow (current + next signing key).
- [ ] Stronger boot-validation: new app MUST talk back over WS within 60s or bootloader rolls back. No soft-failure mode.
- [ ] Anti-rollback counter so known-compromised old versions can't be reapplied.
- [ ] Audit log on Gilbert side: which device received which firmware when, with hash + signing key id.
- [ ] Watchdog + brown-out reboot recovery.
- [ ] `/displays` admin page polish — last-seen, fw version, force update, OTA history.

---

## Phase 5 — Voice (deferred, v2)

The board has an onboard mic per the "AI Speech Interaction" spec. Out of scope for v1 — when this comes back the device joins the Mentra-class voice model (audio in over WS → `audio_blob_store`, voice_brain engine handles the conversation, results pushed back to the screen using the v1 protocol).

---

## Non-goals (v1)

- On-device dashboards or any UI that doesn't come from Gilbert.
- On-device voice/wake-word.
- LVGL animations beyond fade-in screen transitions.
- Offline mode — if Gilbert is unreachable, the device shows a "reconnecting" splash and retries.
- Multi-user lock screens.
- Local rendering of rich content (markdown, charts, plots) — keep the widget vocabulary tiny.
