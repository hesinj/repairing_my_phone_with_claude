# The camera: one part fixed, three cameras still missing

After the haptics fix (27 October) Android ran, but the camera app did not work. On 30 October, three days later, Android bugreports showed
that the same dead I2C bus kills the **rear camera**, and that this can be worked around in the kernel. The **front, macro and ultra-wide cameras** are a
different matter: they are not found by the camera software, the dead bus does not explain it, and it is not fixed. Everything below
was read from Android bugreports taken on 30 October (raw excerpts: [evidence/08](../../evidence/08-rear-camera-dies-on-the-soft-flash-write.txt),
[09](../../evidence/09-two-kernel-experiments-on-the-soft-flash.txt), [10](../../evidence/10-cameras-that-are-not-found.txt),
[07](../../evidence/07-flash-is-on-the-pmic-not-on-the-bus.txt)). One phone, one day of experiments.

## In short

* **Symptom.** The camera app does not open. The vendor camera software (`android.hardware.camera.provider@2.4-service_64`, the camera
  HAL) crashes every time, and is restarted by Android.
* **Cause (read in the kernel log, five of five opens).** Whenever a rear camera is opened, the camera driver sends the init settings
  of the "soft flash" chip (an AW3644 at I2C address 0x63) over I2C bus 3, the bus that does not answer. The write fails
  (`Bus arbitration lost`, error -71), the open fails, and the closed-source HAL then crashes in its own error path.
* **Workaround.** Make the kernel report a failed write to that chip as a success. Two instructions in the kernel's camera I2C code,
  applied by [tools/patch_softflash.py](../../tools/patch_softflash.py) to a boot image. With it the main camera works: it was tried
  with `fastboot boot` (nothing written to the phone) and the owner reports that the main camera works; the log shows normal streams and no
  more HAL crashes. The soft flash itself stays dead. The main flash and the torch are not affected (they are driven by the
  power-management chip, see [2-evidence.md](2-evidence.md)).
* **Not fixed.** The front, macro and ultra-wide cameras are not found by the camera software, and the depth helper camera shows
  data errors. Section 7.

## 1. What happens when a rear camera is opened

[evidence/08](../../evidence/08-rear-camera-dies-on-the-soft-flash-write.txt) shows one open in the kernel log. The camera software
acquires the main sensor (IMX686) at 445.988 s. 61 ms later the camera flash driver applies the init settings of the soft-flash chip and the
I2C controller reports the same line that killed the haptics probe: `i2c_geni 890000.i2c: Bus arbitration lost, clock line undriveable`.
The write returns -71, the driver reports `Failed Flash Config`, and 1.3 s later the camera provider is gone. Its crash is a SIGSEGV in
`chi_override_flush`, the vendor's flush routine, which Android calls after the failed open. That is a bug in the error path of the closed
HAL; the failure that triggers it is the write.

The phone keeps the crash dumps (`/data/tombstones`). They contain 23 crashes of the camera provider: five on 1 July (a different
failure, in `CamX::IFENode::AcquireResources`, cause unknown) and 18 from **2 October** on with the signature above. If those 18 have the
cause shown here, the bus was already dead on 2 October, 17 days before Android stopped booting. That corrects
[2-evidence.md](2-evidence.md), section 5.

## 2. What the "soft flash" is

The device tree (the overlay in `prebuilt/dtbo.img` of the recovery repository; excerpts in
[evidence/07](../../evidence/07-flash-is-on-the-pmic-not-on-the-bus.txt)) gives the three rear sensors that have a flash two flash
sources each:

* `led-flash-src`: the flash module of the PM6150L power-management chip (SPMI, not I2C). It drives the flash and the torch.
* `soft-led-flash-src`: Xiaomi's addition to the camera driver. It points to the camera's "i2c_flash" devices on `890000.i2c`; the chip
  behind them is the AW3644 at 0x63, an AWINIC driver chip for flash LEDs with an IR mode. The kernel has a separate LED driver for it (`leds-aw3644`)
  that fails to probe at every boot for the same reason.

The camera software has a feature called `softlightMode` ("soft light mode"). That the soft flash is its hardware is a guess from the
names, not something a source says. What matters here is that the camera software initialises the chip every time a rear camera
opens, whether or not that feature is used.

## 3. Two experiments, both with `fastboot boot` ([evidence/09](../../evidence/09-two-kernel-experiments-on-the-soft-flash.txt))

1. **Hide the soft flash.** One byte in the kernel changes the name of the property that is looked up, so the sensors have no soft flash.
   The kernel then no longer tries to initialise it, which the log confirms. It does not help: the camera software needs the soft flash for
   the main camera and aborts 0.5 s after acquiring the sensor, in `CamX::SensorNode::CreateSensorSubmodules`, five of five times. (An
   edit of the device-tree overlay that drops the property would have the same effect, so it was not tried. A modified `dtbo.img` was
   prepared and never flashed.)
2. **Keep it visible, make the failed write count as a success.** This works (section 4).

## 4. The workaround

The kernel's camera I2C code for devices that sit on a plain I2C bus rather than on the camera's own bus has two functions that write,
`cam_qup_i2c_write` and `cam_qup_i2c_write_burst`. Each calls `i2c_transfer()` with one message, keeps the
result in a register (`mov w20, w0`), prints an error if it is negative, and returns the register. The patch replaces that copy with
`mov w20, #1`. The test for the error still looks at the real result, so the messages are still printed, but the function returns 1,
"one message transferred", and everything above it carries on.

On the PixelOS 20260609_1626 kernel (the compressed kernel has sha256 `abf7b66f...`) the two words are at 0xcee9e4 and 0xcef048 in the
decompressed Image: `f403002a` becomes `34008052`. `tools/patch_softflash.py` does not use fixed offsets: it looks for the function name
`cam_qup_i2c_txdata`, finds the code that prints it, and checks the instructions around it (a `bl`, a `mov wN, w0` before the
`tbz w0, #31` of the error test, one message, the register returned later). It then packs the boot image again with the original
header settings and proves that the ramdisk, dtb and command line are byte-identical and that the kernel differs in exactly those
bytes. Checked on this phone's image: it finds the same two places and produces the same kernel, ramdisk, dtb and command line as the
image that was tried.

```sh
python3 tools/add_cmdline.py boot-original.img boot-step1.img "initcall_blacklist=drv260x_driver_init" --mkbootimg PATH/TO/mkbootimg
python3 tools/patch_softflash.py boot-step1.img boot-camera.img --mkbootimg PATH/TO/mkbootimg
fastboot boot boot-camera.img        # writes nothing; open the rear camera several times
fastboot flash boot boot-camera.img  # only if it works and you want it to stay
```

The first command is the haptics fix of [4-fix.md](4-fix.md); the second adds the camera workaround on top. Undo as there:
`fastboot flash boot boot-original.img` (or the image with the haptics parameter only, to keep that fix).

## 5. Result ([evidence/09](../../evidence/09-two-kernel-experiments-on-the-soft-flash.txt), [10](../../evidence/10-cameras-that-are-not-found.txt))

In the log of the boot with the workaround, the sensor is opened about 30 times in a few minutes. A single-sensor session shows the
failed write (now returning 1), `CAM_START_DEV Success`, about seven seconds of streaming and a normal stop and release. There is no
camera-provider crash after that boot (the camera service never had to remove and add its devices again) and no kernel `BUG`, `WARNING`
or oops. The camera service log has two "client died" lines: they are the owner swiping the app away (`Killing ... remove task`), not
crashes. Each open prints five error lines and waits about 0.1 s for the failed write.

## 6. Side effects and limits

* The soft flash is not made to work. It could not work before, and if a feature needs it (the "soft light" mode, perhaps a dual-LED
  flash colour), it fails silently now. A photo with flash was not logged; the main flash and the torch run through the other chip.
* Nothing can reach the LEDs through this path: with the bus dead the write never gets to the chip, and if the bus is repaired, the
  writes are made as usual, because the patch only hides failures. After a repair, flash the original boot image and nothing of it remains.
* It hides **every** failed write of those two functions. In this phone's device tree the only camera device on a plain I2C bus is the
  soft flash, so nothing else is affected. On another device or kernel that may not hold.
* A ROM update replaces `boot` and the patch is gone; run the tool on the new boot image (it refuses, and writes nothing, if it cannot
  find exactly two places). A different ROM does not repair the bus: its kernel has the same haptics bug (see [4-fix.md](4-fix.md)) and its
  camera software probably the same dependency, so while the bus is dead it needs both changes.
* It is a workaround for a hardware fault, not a repair, and it was verified on one phone.

## 7. The cameras that are still missing ([evidence/10](../../evidence/10-cameras-that-are-not-found.txt))

The phone has four rear cameras and a front camera (device tree: five sensors; the rear ones are the wide camera, the depth sensor, the
macro camera with autofocus and the ultra-wide camera). The camera service has only **three devices, all facing back**: the wide camera, the
depth sensor, and a logical device made of both. What the log says about the others:

* **Front camera.** In every start of the HAL, one sensor gets no acknowledge on the camera's I2C bus (`NACK`, then a 1.5 s timeout) and
  reads as 0 instead of the expected chip id `0x1641`. The HAL maps the driver `toco_ov16a10_front`; that this id is the front sensor's
  is an inference. The HAL's own record of identified modules says `front_camera=none`.
* **Macro and ultra-wide.** The record says `back_camera_aux=none` twice, and nothing in the kernel log concerns these two sensors: the
  camera software never probes them. Reading the modules' EEPROMs fails with NACK twelve times per start, probably the same modules.
* **Depth sensor (S5K5E9).** It answers and streams, but in a session that uses it together with the wide sensor, the receiver of the
  CSI interface reports errors on the depth sensor's PHY. It is not a camera the user selects.
* **Since when.** In the crash dumps of the camera provider, from 1 July on, only the drivers of the wide and the depth sensor are
  loaded, and in October also the front one; the macro and ultra-wide drivers never. So these cameras were already missing before the
  bus failure, or never worked on this ROM. The log cannot tell which.
* **Not the bus.** These sensors are on the camera's own interface (CCI), not on I2C bus 3, and the workaround does not touch them.

Pattern: three modules, no electrical answer. That is how a hardware fault looks (module, connector, power), but a software cause (what
the ROM's camera configuration contains) is not excluded. Two checks would separate them: whether these cameras worked on this ROM before
July, and whether they work on another ROM or the stock firmware. For a repair shop: "the front, macro and ultra-wide camera modules do not
answer on the camera I2C bus."

## 8. After a hardware repair, or with another ROM

* **Repair of the bus (and the vibration module).** Flash the original boot image back: the haptics driver and the soft flash then work,
  and no workaround is needed. Changing the ROM is not part of that repair.
* **Repair of the camera modules.** Whether the front, macro and ultra-wide cameras then appear depends on what the ROM's camera software
  knows; the crash dumps suggest that on this ROM it did not know the macro and ultra-wide modules even in July. If they stay missing after a
  repair, the ROM is the next suspect.
* **Another ROM without a repair of the bus.** It does not solve the dead bus: expect the boot trouble again until its boot image has the
  haptics parameter, and the camera crash until it has the workaround. A clean install also wipes `/data`; copy the data off first.
* **Repair and another ROM.** If the bus really works afterwards, none of the workarounds of this repository is needed, and the cameras the
  new ROM supports should work if their modules do.
