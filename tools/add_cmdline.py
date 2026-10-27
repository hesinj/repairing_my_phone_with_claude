#!/usr/bin/env python3
"""Add kernel command line parameters to a boot image, change nothing else, and prove it.

    python3 add_cmdline.py BOOT.img OUT.img "initcall_blacklist=drv260x_driver_init" [--mkbootimg DIR]

DIR holds AOSP's unpack_bootimg.py and mkbootimg.py
(git clone https://android.googlesource.com/platform/system/tools/mkbootimg). If --mkbootimg is not given the script
looks at the environment variable MKBOOTIMG_DIR, then at ../mkbootimg and ./mkbootimg.

The boot image is unpacked, the parameters are appended to its command line, and it is packed again with every other
setting of the original header (header version, offsets, page size, OS version and patch level). The packed image is then
unpacked once more and every part (kernel, ramdisk, dtb, ...) must be byte-identical to the original's; if anything
differs the output file is deleted and the exit code is 1. The result has no AVB footer: a phone with an unlocked
bootloader starts it (with the orange warning), a locked one does not.
"""
import argparse
import filecmp
import hashlib
import os
import shlex
import shutil
import subprocess
import sys
import tempfile


def find_tools(given):
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (given, os.environ.get("MKBOOTIMG_DIR"), os.path.join(here, "..", "mkbootimg"), os.path.join(here, "mkbootimg"), "mkbootimg"):
        if d and os.path.isfile(os.path.join(d, "unpack_bootimg.py")) and os.path.isfile(os.path.join(d, "mkbootimg.py")):
            return os.path.abspath(d)
    sys.exit("unpack_bootimg.py and mkbootimg.py not found: git clone https://android.googlesource.com/platform/system/tools/mkbootimg "
             "and pass --mkbootimg DIR (or set MKBOOTIMG_DIR)")


def unpack(tools, image, out):
    """unpack IMAGE into the folder OUT; return the mkbootimg arguments that rebuild it, as a list"""
    r = subprocess.run([sys.executable, os.path.join(tools, "unpack_bootimg.py"), "--boot_img", image, "--out", out, "--format=mkbootimg"],
                       check=True, capture_output=True, text=True)
    text = r.stdout
    if os.name == "nt":  # shlex treats the backslash as an escape; Python on Windows takes forward slashes in paths
        text = text.replace("\\", "/")
    return shlex.split(text)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("boot_img")
    ap.add_argument("out_img")
    ap.add_argument("extra", help="parameters to append to the kernel command line, one string")
    ap.add_argument("--mkbootimg", help="folder with unpack_bootimg.py and mkbootimg.py")
    a = ap.parse_args()
    tools = find_tools(a.mkbootimg)
    work = tempfile.mkdtemp(prefix="add_cmdline.")
    try:
        before = os.path.join(work, "before")
        args = unpack(tools, a.boot_img, before)
        if "--cmdline" not in args:
            sys.exit("this boot image has no command line field that mkbootimg can rewrite")
        i = args.index("--cmdline")
        old = args[i + 1]
        new = (old + " " + a.extra).strip()
        args[i + 1] = new
        if os.path.exists(a.out_img):
            os.remove(a.out_img)
        subprocess.run([sys.executable, os.path.join(tools, "mkbootimg.py")] + args + ["--output", a.out_img], check=True)

        after = os.path.join(work, "after")
        new_args = unpack(tools, a.out_img, after)
        bad = []
        if new_args[new_args.index("--cmdline") + 1] != new:
            bad.append("the command line of the new image is not the old one plus your parameters")
        for name in sorted(os.listdir(before)):
            if not os.path.isfile(os.path.join(after, name)) or not filecmp.cmp(os.path.join(before, name), os.path.join(after, name), shallow=False):
                bad.append("%s differs from the original" % name)
        if bad:
            os.remove(a.out_img)
            sys.exit("CHECK FAILED, %s deleted:\n  " % a.out_img + "\n  ".join(bad))
        print("command line before: " + old)
        print("command line after : " + new)
        print("identical to the original: " + ", ".join(sorted(os.listdir(before))))
        print("%s  %d bytes  sha256 %s" % (a.out_img, os.path.getsize(a.out_img), sha256(a.out_img)))
        print("ADD_CMDLINE_OK  (try it first with:  fastboot boot %s)" % a.out_img)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
