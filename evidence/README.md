# Evidence

Kernel console excerpts of real boots of the phone (kernel 4.14.356, board `SDMMAGPIE PM6150 TOCO`) and, in file 07, excerpts of its device tree. Each file starts with `##` lines that
say what it is and what to look at; below them the log lines are exactly as the kernel printed them, except where a `## [...]` line says
that lines were left out.

| File | What it shows |
|---|---|
| [01-dead-i2c-bus-and-failed-probes.txt](01-dead-i2c-bus-and-failed-probes.txt) | The same failed haptics probe and I2C errors in a normal Android boot, in the custom recovery and in the debug-kernel boot; the AW3644 LED-driver chip fails too |
| [02-kasan-double-free-in-drv260x-probe.txt](02-kasan-double-free-in-drv260x-probe.txt) | KASAN: the probe's error path frees a `devm_kmalloc()` pointer (128 bytes inside the 512-byte object) |
| [03-kasan-use-after-free-in-haptics-firmware-load.txt](03-kasan-use-after-free-in-haptics-firmware-load.txt) | KASAN: the queued firmware load writes 20 bytes into the freed object |
| [04-android-boot-killed-by-heap-corruption.txt](04-android-boot-killed-by-heap-corruption.txt) | A normal Android boot: the firmware callback and then `apexd` fault on garbage pointers |
| [05-ueventd-killed-and-init-reboots-into-recovery.txt](05-ueventd-killed-and-init-reboots-into-recovery.txt) | The damage reaches `ueventd`; `init_user0` fails; `init` reboots into recovery |
| [06-recovery-oops-same-signature.txt](06-recovery-oops-same-signature.txt) | The custom recovery dies of the same corruption (a free object's first bytes overwritten) |
| [07-flash-is-on-the-pmic-not-on-the-bus.txt](07-flash-is-on-the-pmic-not-on-the-bus.txt) | Device tree: the phone's flash and torch are driven by the power-management chip, not by the dead I2C bus; what is on the bus; the camera drivers' log lines |
| [08-rear-camera-dies-on-the-soft-flash-write.txt](08-rear-camera-dies-on-the-soft-flash-write.txt) | The camera open that fails on the soft-flash write, the HAL crash after it, and the crash counts since 1 July |
| [09-two-kernel-experiments-on-the-soft-flash.txt](09-two-kernel-experiments-on-the-soft-flash.txt) | Hiding the soft flash makes the HAL abort; reporting its failed write as a success keeps the camera running |
| [10-cameras-that-are-not-found.txt](10-cameras-that-are-not-found.txt) | Front, macro and ultra-wide: probe and EEPROM errors, the camera service's three devices, the HAL's module record, the depth sensor's CSI errors |

Not included: the stock recovery's saved logs that show the haptics probe succeeding in older sessions, and the full logs (they hold
device identifiers). The explanation of each file is in [../docs/en/2-evidence.md](../docs/en/2-evidence.md).
