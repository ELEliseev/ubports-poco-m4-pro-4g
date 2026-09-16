#!/usr/bin/env python3
"""Patch Ubuntu Touch's media-hub-server so it survives an SELinux security label.

media-hub asks D-Bus for the peer's AppArmor profile name
(GetConnectionCredentials -> LinuxSecurityLabel) on every playback session. On
this port AppArmor is not active -- a 4.14 kernel runs only one major LSM and
that slot is taken by SELinux, which the vendor HALs need -- so SO_PEERSEC
returns the SELinux label, the string "kernel". apparmor::lomiri::Context
rejects it, throws, and the service dies with SIGSEGV. From the outside this
looks like "the player cannot open this file".

The fix is one string constant: the name media-hub compares against when
deciding whether a client is unconfined. Nothing is weakened -- there are no
confinement rules in the first place, AppArmor is off.

The binary is not redistributed here: it is GPL and version-bound. Point this
script at the media-hub-server from your own image.

    scripts/patch-media-hub.sh /usr/bin/media-hub-server overlay/usr/bin/media-hub-server

The proper long-term fix is to run AppArmor, which needs SELinux to run
alongside it. See docs/porting-guide.md, section "Player: the media-hub patch".
"""
import hashlib
import shutil
import sys

# media-hub 4.7~20251006100339.1~45d5f81+ubports20.04, arm64
OFFSET = 678928
OLD = b"unconfined\x00"
NEW = b"kernel\x00\x00\x00\x00\x00"          # same length, NUL padded
MD5_STOCK = "154f1b170b6c9c578fbf81646a171285"
MD5_PATCHED = "5ddf2d089365349c549613d17ce69c40"

assert len(OLD) == len(NEW)


def main(argv):
    if len(argv) != 3:
        sys.exit(__doc__)
    src, dst = argv[1], argv[2]
    data = bytearray(open(src, "rb").read())
    digest = hashlib.md5(data).hexdigest()

    if digest == MD5_PATCHED:
        print(f"{src} is already patched; copying as is")
        shutil.copyfile(src, dst)
        return 0

    if digest != MD5_STOCK:
        sys.exit(
            f"{src}: md5 {digest}\n"
            f"expected the stock binary {MD5_STOCK}.\n"
            "media-hub has been updated; find the new offset of the "
            '"unconfined" constant before patching.'
        )

    if bytes(data[OFFSET:OFFSET + len(OLD)]) != OLD:
        sys.exit(f"{src}: no {OLD!r} at offset {OFFSET}")

    data[OFFSET:OFFSET + len(NEW)] = NEW
    open(dst, "wb").write(bytes(data))
    result = hashlib.md5(open(dst, "rb").read()).hexdigest()
    if result != MD5_PATCHED:
        sys.exit(f"{dst}: md5 {result}, expected {MD5_PATCHED}")
    print(f"patched -> {dst}")
    print("check on the device: media-hub should log is_unconfined(): true")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
