# show5-firmware

Rust thin-client firmware for the **IoTeikXgo 5″ ESP32-P4 display** (Amazon `B0GR5G2H41`),
the same board the [`hardware/show5-enclosure/`](../../hardware/show5-enclosure/) is
built around.

Pairs with a Gilbert instance over WebSocket — Gilbert composes the UI server-side and
pushes a small JSON widget tree; the firmware materializes LVGL widgets and routes touch
events back. No UI logic lives on-device.

See [`docs/plans/2026-05-29-show5-firmware.md`](../../docs/plans/2026-05-29-show5-firmware.md)
for the full architecture, phase plan, and protocol.

## Status

**Phase 0** — toolchain + skeleton. Compiles for `riscv32imafc-unknown-none-elf`,
boots ESP-IDF, logs a heartbeat. No screen, no Wi-Fi, no WebSocket yet.

## Build

Prereqs (one-time on macOS):

```bash
brew install ninja cmake python3
cargo install espup espflash ldproxy cargo-generate
espup install --targets esp32p4,esp32c6
. ~/export-esp.sh   # sets LIBCLANG_PATH + xtensa toolchain (no-op for P4 but harmless)
```

Build:

```bash
cd firmware/show5-firmware
cargo build --release
```

First build pulls ESP-IDF v5.4 + its LLVM toolchain into `~/.espressif/` and takes
5–10 minutes. Subsequent builds are under a minute.

## Flash + monitor (once the board arrives)

```bash
cargo run --release   # ``espflash flash --monitor`` is wired as the Cargo runner
```

Hold BOOT, tap RESET, release BOOT to enter download mode on first flash. Subsequent
flashes can use auto-reset (the board's USB-CDC handles DTR/RTS).

## Phase 0.5 OTA workflow (planned)

Once Phase 0.5 lands, the iteration loop becomes:

```bash
make ota DEVICE=kitchen   # build → SHA256 → upload to Gilbert → trigger
```

— and the new binary lands on the screen in <30s without touching the USB cable.

## File layout

```
Cargo.toml              workspace + esp-idf-svc deps
rust-toolchain.toml     pinned nightly (for -Z build-std)
.cargo/config.toml      target=riscv32imafc + ldproxy + espflash runner
build.rs                embuild ESP-IDF bootstrap
sdkconfig.defaults      ESP-IDF config overrides (PSRAM, Wi-Fi-remote, partitions)
partitions.csv          dual-OTA-slot layout
src/main.rs             entry — currently just a logging heartbeat
```
