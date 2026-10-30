# The evidence

Every excerpt is from the kernel console of a real boot of the phone (kernel 4.14.356, board `SDMMAGPIE PM6150 TOCO`). A crashed boot's
console is kept in RAM by the kernel (`pstore`/`ramoops`) and the recovery that was started next copied it to a file
(`/cache/toco-bb/pstore-before-boot-N.txt`). The raw excerpts are in [../../evidence/](../../evidence/); only lines that are not needed
were left out, and the files say where.

## 1. The symptom: something writes into freed kernel memory

[evidence/06](../../evidence/06-recovery-oops-same-signature.txt), from the custom recovery at 6.6 s:

```
Unable to handle kernel paging request at virtual address eeb0c2a703fb4d93
[eeb0c2a703fb4d93] address between user and kernel address ranges
Process recovery (pid: 515 ...)       pc : __kmalloc_track_caller+0xac/0x2e0
x9 : eeb0c2a703fb4d93 x8 : eeb0c2a703fb4d93
```

The kernel allocator (SLUB) takes the next free object of a cache and reads the pointer to the one after it from the object's first eight
bytes. Here those eight bytes held `eeb0c2a703fb4d93`, which no kernel address can look like. With the cache's hardened free-list key
decoded, the stored word still has a non-pointer, non-zero high half: the bytes were **overwritten with high-entropy data by something
that is not the allocator**. It is not a flipped bit (about 30 bits differ), and a program that crashes there is only the next one to
allocate, not the culprit.

The same signature was read back from eight other consoles: at 24.2 s, 2.67 s, 1.13 s and 5.66 s in the earlier recovery builds, at 2.1 s
(and again at 2.8 s), 2.8 s and 4.0 s in the next build, and at 2.69 s (and again at 2.78 s) in **Android itself**. Three of them were in
`init` (pid 1) before any user-space program existed, and the build without a decryption stack, which mounts no `/data`, failed as well. So
the writer is not the decryption stack, not MTP or USB (one panic came at 2.67 s, before either exists), not a user-space program and not
anything on the user's data partition. That is why a factory reset, which only rewrites `/data`, could not be expected to help.

## 2. The same three lines before the first crash, in every console

[evidence/01](../../evidence/01-dead-i2c-bus-and-failed-probes.txt):

```
drv260x_input(as input_haptics): drv260x probe, i2c address= 5a
i2c_geni 890000.i2c: Bus arbitration lost, clock line undriveable
i2c_geni 890000.i2c: Bus proto err, noisy/unepxected start/stop
drv260x-haptics 3-005a: Failed to read  register[0x01]: -71
drv260x-haptics 3-005a: Device init failed: -71
drv260x-haptics: probe of 3-005a failed with error -71
```

This is in **all seven** saved consoles that were looked at (custom recovery builds, a normal Android boot with the installed, unmodified
boot image, and the debug-kernel Android boot), always before the first oops, between 0.6 s and 8.3 s depending on the boot. On the same bus the AWINIC LED driver
(`leds-aw3644`, address 0x63; the AW3644 is a flash/IR LED driver chip) fails too (`leds-aw3644 3-0063: Failed to read REG_DEVICE_ID register`, `probe ... failed with error -71`), but that
driver fails politely.

`Bus arbitration lost, clock line undriveable` is the I2C controller (Qualcomm GENI, `890000.i2c`, 400 kHz) saying that it tried to drive
the clock line and the line did not follow: something holds it. That is a hardware condition, not a software one.

**The phone's flash is not on this bus.** An earlier version of this page took the AW3644 for "the camera flash LED" and said that the flash
was dead too. That was an inference from the chip's name, not an observation, and it was wrong: the owner reports that the phone's flash works.
The phone's device tree explains why ([evidence/07](../../evidence/07-flash-is-on-the-pmic-not-on-the-bus.txt)): the three rear flash nodes (`led_flash_rear`,
`led_flash_rear_macro`, `led_flash_rear_ultra`) take their flash and torch LEDs from the flash module of the PM6150L power-management chip
(`qcom,qpnp-flash-led-v2`, on the SPMI bus, not on I2C), whereas the AW3644 and the camera's `i2c_flash` devices sit on `890000.i2c` and
appear only as an extra "soft" flash source (`soft-led-flash-src`) of the three rear camera sensors. What that extra LED does for the
camera, and whether it works, was not checked.

## 3. The writer, named by a debug kernel

The kernel of the ROM was replaced, for one boot started with `fastboot boot`, by a build with KASAN (a memory error detector) and SLUB
debugging. It produced the first two KASAN reports of the whole case.

**The bad free** (`double-free or invalid-free`), [evidence/02](../../evidence/02-kasan-double-free-in-drv260x-probe.txt), at 8.33 s, right after the lines above:

```
BUG: KASAN: double-free or invalid-free in drv260x_probe+0x724/0xaf0        (abridged)
  kfree+0x100/0x7fc
  drv260x_probe+0x724/0xaf0
Allocated by task 251:
  devm_kmalloc+0x24/0x88
  drv260x_probe+0x54/0xaf0
The buggy address belongs to the object ... which belongs to the cache kmalloc-512 of size 512
```

The driver allocated a 512-byte object with `devm_kmalloc()` (memory that the driver core frees by itself when the probe fails) and its
error path then calls `kfree()` on the pointer it got. KASAN cannot tell a double free from an invalid free, and the report has a clue:
the pointer is **128 bytes inside** the 512-byte object (`devm_` memory sits behind a header, and on arm64 the data starts 128 bytes into
the object). So the driver frees a pointer that is not the start of the allocation, and the driver core frees the real object when the
probe fails. KASAN refuses the first free. A kernel without KASAN does not refuse it: SLUB takes the pointer for an object of its own and
puts it on the free list, where it overlaps its neighbour. That last step is read from the code of the allocator, not observed.

**Use after free**, [evidence/03](../../evidence/03-kasan-use-after-free-in-haptics-firmware-load.txt), at 14.2 s:

```
ueventd: loading /devices/platform/soc/890000.i2c/i2c-3/3-005a/firmware/drv2604.bin took 3ms        (abridged)
BUG: KASAN: use-after-free in HapticsFirmwareLoad+0x5c/0x528
Write of size 20 at addr ffffffc1a85a2a18 by task kworker/3:1/180
Workqueue: events request_firmware_work_func
Allocated by task 251:  devm_kmalloc <- drv260x_probe+0x54
Freed by task 251:      kfree <- release_nodes <- devres_release_all <- driver_probe_device
```

The failed probe had queued a `request_firmware_nowait()` callback (`HapticsFirmwareLoad`). When `ueventd` serves
`/vendor/firmware/drv2604.bin`, six seconds later, the callback **copies the vibration firmware into the object that was freed at
8.33 s**. By then the allocator has long handed that memory to somebody else, so a random kernel structure is overwritten with
firmware bytes. That explains what the earlier consoles showed:

* the victim cache is almost always `kmalloc-512` (the haptics object is 512 bytes);
* the data written is high-entropy, and it repeats: the bytes `247d14df30` appear in two different oopses of the same boot
  ([evidence/04](../../evidence/04-android-boot-killed-by-heap-corruption.txt): `f38d247d14df30b8` and `7397247d14df30c7`);
* it hits free-list pointers and **live** structures alike (in that boot a live regmap mutex of the haptics driver itself);
* it starts before user space (the probe runs in the kernel's own initcalls, 0.6-8.3 s into the boot);
* it does not care about the ramdisk, `/data`, USB or the decryption stack.

## 4. What the corruption did to Android

[evidence/04](../../evidence/04-android-boot-killed-by-heap-corruption.txt), a normal boot (no debug kernel, the installed boot image): at
2.552 s `init` starts `apexd --bootstrap`; at 2.688 s the kworker that runs the firmware callback faults inside `regmap_write`, at 2.784 s
`apexd` faults in the allocator (`__kmalloc` called from `__alloc_workqueue_key` called from `dm_create`). `init`'s rule for a failed
`apexd --bootstrap` is to reboot into the bootloader, which matches the reason `bootstrap-apexd-failed` that `/metadata/bootstat` had
recorded on 25 October.

[evidence/05](../../evidence/05-ueventd-killed-and-init-reboots-into-recovery.txt), the debug-kernel boot: its poisoning absorbed the damage at
the `apexd` stage, but at 15.6 s `ueventd` was hit (`BUG kmalloc-256: Invalid object pointer`, then `received SIGSEGV`), `vold` waited for
device links that `ueventd` should have made, `vdc cryptfs init_user0` failed and `init` rebooted into the *recovery partition* with
`reason: init_user0_failed`. On such a reboot Android writes a message for the bootloader into the `misc` partition
(`--prompt_and_wipe_data --reason=init_user0_failed`). A phone with that message keeps starting its recovery, and a stock recovery then
offers "Factory data reset". On the reference phone `misc` was empty when it was read, probably because the custom recovery that started next
ignores such a request and clears it (as TWRP-based recoveries do): see [4-fix.md](4-fix.md).

## 5. When the bus died

The stock (ROM) recovery keeps its kernel logs of past sessions. In the oldest sessions the haptics probe succeeds
(`Get drv260x status reg[0x01]=0x40`); from one session on, every session shows the I2C error. The recovery's clock read 1971, so
those sessions cannot be dated. The five stock sessions after the change survived with the bug in them: that recovery allocates little,
and only a boot that survives writes a log. (An old crash dump in the `minidump` partition shows the same `drv260x_input` driver working
in the MIUI days.) These logs are not in this repository.

What does date the bus is the camera ([6-camera.md](6-camera.md)). The phone keeps the crash dumps of the camera software, and the
first crash with the signature of a failed write to the chip on this bus is from **2 October**
([evidence/08](../../evidence/08-rear-camera-dies-on-the-soft-flash-write.txt), part C). So the bus was dead on 2 October at the latest (if that crash had the cause shown for 30 October, which the dumps alone
do not prove), 17 days before Android stopped booting. An earlier version of this section said "at about the time Android stopped booting"; that was an
inference from the order of the recovery sessions and it was wrong. Why the boot trouble started 17 days later is not shown. One
possibility: the faulty driver runs only at boot, so a phone that is not restarted for weeks shows nothing until its first restart after
the bus died.

## 6. The test that closed the case

`initcall_blacklist=drv260x_driver_init` on the kernel command line stops that one driver from ever starting: no probe, no bad free,
no queued firmware load. With it, `fastboot boot` of the ROM's own boot image started Android to the lock screen with the data intact, and
the same image flashed to `boot` kept starting. A fix that removes the symptom by removing exactly the faulty component is stronger than
any single log line, and that is the reason the cause chain is called confirmed here.

## 7. The camera (30 October)

The same bus kills the rear camera: every open of a rear camera writes to the soft-flash chip on it, the write fails and the closed
camera HAL crashes in its error path ([evidence/08](../../evidence/08-rear-camera-dies-on-the-soft-flash-write.txt)). A kernel change that reports that failed write as a success
brings the main camera back ([evidence/09](../../evidence/09-two-kernel-experiments-on-the-soft-flash.txt)). The front, macro and ultra-wide cameras are not found by the camera
software ([evidence/10](../../evidence/10-cameras-that-are-not-found.txt)). Details, the tool and the limits are in [6-camera.md](6-camera.md).

## What the evidence does not show

* **Which hardware part is broken.** The log shows an undriveable clock line on bus 3, not whether the cause is the chip, its flex or the
  motor module, a short, or moisture damage.
* **The source line of the bad `kfree()`.** The public kernel repository has the plain TI `drv260x` driver at the commit that was checked,
  while the built-in driver is a Xiaomi variant (`HapticsFirmwareLoad`, `android_haptics_play`). KASAN gave the offset
  (`drv260x_probe+0x724`); the code was not seen.
* **Whether the rear cameras and the extra "soft" flash LED work.** The phone's flash works (the owner's report). The camera sensors are on
  the camera control interface, not on bus 3, but the three rear ones list devices of bus 3 as a soft flash (evidence/07); whether a rear camera
  opens with the bus dead was not tested.
* **Why the front, macro and ultra-wide cameras are not found.** The logs show three modules that do not answer and that the camera
  software never knew (macro, ultra-wide) or no longer finds (front). Whether that is hardware or the ROM's camera configuration is open.
* **That every phone with this symptom has this cause.** One phone, one dead bus.
