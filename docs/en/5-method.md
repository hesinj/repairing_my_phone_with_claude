# How it was found: method, lessons, checklist, FAQ

## What worked

1. **Look at the first failure, not at the victim.** The process that crashed was different every time (`tee`, `recovery`, `kworker`,
   `init`, `apexd`, `ueventd`). The three lines about the haptics probe were identical, and before the first crash, in every saved console.
2. **Recognise heap corruption and stop reading call traces.** A "virtual address" that is not a kernel address, in the allocator
   (`__kmalloc`, `kmem_cache_alloc_trace`), means that a free object's first bytes were overwritten. The call trace names whoever allocated
   next. What is needed is the writer, and a debugging allocator or KASAN names it.
3. **Keep the console of a boot that died.** See the next section; without it nothing here would have been found.
4. **Compare what should be identical.** The ROM's boot image, the ROM's recovery and the custom recovery carried the same kernel and
   device tree, yet behaved differently. So the kernel version was not the cause; what differs is what each one allocates and when.
5. **Read the clock.** A panic at 1.1 s is before user space, so no user-space program did it; at 2.67 s there is no USB gadget yet,
   so USB did not either. The uptime stamp cut hypotheses faster than any experiment.
6. **Switch the suspect off, reversibly.** A kernel command-line parameter on the ROM's own boot image, started with `fastboot boot`,
   writes nothing, and a successful boot is a stronger confirmation than a log.

## Keeping the console on a Qualcomm phone

* The kernel's console of the last boot is kept in RAM (`pstore`/`ramoops`) and is readable after the next start from
  `/sys/fs/pstore/console-ramoops-0`. But the RAM survives only a **warm** reset.
* On this phone (and on devices whose PMIC node has `qcom,store-hard-reset-reason`) a restart is warm only after a kernel panic
  (download mode armed) or for `edl`; `reboot`, `reboot bootloader`, init's reboot after a failed service and a long press of Power are
  **hard** resets that empty the RAM. The device tree property `qcom,force-warm-reboot` in the `qcom,pshold` node makes every restart warm;
  a boot image with it was made for the capture.
* Power plus Volume-Down for a few seconds is a warm reset on this phone; Power alone is hard.
* The kernel zaps the console zone at the start of the next boot (`persistent_ram_zap` at the end of `ramoops_init_prz`), after copying
  it for reading. Only the first reader sees it, so the first thing that runs after a crash must save the console to storage and do nothing
  else risky. A reader that dies first takes the evidence with it; that happened once here.
* A kernel with `panic=0` freezes instead of restarting; then the usual way out is a hard reset that destroys the evidence.

## What went wrong along the way (so that it is not repeated)

* **Changing five things at once** (`r7`: a different kernel binary, two command-line options, a CPU governor switch, a sensor-reading
  recorder). It failed, and nothing could be concluded. One variable per attempt.
* **Believing a control that was not counted.** "The ROM's own recovery always boots" was the owner's impression, and it led to "the phone
  is fine" for days. A recovery that allocates little can carry a corrupted free object around without ever touching it.
* **A passing test taken for more than it covers.** The RAM stress test (0 errors in 1.9 TiB) says the memory cells hold their data under a
  steady load. It cannot say anything about a bug that overwrites memory at boot.
* **An old crash dump read as the cause.** The `minidump` partition held a kernel panic that looked relevant; its kernel was 4.14.190,
  the MIUI days, not the 4.14.356 that ran Android. Check the version and the date inside a dump first.
* **A recorder that shaped what it recorded.** The black-box recorder wrote every 3 s, dropped the charger and USB lines, and only knew
  the boots that had reached it, so "deaths cluster at 11.5-14.2 s" was partly an artefact of when it wrote, what it filtered and which
  boots it could see.
* **Reading "decryption hangs" into the first log** because the log ended right after "Device ready for decryption". The recovery without
  any decryption failed as often.

## Checklist for a phone that will not boot (without wiping it)

1. Copy the data first, and verify the copy. Nothing below needs a wipe; if a step seems to, stop and ask the owner.
2. Read-only diagnosis from a recovery: boot reason in `/metadata/bootstat`, the `misc` message, partition hashes against the official
   release, a read test of every partition, the kernel logs the ROM's recovery keeps (`/cache/recovery/last_kmsg*`), `pstore`.
3. Get the console of a failing boot (warm reset, first reader saves it).
4. Read the first error in it. Note the uptime of the first crash.
5. If it is heap corruption: a debug kernel (KASAN, `slub_debug=FZPU`), or the same parameters on the stock kernel if it was built with
   `CONFIG_SLUB_DEBUG`. (Here a debug kernel was built; it was not tried whether `slub_debug` alone on the release kernel would have been
   enough.)
6. Name the writer. Find the smallest reversible switch: `initcall_blacklist=<init function>` for a built-in driver, `module_blacklist=`
   for a loadable module, `nr_cpus=`, `loglevel=`.
7. `fastboot boot` the ROM's own boot image with that one change. If Android starts, flash the same image to `boot` after a backup,
   and keep the original for the undo. A ROM update undoes it.
8. Say what is known and what is not, in short messages. A factory reset is the owner's decision, never a diagnostic step.

## FAQ

**Will a factory reset fix it?** No. The corruption happens in kernel memory before `/data` is used, and boots of a recovery that mounts
no `/data` failed as well. It would have destroyed the data for nothing.

**Will the official ROM fix it?** Almost certainly not. The ROM was reinstalled twice without change, and the stock recovery's logs show the
same failed probe. A MIUI ROM carries the same vendor driver (it was seen working in the MIUI days: while the chip answered), and MIUI
cannot open Android 16's encrypted data.

**Why did the hardware fail?** It cannot be told from software. The logs say: suddenly and permanently (working in the oldest saved
sessions, dead from some session on and in every boot after), and the clock line of the bus cannot be driven, with two different
chips on that bus failing. Common causes of such a fault are moisture or corrosion (even invisible), a knock or pressure on a flex, a
shorted or burnt part, a cracked solder joint. Which one is not known; see [3-root-cause.md](3-root-cause.md) for what to tell a repair
shop.

**Is the fix safe to keep?** It changes only the `boot` partition and is undone with one command. Risks: an OTA or a new ROM replaces
`boot` and the problem returns; the image has no AVB footer, so the bootloader has to stay unlocked.

**Does vibration really not work now?** It did not work before the fix either; the chip is silent. The camera flash LED, on the same bus,
is dead too.

**Why not fix the driver?** The proper fix is in the driver's error path: do not `kfree()` memory from `devm_kmalloc()`, and do not leave
a `request_firmware_nowait()` callback queued after a failed probe. The built-in driver is a Xiaomi variant whose source was not read, and
the ROM's kernel is built by its maintainers' CI. The parameter needed neither a rebuild nor the source.

**Could another phone have this?** Any phone whose kernel has this driver and whose chip or bus fails the same way. Whether other
models with `drv260x` behave like this was not checked.

## Tools used

All in [hesinj/orangefox-toco](https://github.com/hesinj/orangefox-toco): `tools/android-diagnose.bat` (read-only diagnosis of the
installed Android from the recovery), `tools/make-diag-boot.sh` (repack a ROM boot image with extra parameters, a dtb property
(`WARM=1`) or another kernel (`KERNEL=`)), `tools/toco-logs.bat` (collect logs over adb), `tools/ram-test.bat` (RAM stress test),
`tools/ota-verify.py` (compare the installed partitions with the ROM zip without storing it), and the black-box recorder of the recovery.
This repository's `tools/add_cmdline.py` is the small, self-contained part needed for the fix itself. The same lessons are packaged as
skills in that repository (`skills/`).
