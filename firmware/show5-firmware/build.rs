// esp-hal ships memory-region linker scripts that pin where code,
// rodata, and stack go in HP SRAM. cargo doesn't auto-discover them;
// the build.rs has to tell the linker where to find them.
//
// Without this, ``-Tlinkall.x`` resolves to whatever stale script
// happens to be on the search path (usually nothing → the binary
// links with default sections that don't match the chip's memory
// layout → silent crash before main()).

fn main() {
    println!("cargo:rustc-link-arg=-Tlinkall.x");
}
