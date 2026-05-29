// embuild bootstraps ESP-IDF + LLVM toolchains, generates linker scripts,
// and emits ``cargo:rustc-link-search`` for the IDF static libs. The
// ESP_IDF_VERSION env var (set in ``.cargo/config.toml``) controls which
// IDF tag is pulled.

fn main() -> Result<(), Box<dyn std::error::Error>> {
    embuild::espidf::sysenv::output();
    Ok(())
}
