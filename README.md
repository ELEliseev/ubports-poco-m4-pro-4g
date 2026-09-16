# Ubuntu Touch for Xiaomi fleur

Ubuntu Touch 20.04 (focal) on **Xiaomi fleur** — sold as Poco M4 Pro 4G and
Redmi Note 11S. MediaTek Helio G96 (MT6781), kernel 4.14, A/B layout, an 8.5 GB
`super` partition.

The phone is usable as a daily driver. Calls are the notable gap.

> **This is a development port.** It ships ssh with an **empty password** and
> `ADBD_SECURE=0`. Anyone on the same network can log in as `phablet` and run
> `sudo` without a password. Do not carry it around in this state without
> setting a password first.

| Works | Does not |
|---|---|
| boot, systemd, ssh | calls (untested) |
| 1080×2400 display, Mali-G57, OpenGL ES 3.2 | Bluetooth (`hci0` never comes up) |
| Lomiri, keyboard, indicators, touchscreen | MTP and developer mode |
| Wi-Fi, mobile data, battery | video recording bitrate is absurd (~130 Mbit/s) |
| audio, microphone, the stock player | |
| camera: stills, viewfinder, video **with sound** | |
| hardware video playback | |
| AmneziaWG VPN with a small GUI | |

## What is in here

Only the parts that are ours. The kernel sources, the Halium GSI, the Ubuntu
Touch rootfs and the build tools all come from upstream and are fetched by the
scripts.

```
deviceinfo                 device configuration for the UBports build tools
kernel/patches/            12 patches against MiCode fleur-s-oss @ 32022887f
kernel/mali-r32p1-compat/  Mali r32p1 backported from a 4.19 tree to 4.14
kernel/halium.config       kernel config fragment on top of fleur_defconfig
overlay/                   systemd units and files layered onto the rootfs
scripts/                   fetch sources, build the kernel, regenerate patches
tools/                     small diagnostic programs used while porting
docs/                      the porting guide and per-problem write-ups
```

## Building

You need ~8 GB of RAM plus swap, and Xiaomi's own compiler. Using a different
compiler produces a kernel that hangs two seconds into boot without printing
anything — the vendor's toolchain is named in the stock kernel banner,
`Android (6443078 based on r383902) clang 11.0.2`.

```bash
# Xiaomi's clang, kept outside the build directory on purpose: the UBports
# setup script wipes every clang revision but the one it wants.
mkdir -p ~/toolchains/clang-r383902 && cd ~/toolchains/clang-r383902
curl -sL -A "Mozilla/5.0" -o c.tar.gz \
  "https://android.googlesource.com/platform/prebuilts/clang/host/linux-x86/+archive/refs/heads/android11-release/clang-r383902.tar.gz"
tar xf c.tar.gz && rm c.tar.gz

sudo apt install -y git wget curl bc bison flex libssl-dev make gcc \
  gcc-aarch64-linux-gnu binutils-aarch64-linux-gnu python3 python3-pip \
  android-sdk-libsparse-utils e2fsprogs fastboot adb libelf-dev cpio fakeroot rsync
```

Then, from a clone of this repository:

```bash
scripts/setup-kernel-tree.sh      # clone MiCode sources, apply our patches
scripts/build-kernel.sh -c        # configure and build
scripts/fetch-prebuilts.sh        # third-party libraries the overlay needs
```

`boot.img`, the device tarball and `rootfs.img` are produced by the UBports
[halium-generic-adaptation-build-tools][tools]; point them at `deviceinfo` and
`overlay/` from this repository. The whole sequence, including flashing, is in
[docs/porting-guide.md](docs/porting-guide.md).

[tools]: https://gitlab.com/ubports/community-ports/halium-generic-adaptation-build-tools

## Flashing, in one warning

**Our `boot.img` is written last.** `fastbootd` — the mode that can see logical
partitions inside `super` — lives in the recovery half of the *stock*
`boot.img`. halium-boot does not have it. Flash our boot first, then ask for
`fastboot reboot fastboot`, and the phone has nowhere to boot: you get a loop
that the key combinations cannot break, because `lk` never reaches fastboot.
Getting out means BROM and mtkclient.

Never erase `super` wholesale either: the vendor blobs this port runs on live
in the stock `vendor` and `odm` partitions inside it.

One thing is deliberately not translated: the AmneziaWG control GUI served by
`overlay/usr/local/lib/awg-control/server.py` still has a Russian interface.
Its code and comments are in English; only the strings a user sees are not.

## Notes on specific problems

* [docs/porting-guide.md](docs/porting-guide.md) — the whole port, start to finish
* [docs/fix-camera-hang.md](docs/fix-camera-hang.md) — the camera freezing after a video is stopped, and how video sound started working
* [docs/fix-video-playback.md](docs/fix-video-playback.md) — hardware and software video decoding
* [docs/fix-media-hub.md](docs/fix-media-hub.md) — media-hub crashing on an SELinux label

## The one lesson worth carrying to another MediaTek device

Xiaomi's published kernel sources (`fleur-s-oss`, commit `32022887f`) are older
than the kernel actually shipped on the phone (`4.14.186-perf-g8068275caa57`).
The vendor blobs were built against the shipped kernel and ask it for things
the published sources do not have. Nearly every failure in this port was the
same shape: a blob calls an ioctl or a function that our kernel does not
implement. The cure was always the same too — find it in a neighbouring MiCode
branch and port it across.

## Licence

GPL-3.0-or-later; see [LICENSE](LICENSE). The kernel patches are derivative
works of Linux and remain GPL-2.0. Third-party binaries are not redistributed
here — the scripts fetch them from their own distributors.
