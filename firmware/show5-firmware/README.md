# show5-firmware

Rust thin-client firmware for the **IoTeikXgo 5″ ESP32-P4 display** (Amazon `B0GR5G2H41`),
the same board the [`hardware/show5-enclosure/`](../../hardware/show5-enclosure/) is
built around.

Pairs with a Gilbert instance over WebSocket — Gilbert composes the UI server-side and
pushes a small JSON widget tree; the firmware materializes widgets and routes touch
events back. No UI logic lives on-device.

See [`docs/plans/2026-05-29-show5-firmware.md`](../../docs/plans/2026-05-29-show5-firmware.md)
for the full architecture, phase plan, runtime decision, and protocol.

## Status

**Phase 0 — esp-hal track, hello-world boots cleanly.** Compiles for
`riscv32imafc-unknown-none-elf`, the ROM bootloader loads us, image
segments map to HP flash + HP SRAM, app runs without panic.

Console output verification is pending — `jtag-serial` output via the
P4's native USB peripheral needs a cable on the *other* USB-C port.
UART0 output via the CH343 didn't appear; pin mapping for this board's
CH343 wiring is TBD.

No screen, no Wi-Fi, no WebSocket yet — next is Phase 0.5 (OTA so we
can iterate without USB) → Phase 1 (WebSocket protocol skeleton).

### Why esp-hal, not esp-idf-svc

The initial Phase 0 spike used `esp-idf-svc` (std-on-ESP-IDF). It built
cleanly but reproducibly panicked at boot on this chip's specific ROM
revision (`esp32p4-eco2-20240710`):

- ESP-IDF v5.4 / v5.5: Guru Meditation right after
  `cpu_start: Multicore app` — junk PC pointing into LP SRAM,
  consistent with a corrupt C++ ctor table during multicore startup.
- ESP-IDF v5.5.3: bootloader's first instruction faults as illegal.
- **Pristine upstream** `esp-idf-template` (P4) reproduces the
  v5.5.3 panic identically — it's not anything we configured.

esp-hal sidesteps the whole C++ ctor / multicore startup chain (no
libstd init, no FreeRTOS bring-up), runs directly on the RISC-V cores,
and boots cleanly on the same hardware.

## Build

Prereqs (one-time on macOS):

```bash
brew install ninja cmake python3
cargo install espup espflash ldproxy
espup install --targets esp32p4,esp32c6
```

For serial monitoring on this board:

- Install **CH34xVCPDriver** from the Mac App Store. Without it the
  WCH CH343 USB-UART chip enumerates on the bus but no `/dev/cu.*`
  appears.
- `cat /dev/cu.*` mangles the binary console output via the macOS tty
  line discipline. Read with PySerial (`pip install pyserial` then
  `python -m serial.tools.miniterm /dev/cu.wchusbserial10 115200`).

Build:

```bash
cd firmware/show5-firmware
cargo build --release
```

First build is ~30 s. Subsequent rebuilds <10 s.

## Flash

```bash
cargo run --release
```

Or explicitly:

```bash
espflash flash \
    --port /dev/cu.wchusbserial10 \
    --no-stub \
    --chip esp32p4 \
    target/riscv32imafc-unknown-none-elf/release/show5-firmware
```

Notes specific to this board:

- **Use `--no-stub`.** The flash-stub bounce fails to connect through
  the CH343; direct bootloader works fine.
- **Manual download mode every flash.** Hold BOOT, tap RESET, release
  BOOT, then run espflash within ~5 s. The board's auto-reset wiring
  doesn't drop the chip into download mode reliably.
- **Tap RESET after flash** (no BOOT held) to boot the new firmware.

## Monitor

Until `jtag-serial` is wired up:

```bash
python3 -m serial.tools.miniterm /dev/cu.wchusbserial10 115200
```

(or `uv run --with pyserial python -m serial.tools.miniterm …`)

## Phase 0.5 OTA workflow (planned)

Once Phase 0.5 lands, the iteration loop becomes:

```bash
make ota DEVICE=kitchen   # build → SHA256 → upload to Gilbert → trigger
```

— and the new binary lands on the screen in <30 s without touching
the USB cable.

## File layout

```
Cargo.toml              esp-hal + esp-bootloader-esp-idf + esp-println + esp-backtrace
rust-toolchain.toml     pinned nightly for build-std
.cargo/config.toml      target=riscv32imafc-unknown-none-elf + espflash runner
partitions.csv          dual-OTA-slot layout (Phase 0.5)
src/main.rs             entry — currently bare heartbeat
```
