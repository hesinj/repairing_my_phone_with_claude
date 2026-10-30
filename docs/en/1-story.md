# What happened, in order

Times are Iran time (UTC+3:30) unless noted. Dates are 2026.

## The phone

* Xiaomi Mi Note 10 Lite (`toco`), Snapdragon 730G (SM6150), 8 GB RAM, UFS (SK hynix H9HQ16AFAMMDAR), bootloader unlocked, no root.
* ROM: PixelOS 16.2 (Android 16), build 20260609_1626, on the MIUI V13.0.4.0.SFNMIXM vendor firmware. Kernel 4.14.356 (PixelOS's release
  kernel). Android had run this same kernel since 31 May.
* User data: file-based encryption (fscrypt v2) with metadata encryption and hardware-wrapped keys. A recovery that cannot unwrap the key
  sees an empty or scrambled internal storage.

## What the phone did

* **Android.** On the night of 18 October the phone was switched off after normal use (web browsing, YouTube, Instagram), at about 23:14.
  On the morning of 19 October it stayed on the Xiaomi logo, and it never booted again before the fix. Most attempts hung on the logo. One
  attempt (25 October, about 11:03) reached `init`, and `apexd --bootstrap` failed; init rebooted into the bootloader and recorded
  `bootloader,bootstrap-apexd-failed`. During one diagnostic boot the logo disappeared after a few seconds and came back.
* **The ROM's own recovery** started every time, according to the owner (it was never counted in a series).
* **The custom recovery that was built to copy the data off** (OrangeFox, see the related repository) started about one time in two. The
  rest was a logo that never went away, a black screen, or a restart into the installed system. After a boot that did come up it ran for
  hours (one session: 16.9 hours) without any trouble.

## Timeline

| Date | What was done | What it showed |
|---|---|---|
| 19 Oct | PixelOS 16.2 sideloaded twice (the same 2.88 GB zip) | No change. (Read much later in the stock recovery's saved logs: the haptics chip goes from answering to not answering somewhere in the history of those sessions. Those logs have no usable dates, the recovery's clock read 1971. The camera's crash dumps, read on 30 October, date the dead bus: 2 October at the latest.) |
| 23-24 Oct | Built a custom OrangeFox recovery that can decrypt PixelOS's `/data`, to copy the files off | First boots: stuck on the logo, black screens, restarts into the installed system. The first reading was "the decryption chain hangs" (wrong, see below). |
| 24-25 Oct | Kernel log (`pstore`) of a frozen boot | The "freezes" are kernel panics: a free-list pointer of a freed kernel object overwritten by garbage, found by the next allocation. Heap corruption, anywhere from 1.1 s to 24 s after the kernel starts. |
| 25 Oct | Recovery build `r8` came up, decrypted `/data`, and `adb pull` copied the internal storage | **The data was safe on a PC before any repair was tried.** From here on the goal was repair without a factory reset. |
| 25-26 Oct | Read-only diagnosis of the installed Android from the recovery (bundles of 25 and 26 Oct) | Partitions `boot`, `dtbo`, `recovery` identical to the official release; all 8,338 files of the system readable; 36 APEX packages intact; every partition except `userdata` readable raw; `e2fsck` clean on `persist`, `cust`, `/metadata`; the five logical partitions bit-identical to the ROM zip. Nothing wrong with the stored system. |
| 26 Oct | RAM stress test from the recovery (8 CPUs, 480 s, 1.9 TiB verified), then two longer runs | 0 errors. RAM cells fine. |
| 26 Oct | Probe images: the ROM's own boot image with one kernel parameter each (`nr_cpus=6`, `loglevel=0`, `cpufreq.off=1`), started with `fastboot boot` | None reached the lock screen. Two ended in a restart by the phone itself. |
| 26 Oct | The custom recovery without the decryption stack, eight boots in a row | ok, ok, black, black, black, ok, black, doubtful: as bad as the full one. So not the decryption chain. |
| 27 Oct | Saving the kernel console of failing boots: the console survives a restart only when the restart is warm, so a boot image with `qcom,force-warm-reboot` was used | The console of a normal Android boot, read for the first time: `apexd` killed by an oops inside its own `dm_create` call at 2.78 s, preceded at 2.69 s by an oops in the firmware callback of a *haptics driver*. Every saved console starts with the same failed haptics probe. |
| 27 Oct | Debug kernel (KASAN + SLUB debugging) booted instead | The first two KASAN reports of the whole case: a `double-free or invalid-free` inside `drv260x_probe`, then a use-after-free write from `HapticsFirmwareLoad` into the same object. The probe fails because the I2C bus does not answer. |
| 27 Oct, afternoon | `fastboot boot` of the ROM's boot image with `initcall_blacklist=drv260x_driver_init` (after clearing the bootloader message, see [4-fix.md](4-fix.md)) | **Android started to the lock screen, data intact.** |
| 27 Oct, later that afternoon | The same image flashed to `boot` | Still starts. Confirmed by the owner. |
| 30 Oct | Android bugreports, taken because the camera app did not work | The rear camera dies on a write to the soft-flash chip on the dead bus, and the camera software then crashes in its error path. The crash dumps put the first such crash on 2 October. The front, macro and ultra-wide cameras are not found. ([6-camera.md](6-camera.md)) |
| 30 Oct | `fastboot boot` of a kernel in which the soft flash is hidden | Does not help: the camera software needs the chip and aborts. |
| 30 Oct | `fastboot boot` of a kernel in which the failed write counts as a success | **The main camera works.** The soft flash stays dead; the other three cameras are still missing. |

## Dead ends, and what ruled each one out

Wrong turns are part of the record because each of them looked reasonable at the time.

| Idea | Why it looked right | What ruled it out |
|---|---|---|
| The recovery hangs in the decryption chain (`qseecomd`, Keymaster, `keystore2`) | The first log ended right after "Device ready for decryption" | The recovery without any decryption stack failed about as often (4-5 of 8 boots), and one of the panics happened at 1.1 s, before user space. |
| MTP / USB gadget switching | The failures seemed to happen when the PC enumerated the phone | A panic at 2.67 s, before USB exists; Android failed with no cable at all. |
| A miscompiled kernel | The recovery's own kernel build failed | PixelOS's release kernel, byte for byte, failed too. |
| Heat | It "works one time, not the other" | The very first failure came after the phone had been off all night, and the cause found has nothing to do with temperature. |
| Bad RAM or CPU | Heap corruption looks like it | Stress test: 0 errors in 1.9 TiB verified; the corruption pattern (30 bits of a pointer replaced by high-entropy data, only free objects) is not a bit flip. |
| Damaged system files, a failed install | A phone that stops booting overnight, and a reinstall that seemed to change nothing, suggest broken files | Every system file readable; the five logical partitions bit-identical to the ROM zip; the reinstalls changed nothing because there was nothing to repair. |
| CPU frequency steps, USB, a slow serial console | Deaths seemed to cluster 11.5-14.2 s after the kernel start | Probe images without big cores, without console output and without frequency changes all still failed. (The cluster was partly an artefact of when the recorder wrote and which boots it could see.) |
| "The ROM's own recovery always boots, so the phone is fine" | The owner was sure it came up every time | It allocates little and does little in the first seconds: a corrupted free object is harmless until somebody allocates it. It runs the same kernel and device tree, and its saved logs show the failed haptics probe too. |
| A kernel crash caught by the firmware (the `minidump` partition) | A dump existed | It was from the MIUI days: kernel 4.14.190, a different bug in a driver that PixelOS's kernel does not have. Check the version inside a dump before drawing conclusions. |

## What finally worked

Instead of asking who crashed, the question became who wrote into the freed memory, and for that a console of a failing boot was needed:

1. A software restart on this phone is a *hard* reset that empties the RAM, and the kernel console with it. The device tree gets one more
   property (`qcom,force-warm-reboot` in the `qcom,pshold` node) so that every restart is warm and the console survives.
2. The console of an Android boot showed, before the first oops, the same three lines every time: the haptics probe, the I2C bus error and
   the failed probe. A debug kernel then named the bad free and the use-after-free.
3. A kernel parameter removed the driver from the boot, and Android came up.

Details: [2-evidence.md](2-evidence.md), [3-root-cause.md](3-root-cause.md), [4-fix.md](4-fix.md), [5-method.md](5-method.md).
