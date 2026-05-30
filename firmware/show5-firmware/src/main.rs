//! Show5 firmware — Phase 0 hello-world on esp-hal (no_std).
//!
//! After esp-idf-svc reproducibly panicked at boot on this chip's ROM
//! revision (see `docs/plans/2026-05-29-show5-firmware.md`), we
//! switched the firmware to esp-hal. This file is the bare minimum that
//! proves the chain works: peripherals init, println! to UART, busy
//! loop.
//!
//! Next steps after this boots cleanly:
//! 1. Replace the loop with embassy-executor + an embassy task.
//! 2. Bring up the screen (MIPI-DSI on this board) via
//!    `embedded-graphics` + a P4-specific driver.
//! 3. Phase 0.5 OTA — see plan doc.

#![no_std]
#![no_main]

extern crate alloc;

use esp_backtrace as _; // panic handler + backtrace dumper
use esp_println::println;

// Embed the ESP-IDF-compatible app descriptor at the start of the
// image. The boot ROM checks this header before jumping to our entry
// point; without it espflash refuses to flash and the chip wouldn't
// boot the image anyway.
esp_bootloader_esp_idf::esp_app_desc!();

#[esp_hal::main]
fn main() -> ! {
    // Initialize the chip + peripherals with esp-hal's defaults. This
    // sets up the clocks, the system controller, and the boot-time
    // configuration. Without this, peripheral access faults.
    let _peripherals = esp_hal::init(esp_hal::Config::default());

    // 8 KiB heap for early allocations (log formatting, etc.). Bumps
    // come later when libraries demand more.
    esp_alloc::heap_allocator!(size: 8 * 1024);

    println!(
        "show5-firmware {} booting on esp-hal",
        env!("CARGO_PKG_VERSION")
    );
    println!("target: ESP32-P4 (riscv32imafc-unknown-none-elf, no_std)");

    let mut tick: u32 = 0;
    loop {
        // ~1 Hz heartbeat. Crude busy-wait — replaced by an embassy
        // `Timer::after_millis(1000)` once we add the executor.
        for _ in 0..40_000_000 {
            core::hint::spin_loop();
        }
        tick = tick.wrapping_add(1);
        if tick % 10 == 0 {
            println!("alive — uptime ~{}s", tick);
        }
    }
}
