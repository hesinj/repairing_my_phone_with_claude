# Tools

## add_cmdline.py

Adds kernel command-line parameters to a boot image, changes nothing else, and proves it.

```
python3 add_cmdline.py BOOT.img OUT.img "initcall_blacklist=drv260x_driver_init" --mkbootimg PATH/TO/mkbootimg
```

* Needs Python 3 and AOSP's `unpack_bootimg.py` and `mkbootimg.py` (`git clone https://android.googlesource.com/platform/system/tools/mkbootimg`,
  or the copy in an OrangeFox/TWRP tree at `system/tools/mkbootimg`). `--mkbootimg` can be replaced by the environment variable
  `MKBOOTIMG_DIR`.
* It unpacks the image, appends your parameters to its command line, packs it again with every other header field of the original
  (header version, offsets, page size, OS version, patch level), unpacks the result and compares every part (kernel, ramdisk, dtb, ...)
  byte for byte with the original. On any difference it deletes the output and exits with 1.
* The output has **no AVB footer**. An unlocked bootloader starts it with a warning; a locked one does not.
* Tested on Linux with the `mkbootimg` of the OrangeFox 12.1 tree (an Android 12-era copy of AOSP's tool) on the PixelOS 20260609_1626 boot
  image of the Mi Note 10 Lite: the result is byte-identical (sha256 `4f32c10b...`) to the image that was flashed on the phone. Not tried:
  Windows (the script replaces backslashes in the paths that the unpacker prints, because `shlex` treats them as escapes), macOS, and the
  current upstream `mkbootimg`.

## More tools

The diagnosis tools of this case (a read-only diagnosis of the installed Android from a recovery, a RAM stress test, a boot-image repacker
with a warm-reset dtb patch and a kernel swap, log collectors, the black-box recorder) are in
[hesinj/orangefox-toco](https://github.com/hesinj/orangefox-toco) under `tools/` and `skills/`.
