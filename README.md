# Mi Note 10 Lite (toco): Android that would not boot, repaired without a factory reset

[فارسی](README.fa.md)

On 19 October 2026 a Xiaomi Mi Note 10 Lite (`toco`, Snapdragon 730G) running PixelOS 16 (Android 16) stopped booting and did not recover:
stuck on the Xiaomi logo, restarting into the bootloader, and a custom recovery that froze or showed a black screen in about half of its
boots. Reinstalling the ROM twice changed nothing. After several days of log analysis the cause was found, and one parameter on the kernel
command line made Android boot again with all data intact. No factory reset, no hardware repair.

This repository is the record: what was seen, what was tried (including the wrong turns), the evidence, the cause, the exact steps of the fix
and how to undo it. It is one case on one phone; read "Limits" before you copy anything.

## In short

* **What was wrong.** The phone's I2C bus 3 stopped answering at about the time Android stopped booting, 19 October (a hardware fault;
  the vibration-motor driver chip DRV2604 at address 0x5a and the LED-driver chip AW3644 at 0x63 sit on that bus). When its chip
  does not answer, the kernel's vendor haptics driver (`drv260x`) goes wrong in its error path: it frees device-managed memory by hand
  (KASAN: `double-free or invalid-free`) although the driver core frees it too, and it leaves a queued firmware load behind, which later
  writes the vibration firmware into the freed memory. Every boot therefore corrupts a random piece of kernel memory, and whichever
  program allocates memory next dies: `apexd`, `ueventd`, `init`, the recovery. From the outside that looks like a bad install, bad RAM
  or storage, a broken ROM: anything but a vibration driver.
* **The fix.** Tell the kernel not to start that driver: add `initcall_blacklist=drv260x_driver_init` to the kernel command line of the
  `boot` image. Kernel, ramdisk and device tree stay byte-identical; only that one parameter is added.
* **The price.** Vibration does not work (it did not before either). The phone's flash works (the owner's report): the device tree puts the
  flash and the torch on the power-management chip, not on the dead bus ([evidence](evidence/07-flash-is-on-the-pmic-not-on-the-bus.txt)). The AW3644 LED driver on the dead bus
  fails to start, as before; the parameter does not touch it. After a hardware repair, flash the original boot image back to get
  vibration again.
* **Evidence that it works.** On the one phone this was found on, Android started to the lock screen on the first try with every file
  intact (`fastboot boot`), and it kept starting after the image was flashed permanently.

## Do you have the same problem?

Do not flash anything because of symptoms alone. Read the kernel log first (from a recovery with adb, or from Android: `adb shell dmesg`).
The pattern on this phone, in every saved boot log:

```
drv260x_input(as input_haptics): drv260x probe, i2c address= 5a
i2c_geni 890000.i2c: Bus arbitration lost, clock line undriveable
i2c_geni 890000.i2c: Bus proto err, noisy/unepxected start/stop
drv260x-haptics 3-005a: Failed to read  register[0x01]: -71
drv260x-haptics: probe of 3-005a failed with error -71
```

and then, at a random moment, an oops whose "virtual address" is not a kernel address (a free object's first bytes overwritten by data):

```
Unable to handle kernel paging request at virtual address eeb0c2a703fb4d93
pc : __kmalloc_track_caller+0xac/0x2e0
```

Other signs: `bootloader,bootstrap-apexd-failed` as the last boot reason in `/metadata/bootstat/persist.sys.boot.reason`; `init: Exec service
failed, status 25: Rebooting into recovery, reason: init_user0_failed`; a recovery that works one time in two. The kernel console of a
crashed boot survives only after a *warm* reset: see [docs/en/5-method.md](docs/en/5-method.md). A different phone with a different driver
can show the same family of symptoms; the method in that file is meant for that case.

## The fix in short

Full instructions, safety rules and the undo are in [docs/en/4-fix.md](docs/en/4-fix.md). The core is:

```sh
python3 tools/add_cmdline.py boot-original.img boot-fixed.img "initcall_blacklist=drv260x_driver_init" --mkbootimg PATH/TO/mkbootimg
fastboot boot boot-fixed.img          # writes nothing; if Android starts, the fix works
fastboot flash boot boot-fixed.img    # only then: make it permanent
fastboot reboot
fastboot flash boot boot-original.img # undo (after a hardware repair, or if you change your mind)
```

## What is in here

| Path | What |
|---|---|
| [docs/en/1-story.md](docs/en/1-story.md) | What happened, day by day, with the dead ends and what ruled each one out |
| [docs/en/2-evidence.md](docs/en/2-evidence.md) | The proof, annotated; the raw excerpts are in [evidence/](evidence/) |
| [docs/en/3-root-cause.md](docs/en/3-root-cause.md) | The mechanism, what is certain and what is not, what to tell a repair shop |
| [docs/en/4-fix.md](docs/en/4-fix.md) | The fix step by step, the undo, ROM updates |
| [docs/en/5-method.md](docs/en/5-method.md) | How it was found, lessons, a checklist, FAQ |
| `docs/fa/` | The same five documents in Persian |
| [evidence/](evidence/) | Kernel console excerpts of the real boots (KASAN reports, the dead bus, the Android boot that died) |
| [tools/](tools/) | `add_cmdline.py`, which makes the modified boot image and proves that nothing else changed |

## Limits

* **One phone.** The fix was verified on one unit: unlocked bootloader, PixelOS 16.2 build 20260609_1626 (kernel 4.14.356). Whether another
  unit has the same dead bus is for its kernel log to say.
* **The exact hardware fault is not known.** The logs say the clock line of I2C bus 3 cannot be driven. Which part holds it (the chip, its
  flex or the motor module, a short, moisture damage) can only be found by a technician.
* **The exact source line of the bad `kfree()` was not read.** The kernel's public repository has the plain TI driver at the commit that was
  checked, while the built-in driver is a Xiaomi variant (`HapticsFirmwareLoad`). KASAN named the place (`drv260x_probe+0x724`); the code
  was not seen.
* The modified image has no AVB footer. It needs an unlocked bootloader.
* A ROM update replaces `boot` and brings the problem back until the parameter is applied to the new boot image.
* Use at your own risk. Flashing a wrong image to `boot` can leave a phone unable to start; keep the original image and a copy of your data.

## Related

The custom OrangeFox recovery that was built to copy the data off the phone, and whose crashes produced most of the evidence, is in
[hesinj/orangefox-toco](https://github.com/hesinj/orangefox-toco) (its `docs/TROUBLESHOOTING.md` is the long, chronological version of
this story, written while the cause was still unknown).

## Credits

The phone's owner ran every test and collected every log. The analysis and the writing were done with Claude (an AI assistant) in one
interactive session over five days. Claims about this phone rest on log excerpts and command outputs from that session; what is
inferred is said to be inferred, and what is not known is listed as such.
