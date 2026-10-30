#!/usr/bin/env python3
"""Make the camera driver of the kernel in a boot image treat a failed I2C write to the "soft flash" chip as a success, and prove
that nothing else changed.

    python3 patch_softflash.py BOOT.img OUT.img [--mkbootimg DIR] [--expect 2]

Why: on the Mi Note 10 Lite whose I2C bus 3 is dead, every rear camera open makes the camera driver write the init settings of the
AW3644 "soft flash" (address 0x63 on that bus). The write fails, the open fails, and the vendor camera HAL then crashes in its error
path. This script finds the two places in the kernel's camera I2C code where the result of i2c_transfer() is kept in a register
(`mov wN, w0` right before `tbz w0, #31`), and replaces each with `mov wN, #1`: the function then returns "one message transferred"
even when the transfer failed. The error messages are still printed; the camera carries on. The soft flash itself stays dead.
See docs/en/6-camera.md.

How the places are found (no fixed offsets, so it can work on another build of the same kernel): the script looks for the function
name literal "cam_qup_i2c_txdata" in the decompressed kernel, finds the code that loads its address (ADRP + ADD), goes back to the
`tbz w0, #31` that decides about the error print, and checks that the instruction before it is `mov wN, w0`, the one before that a
`bl` (the call of i2c_transfer, with `mov w2, #1` = one message in front of it), and that `mov w0, wN` (the return) follows. A place
that fails one of these checks is not touched. If the number of places is not --expect (default 2), nothing is written.

The boot image is unpacked with AOSP's unpack_bootimg.py, the kernel is patched and compressed again, the image is packed with
mkbootimg.py using every other setting of the original header, unpacked once more, and then: ramdisk, dtb and all other parts must be
byte-identical to the original, the command line must be the same, and the decompressed kernel must differ from the original's in
exactly the patched words. Otherwise the output is deleted and the exit code is 1. The result has no AVB footer; an unlocked
bootloader starts it with a warning.
"""
import argparse
import filecmp
import hashlib
import os
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib


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


# ---------------------------------------------------------------------------------------------- kernel container
def decompress(data):
    """-> (raw Image, tail) ; gzip or an uncompressed arm64 Image"""
    if data[:2] == b"\x1f\x8b":
        d = zlib.decompressobj(31)
        raw = d.decompress(data)
        return raw, d.unused_data, True
    if data[0x38:0x3C] == b"ARMd":
        return data, b"", False
    sys.exit("the kernel in this boot image is neither gzip nor an arm64 Image (lz4 and others are not handled)")


def compress(raw):
    c = zlib.compressobj(9, zlib.DEFLATED, 31)
    gz = bytearray(c.compress(raw) + c.flush())
    gz[8], gz[9] = 2, 3        # the header bytes `gzip -9` writes (maximum compression, Unix); not covered by the checksum
    return bytes(gz)


# ---------------------------------------------------------------------------------------------- finding the places
def find_places(img):
    name = b"\x00cam_qup_i2c_txdata\x00"
    start, pos = 0, []
    while True:
        i = img.find(name, start)
        if i < 0:
            break
        pos.append(i + 1)
        start = i + 1
    if len(pos) != 1:
        sys.exit("the name literal cam_qup_i2c_txdata occurs %d times in the kernel (expected 1): not this kernel" % len(pos))
    target = pos[0]
    words = struct.unpack("<%dI" % (len(img) // 4), img[:len(img) // 4 * 4])
    refs = []
    for i, w in enumerate(words):
        if (w & 0x9F000000) != 0x90000000:                  # ADRP
            continue
        immlo, immhi = (w >> 29) & 3, (w >> 5) & 0x7FFFF
        imm = (immhi << 2) | immlo
        if imm & (1 << 20):
            imm -= 1 << 21
        if ((i * 4) & ~0xFFF) + (imm << 12) != (target & ~0xFFF):
            continue
        rd = w & 31
        for j in range(1, 9):
            if i + j < len(words):
                a = words[i + j]
                if (a & 0xFFC00000) == 0x91000000 and ((a >> 5) & 31) == rd and ((a >> 10) & 0xFFF) == (target & 0xFFF):
                    refs.append(i)
                    break
    places = []
    for r in refs:
        # go back to the `tbz w0, #31` of the error check
        t = next((k for k in range(r - 1, max(r - 17, 0), -1) if (words[k] & 0xFFF8001F) == 0x36F80000), None)
        if t is None:
            continue
        mov = words[t - 1]
        if (mov & 0xFFFFFFE0) != 0x2A0003E0:                # mov wN, w0
            continue
        n = mov & 31
        if (words[t - 2] & 0xFC000000) != 0x94000000:       # bl i2c_transfer
            continue
        if not any(words[t - 2 - j] == 0x52800022 for j in range(1, 15)):   # mov w2, #1 : one message
            continue
        if not any(words[t + j] == (0x2A0003E0 | (n << 16)) for j in range(1, 80)):   # mov w0, wN : the return value
            continue
        places.append(((t - 1) * 4, n))
    return sorted(set(places))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("boot_img")
    ap.add_argument("out_img")
    ap.add_argument("--mkbootimg", help="folder with unpack_bootimg.py and mkbootimg.py")
    ap.add_argument("--expect", type=int, default=2, help="how many places the kernel must have (default 2)")
    a = ap.parse_args()
    tools = find_tools(a.mkbootimg)
    work = tempfile.mkdtemp(prefix="patch_softflash.")
    try:
        before = os.path.join(work, "before")
        args = unpack(tools, a.boot_img, before)
        kfile = os.path.join(before, "kernel")
        raw, tail, gz = decompress(open(kfile, "rb").read())
        places = find_places(raw)
        for off, n in places:
            print("place at %#x in the decompressed kernel: mov w%d, w0  ->  mov w%d, #1" % (off, n, n))
        if len(places) != a.expect:
            sys.exit("found %d places, expected %d: nothing written (look at the kernel with a disassembler, or pass --expect)" % (len(places), a.expect))
        new = bytearray(raw)
        for off, n in places:
            if struct.unpack_from("<I", new, off)[0] != (0x2A0003E0 | n):
                sys.exit("internal error at %#x" % off)
            struct.pack_into("<I", new, off, 0x52800020 | n)
        newfile = os.path.join(work, "kernel.new")
        open(newfile, "wb").write((compress(bytes(new)) if gz else bytes(new)) + tail)
        args[args.index("--kernel") + 1] = newfile
        if os.path.exists(a.out_img):
            os.remove(a.out_img)
        subprocess.run([sys.executable, os.path.join(tools, "mkbootimg.py")] + args + ["--output", a.out_img], check=True)

        after = os.path.join(work, "after")
        new_args = unpack(tools, a.out_img, after)
        bad = []
        if new_args[new_args.index("--cmdline") + 1] != args[args.index("--cmdline") + 1]:
            bad.append("the command line changed")
        for name in sorted(os.listdir(before)):
            if name == "kernel":
                continue
            if not os.path.isfile(os.path.join(after, name)) or not filecmp.cmp(os.path.join(before, name), os.path.join(after, name), shallow=False):
                bad.append("%s differs from the original" % name)
        raw2, tail2, _ = decompress(open(os.path.join(after, "kernel"), "rb").read())
        if tail2 != tail:
            bad.append("the data behind the kernel differs")
        diff = [i for i in range(len(raw)) if raw[i] != raw2[i]] if len(raw) == len(raw2) else None
        want = sorted(i for off, n in places for i in range(off, off + 4) if raw[i] != new[i])
        if diff != want:
            bad.append("the kernel differs in other bytes than the patched words")
        if bad:
            os.remove(a.out_img)
            sys.exit("CHECK FAILED, %s deleted:\n  " % a.out_img + "\n  ".join(bad))
        print("identical to the original: " + ", ".join(n for n in sorted(os.listdir(before)) if n != "kernel") + "; command line unchanged")
        print("kernel: %d bytes decompressed in both, %d bytes differ (%s)" % (len(raw), len(diff), ", ".join("%#x" % i for i in diff)))
        print("%s  %d bytes  sha256 %s" % (a.out_img, os.path.getsize(a.out_img), sha256(a.out_img)))
        print("PATCH_SOFTFLASH_OK  (try it first with:  fastboot boot %s)" % a.out_img)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
