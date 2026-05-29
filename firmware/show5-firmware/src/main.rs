//! Show5 firmware — Phase 0 hello-world.
//!
//! This is the minimum that proves the toolchain works end-to-end: ESP-IDF
//! boots, logging comes out the UART, the main task loops. Once the board
//! arrives we'll add the screen bring-up (Phase 0 step 2), then the C6
//! hosted Wi-Fi bring-up (Phase 0 step 4), then the WebSocket client
//! (Phase 0 step 5 + Phase 1).
//!
//! Cross-reference: docs/plans/2026-05-29-show5-firmware.md

use esp_idf_svc::hal::delay::FreeRtos;
use esp_idf_svc::log::EspLogger;
use log::info;

fn main() -> anyhow::Result<()> {
    // ESP-IDF link-time hook. Without this, ROM patches don't apply and
    // newlib symbols aren't pulled in — every esp-idf-svc binary calls it.
    esp_idf_svc::sys::link_patches();
    EspLogger::initialize_default();

    info!("show5-firmware {} booting", env!("CARGO_PKG_VERSION"));
    info!("target: ESP32-P4 (riscv32imafc-unknown-none-elf)");

    // Heartbeat. Replaced by the WebSocket loop once Phase 1 starts.
    let mut tick: u32 = 0;
    loop {
        FreeRtos::delay_ms(1000);
        tick = tick.wrapping_add(1);
        if tick % 10 == 0 {
            info!("alive — uptime ~{}s", tick);
        }
    }
}
