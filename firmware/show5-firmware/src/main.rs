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
use esp_hal::delay::Delay;
use esp_hal::gpio::{Level, Output, OutputConfig};
use esp_hal::time::Duration;
use esp_println::println;

// Embed the ESP-IDF-compatible app descriptor at the start of the
// image. The boot ROM checks this header before jumping to our entry
// point; without it espflash refuses to flash and the chip wouldn't
// boot the image anyway.
esp_bootloader_esp_idf::esp_app_desc!();

// GPIO sweep for the onboard LED. Different IoTeikXgo board revisions
// wire a status LED to different pins; without a schematic we toggle
// a few likely candidates each cycle. Whichever one is the real LED
// will blink at ~1 Hz; the rest get harmlessly poked.
const LED_CANDIDATES: &[u8] = &[15, 22, 48, 23, 21, 38, 11];

#[esp_hal::main]
fn main() -> ! {
    // Initialize the chip + peripherals with esp-hal's defaults.
    let peripherals = esp_hal::init(esp_hal::Config::default());

    esp_alloc::heap_allocator!(size: 8 * 1024);

    println!(
        "show5-firmware {} booting on esp-hal",
        env!("CARGO_PKG_VERSION")
    );
    println!("target: ESP32-P4 (riscv32imafc-unknown-none-elf, no_std)");

    // Set up an LED-blink fallback: even with no console, a blinking
    // GPIO proves the chip is running our code. Drive ALL candidate
    // pins; the one that's wired to the LED will respond.
    let cfg = OutputConfig::default();
    let mut leds = [
        Output::new(peripherals.GPIO15, Level::Low, cfg),
        Output::new(peripherals.GPIO22, Level::Low, cfg),
        Output::new(peripherals.GPIO48, Level::Low, cfg),
        Output::new(peripherals.GPIO23, Level::Low, cfg),
        Output::new(peripherals.GPIO21, Level::Low, cfg),
        Output::new(peripherals.GPIO38, Level::Low, cfg),
        Output::new(peripherals.GPIO11, Level::Low, cfg),
    ];

    println!(
        "LED sweep — toggling GPIOs {:?} every 500ms",
        LED_CANDIDATES
    );

    let delay = Delay::new();
    let mut tick: u32 = 0;
    let mut on = false;
    loop {
        on = !on;
        let level = if on { Level::High } else { Level::Low };
        for led in leds.iter_mut() {
            led.set_level(level);
        }
        delay.delay(Duration::from_millis(500));
        tick = tick.wrapping_add(1);
        if tick % 4 == 0 {
            // Every ~2 s.
            println!("alive — tick {}", tick);
        }
    }
}
