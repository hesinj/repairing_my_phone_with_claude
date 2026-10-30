# The root cause

## The chain

```
 hardware fault (not repaired)               software bug in the vendor driver (not fixed, only switched off)
 ──────────────────────────────              ─────────────────────────────────────────────────────────────────
 clock line of I2C bus 3 cannot be     +     the probe of the haptics driver fails -> its error path kfree()s memory
 driven; the chips on it (haptics 0x5a,      that came from devm_kmalloc() (which the driver core frees too: double /
 LED driver 0x63) do not answer              invalid free) and a queued firmware load later writes into that memory

                                       =     random kernel memory is overwritten in every boot, from the first seconds
                                             on, by the bytes of /vendor/firmware/drv2604.bin
```

Neither half alone does harm: with a working bus the probe succeeds and nothing is freed wrongly; a driver with a correct error path would
just print an error. Together they turned a dead vibration motor into a phone that would not boot.

## How the driver goes wrong, step by step

1. `drv260x_probe` allocates its state with `devm_kmalloc()` (512 bytes, `kmalloc-512`, at `drv260x_probe+0x54`). `devm_` memory belongs
   to the device: the driver core frees it by itself when the probe fails or the driver is removed.
2. The probe reads register 0x01 over I2C. The bus does not answer (`Bus arbitration lost, clock line undriveable`), the read fails with
   `-71` (EPROTO), `Device init failed: -71`.
3. The error path calls `kfree()` on the pointer it got from `devm_kmalloc()` (`drv260x_probe+0x724`). That pointer is not the start of the
   slab object: `devm_` memory sits behind a header, and on arm64 the data starts 128 bytes into the object (KASAN: "located 128 bytes
   inside of 512-byte region"). KASAN: `double-free or invalid-free`, and it refuses the free. A kernel without KASAN would put that
   interior pointer on the free list as an object of its own, overlapping its neighbour (inferred from the allocator's code, not observed).
4. The probe returns the error, and the driver core releases the device's resources (`release_nodes` -> `kfree` of the real object): the
   memory is now free, and the driver still holds pointers into it.
5. Before failing, the probe had queued a firmware load with `request_firmware_nowait()`. The callback (`HapticsFirmwareLoad`) is still
   queued. When `ueventd` serves `drv2604.bin` (about 6 seconds later in the debug boot, 2.7 s in a normal boot), the callback copies the
   firmware into the object that has been freed. KASAN: `use-after-free ... Write of size 20`.
6. The allocator has long since handed that memory to someone else. Whatever lives there now (a free object's free-list pointer, a mutex,
   a work queue, a socket buffer) is overwritten. The next allocation from that cache, or the next use of the structure, faults.

## Why it looked like everything but a driver

| What was seen | Why |
|---|---|
| `apexd`, `ueventd`, `init`, `recovery`, `tee` crashing, never the same one | They were the next to allocate from the poisoned cache; nothing about them is wrong. |
| Crashes at 1.1 s, 2.7 s, 5.7 s, 24 s, or none | The damage comes in two steps: the bad free at probe time (0.6-8.3 s; the early crashes at 1.1 s are before any firmware is served, so this step is inferred to be harmful by itself) and the firmware write when `ueventd` serves the file. Which object is hit decides when and where it crashes. |
| "Works one time in two" | Sometimes the overwritten memory is not used again, or is harmless. |
| A reinstall of the ROM changed nothing | The system was never the problem; the reinstall wrote correct data over correct data. |
| The ROM's recovery fine, the custom one not | The ROM's recovery allocates little and finishes in 4 s; the corrupted object is harmless until somebody allocates it. It saw the same failed probe in its logs. |
| `bootstrap-apexd-failed`, `init_user0_failed` | `apexd` or `ueventd` was the victim; init's rules for their failure reboot the phone. |
| No pattern with USB, heat, decryption, RAM, frequencies | None of them is involved. |

## Why a factory reset, a reinstall or the official ROM would not have helped

* A factory reset rewrites `/data` (and `/metadata`). The corruption happens in kernel memory, before `/data` is mounted; boots of a
  recovery that mounts no `/data` failed the same way.
* The ROM was reinstalled twice (system, vendor, product, odm, system_ext, dtbo, vbmeta) and then verified bit-identical to the zip. The
  kernel that is built into `boot` is the same either way.
* Another ROM would carry its own copy of this vendor driver. In the MIUI days the same `drv260x_input` driver was running, which only
  says that it works while the chip answers. And the stock MIUI cannot open Android 16's encrypted data, so switching would have cost
  the data for nothing.
* The kernel parameter removes the driver; that is the only change of the repair.

## What is certain, what is not

Certain (read from logs of the phone, or shown by the repair):

* the I2C errors precede the first crash in every saved console;
* KASAN names the bad free in `drv260x_probe` (a `kfree()` of a `devm_kmalloc()` pointer) and the use-after-free write in
  `HapticsFirmwareLoad`, both on the same 512-byte object;
* without the driver, Android starts, with the data intact.

Not known:

* **Which hardware part is at fault.** Only that the clock line of bus 3 cannot be driven. A chip, its flex, the motor module, a short,
  moisture or a damaged connector would all give the same log.
* **The source line of the bad `kfree()`** (the built-in driver is a Xiaomi variant that was not read).
* Whether the bus recovers by itself. In the logs it stayed dead in every boot after it died.
* Whether the phone had a drop or got wet before 19 October. It was asked, and the answer is not recorded.

## For a repair shop

What to say: "I2C bus 3 of this Snapdragon 730G board (kernel name `890000.i2c`, 400 kHz) does not answer. On it, at address 0x5a, is the
vibration-motor driver (DRV2604) and, at 0x63, an LED driver (AW3644, a flash/IR LED driver chip). The kernel log says `Bus arbitration lost, clock line
undriveable`, so the clock line is held down or shorted, or noisy."

Suggestions that were **not** tried here (nobody has opened this phone):

* Disconnect the vibration-motor module and its flex, and the camera/flash flex, one at a time; start a recovery and read
  `adb shell dmesg | grep 890000.i2c`. If the errors stop, the part that was disconnected is the one that holds the line.
* Look for moisture or corrosion, burn marks or a bent connector near those flexes.
* With the phone off, check the clock and data lines of the bus against ground for a short. The board schematic names the test points.

After a repair, flash the original boot image back ([4-fix.md](4-fix.md)): the driver then loads again and vibration works.

## What the parameter does

`initcall_blacklist=drv260x_driver_init` makes the kernel skip the initcall whose function is called `drv260x_driver_init`. The driver
is built into the kernel, and `module_i2c_driver(drv260x_driver)` generates exactly that init function, which registers the I2C driver.
Skipped, the driver never registers, so there is no probe, no bad free and no queued firmware load. The kernel prints nothing about
the skipped call (the message is a `pr_debug`). A parameter whose name matches nothing is ignored silently, so after a kernel update
the symbol has to be checked again.
