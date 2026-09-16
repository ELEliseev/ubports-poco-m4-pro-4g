# Porting Ubuntu Touch to Xiaomi fleur

**Device:** Xiaomi fleur = Poco M4 Pro 4G = Redmi Note 11S
**SoC:** MediaTek Helio G96 (MT6781), kernel 4.14, A/B layout, 8.5 GB `super`
**State:** usable as a daily driver.

This is written so somebody else can repeat the port from nothing. The sections
follow the order of the work. Commands are complete and meant to be copied.

> **Read this before anything else.**
> Xiaomi's published kernel sources (branch `fleur-s-oss`, commit `32022887f`)
> are **older than the kernel actually flashed on the phone**
> (`4.14.186-perf-g8068275caa57`). The vendor's binary blobs were built against
> the flashed kernel and ask it for things the published sources never had.
> Almost every failure in this port has the same shape: a blob calls a function
> or an ioctl that our kernel does not implement. The cure is the same too —
> find the missing piece in a neighbouring MiCode branch and port it across.

---

## 1. What you get, and what you do not

| Works | Does not |
|---|---|
| boot, systemd, ssh | calls (untested) |
| 1080×2400 display, Mali-G57, OpenGL ES 3.2 | Bluetooth (`hci0` never comes up) |
| Lomiri, keyboard, indicators, touchscreen | video recording bitrate is absurd (§ 9.4) |
| Wi-Fi, mobile data, battery | MTP and developer mode |
| audio, microphone, the stock player | |
| camera: stills, viewfinder, video with sound | |
| hardware video playback | |
| AmneziaWG VPN with its own GUI | |

This is a **development port**: ssh with an empty password, `ADBD_SECURE=0`.
Locking that down is a separate job before daily use.

---

## 2. How the finished system is put together

Bottom to top. Each layer hides the failures of the one above it, which is why
you fix them bottom-up.

```
┌──────────────────────────────────────────────────────────────┐
│  Lomiri · apps · Qt 5.12                                     │
├──────────────────────────────────────────────────────────────┤
│  Mir (compositor)   media-hub   PulseAudio   qtubuntu-camera │
├──────────────────────────────────────────────────────────────┤
│  libhybris — the glibc ↔ bionic bridge, loads Android .so    │
├──────────────────────────────────────────────────────────────┤
│  LXC container "android" = Halium GSI + stock vendor/odm     │
│  inside: hwcomposer@2.1 · camerahalserver · audio HAL · vpud │
├──────────────────────────────────────────────────────────────┤
│  Ubuntu Touch 20.04 (focal), rootfs in the logical partition │
│  system_a inside super                                       │
├──────────────────────────────────────────────────────────────┤
│  halium-boot initramfs — finds super, assembles /dev/mapper, │
│  mounts the rootfs                                           │
├──────────────────────────────────────────────────────────────┤
│  OUR KERNEL 4.14, patched                                    │
└──────────────────────────────────────────────────────────────┘
```

Three things worth understanding immediately:

1. **We do not build the Android side.** `/android/system` is a prebuilt Halium
   GSI downloaded from UBports CI. That is what "generic" means: a universal
   Android half plus your own kernel.
2. **The vendor blobs come out of the phone's stock `super`.** Which is why
   `super` **must not be erased wholesale** — `vendor` and `odm` go with it, and
   then neither MIUI nor Ubuntu Touch will boot.
3. **What is actually ours is the kernel, the initramfs and the overlay** — a
   handful of systemd units and replaced files. Everything else arrives ready-made.

---

## 3. The order of work

```
① host setup                 apt install …, clang-r383902 toolchain
        │
② sources                    MiCode fleur-s-oss + the 4.19 donor tree
        │
③ kernel patches             halium.config + transplanted drivers
        │
④ build the kernel   ──────► Image.gz            scripts/build-kernel.sh -c
        │
⑤ boot.img          ──────►  boot.img            mkbootimg + our ramdisk
        │
⑥ device tarball    ──────►  device_fleur.tar.xz build.sh
        │
⑦ rootfs            ──────►  rootfs.img          prepare-fake-ota + system-image-from-ota
        │
⑧ FLASHING (order matters, § 8)
        │
⑨ first boot, diagnostics
        │
⑩ fixing the layers: graphics → audio → camera → …
```

Steps ④ and ⑩ repeat in a loop: patch the kernel, build, flash `boot_a` alone,
test. The full ⑦–⑧ cycle is only needed when `overlay/` or the kernel modules
changed.

---

## 4. Where everything comes from

| What | Source |
|---|---|
| Kernel sources | `https://github.com/MiCode/Xiaomi_Kernel_OpenSource`, branch `fleur-s-oss` |
| 4.19 donor tree | `https://github.com/StasGr12/kernel_ubports_mt6781.git`, branch `main` |
| Donor branches for drivers | MiCode again: `camellian-t-oss`, `light-u-oss` (Android 13/14, same `mt6853`) |
| **Compiler** | `https://android.googlesource.com/platform/prebuilts/clang/host/linux-x86/+archive/refs/heads/android11-release/clang-r383902.tar.gz` |
| Build tools | UBports halium-generic-adaptation-build-tools |
| Ubuntu Touch rootfs | UBports CI, job `ubuntu-touch-rootfs`, branch `ubports%252Ffocal` |
| Halium GSI | UBports CI, `generic_arm64` / `halium-12.0`, artifact `halium_halium_arm64.tar.xz` |
| Stock firmware | fastboot ROM `fleur_global_images_V13.0.9.0.SKEMIXM…` |
| TWRP | `twrp-3.7.1_12-0-fleur.img` |
| Unbricking | mtkclient (BROM) |

Do **not** guess URLs on `cdimage.ubports.com` for the rootfs and the GSI — what
comes back is an 11 KB 404 page that looks like an archive. The only correct
route is `prepare-fake-ota.sh`, which talks to Jenkins.

---

## 5. Host setup

```bash
sudo apt install -y git wget curl bc bison flex libssl-dev make gcc \
     gcc-aarch64-linux-gnu binutils-aarch64-linux-gnu \
     python3 python3-pip android-sdk-libsparse-utils \
     e2fsprogs fastboot adb libelf-dev cpio fakeroot rsync

# Xiaomi's compiler, OUTSIDE the build directory
mkdir -p ~/toolchains/clang-r383902 && cd ~/toolchains/clang-r383902
curl -sL -A "Mozilla/5.0" -o c.tar.gz \
 "https://android.googlesource.com/platform/prebuilts/clang/host/linux-x86/+archive/refs/heads/android11-release/clang-r383902.tar.gz"
tar xf c.tar.gz && rm c.tar.gz
```

**Why the toolchain lives outside the build directory.** The UBports
`setup_repositories.sh` contains
`rm -rf "$TMPDOWN/linux-x86/"!("clang-$CLANG_REVISION")`, which deletes every
clang revision in the download directory except the one it wants. The first
build will eat somebody else's toolchain if you put it there.

You need **at least 8 GB of RAM plus swap**. A kernel build fits in 7 GB. An
AOSP build — needed only for a couple of libraries — does not: `soong_build`
takes 5.5 GB and carries the whole session away with it. If you must run one:

```bash
setsid nohup nice -n 10 ./yourscript.sh &   # survives closing the terminal
# and as the first line inside the script:
echo 1000 > /proc/self/oom_score_adj        # the OOM killer takes the build, not your editor
```

---

## 6. Building

### 6.1 Device configuration — `deviceinfo`

```ini
deviceinfo_codename="fleur"
deviceinfo_arch="aarch64"
deviceinfo_kernel_source="https://github.com/MiCode/Xiaomi_Kernel_OpenSource"
deviceinfo_kernel_source_branch="fleur-s-oss"
deviceinfo_kernel_defconfig="fleur_defconfig halium.config"
deviceinfo_kernel_cmdline="console=tty0 bootopt=64S3,32N2,64N2 systempart=/dev/mapper/system_a systemd.mask=usb-rescue-mode-off.service"
deviceinfo_dtb="mediatek/mt6781.dtb"
deviceinfo_flash_offset_kernel="0x40080000"
deviceinfo_flash_offset_ramdisk="0x47c80000"
deviceinfo_flash_offset_tags="0x4bc80000"
deviceinfo_flash_offset_dtb="0x4bc80000"
deviceinfo_flash_pagesize="2048"
deviceinfo_bootimg_header_version="2"
deviceinfo_halium_version="12"
deviceinfo_ubuntu_touch_release="focal"
```

Every line below has already tripped somebody up:

* `console=tty0` is **mandatory**. Without it the rootfs does not boot. Other
  ports (rosemary) do not have it, and the temptation to match them is strong.
* `deviceinfo_dtb="mediatek/mt6781.dtb"` — that is what the tree actually
  builds. There is a `fleur.dts` in the sources, but it is broken and not wired
  into the Makefile.
* `systempart=/dev/mapper/system_a` ties the port to the "logical partition
  inside super" layout. Drop it and the image is looked up as a file on the
  data partition, where it **must** be called `ubuntu.img`.
* `systemd.mask=usb-rescue-mode-off.service` keeps ssh alive once the shell
  starts (§ 10.3).
* `ubuntu_touch_release="focal"` — **not 24.04** (§ 6.5).

### 6.2 Building the kernel

```bash
scripts/build-kernel.sh -c    # regenerate .config and build
scripts/build-kernel.sh       # build only
```

**Four mandatory conditions, every one of them found by chasing a false lead:**

| Condition | What happened without it |
|---|---|
| compiler **clang-r383902** | kernel hangs two seconds in, without a single message |
| `CROSS_COMPILE=aarch64-linux-gnu-` | "`-fstack-protector-strong` is not supported by the compiler" — a lie; the real problem is the assembler from GCC 4.9 (2017), which does not know `cortex-a55` |
| `LD=ld.lld` | "relocation truncated to fit: `R_AARCH64_LDST64_ABS_LO12_NC`" while linking vmlinux |
| `KCFLAGS=-fno-builtin-stpcpy` | "undefined symbol: stpcpy" — clang folds `strcpy`+`strlen` into `stpcpy`, which the kernel does not have |

On the compiler specifically: the version the manufacturer used is written in
the stock kernel's version string — `Android (6443078 based on r383902) clang
11.0.2`. **The general rule: for a vendor kernel, use the vendor's compiler.**

### 6.3 Checking the configuration — always do this

```bash
curl -sL -o /tmp/mer_verify_kernel_config \
  https://raw.githubusercontent.com/mer-hybris/mer-kernel-check/master/mer_verify_kernel_config
perl /tmp/mer_verify_kernel_config <kernel obj dir>/.config
```

Halium's own checker gives you in a minute what takes half an evening by hand.

Separately there are **systemd's requirements**, which the checker does not know
about. Without them systemd exits with status 2 having written nothing, and it
looks like `Kernel panic - not syncing: Attempted to kill init!` six seconds in:

```
CONFIG_AUTOFS4_FS=y   CONFIG_CGROUP_PIDS=y   CONFIG_CGROUP_DEVICE=y
CONFIG_CGROUP_PERF=y  CONFIG_BLK_CGROUP=y    CONFIG_CGROUP_NET_CLASSID=y
CONFIG_CGROUP_NET_PRIO=y   CONFIG_NET_CLS_CGROUP=y
```

`SYSFS_DEPRECATED` and `SYSFS_DEPRECATED_V2` must be off.

One known discrepancy: `CONFIG_STATIC_USERMODEHELPER=y` is written straight into
`fleur_defconfig` and a `halium.config` fragment does not override it — the
defconfig itself has to be edited.

### 6.4 boot.img

```bash
S=/tmp/bootparts
python3 <tools>/unpack_bootimg.py --boot_img <known-good boot.img> --out $S

python3 <tools>/mkbootimg.py \
  --kernel <kernel obj dir>/arch/arm64/boot/Image.gz \
  --ramdisk $S/ramdisk --dtb $S/dtb \
  --cmdline "console=tty0 bootopt=64S3,32N2,64N2 systempart=/dev/mapper/system_a systemd.mask=usb-rescue-mode-off.service" \
  --base 0x00000000 --kernel_offset 0x40080000 --ramdisk_offset 0x47c80000 \
  --second_offset 0x00000000 --tags_offset 0x4bc80000 --dtb_offset 0x4bc80000 \
  --pagesize 2048 --os_version 12.0.0 --os_patch_level 2024-12 \
  --header_version 2 --output new-boot.img
```

**Take the ramdisk from a working image, not from stock.** It carries a fix
without which the port does not boot at all:

> There is no udev in the initramfs, so nothing creates
> `/dev/disk/by-partlabel/`. And `scripts/halium` checks for exactly that:
> `if [ -b /dev/disk/by-partlabel/super ]; then parse-android-dynparts … | sh`.
> The test silently fails → `/dev/mapper` stays empty → `systempart` is not
> found → initrd panics and drops to the emergency telnet. The fix is a
> `scripts/init-premount/partlabels` script that creates the links itself from
> `PARTNAME` in `/sys/class/block/*/uevent`, plus a fallback that finds `super`
> by size (16777216 sectors).

Only ever repack the ramdisk under `fakeroot`, otherwise root ownership is lost.

### 6.5 rootfs

```bash
./build.sh                       # produces device_fleur.tar.xz
./prepare-fake-ota.sh      <out>/device_fleur.tar.xz <out>/ota-focal
./system-image-from-ota.sh <out>/ota-focal/ubuntu_command <out>/flashable-focal
```

Both steps are slow (hundreds of megabytes over the network plus `mkfs`), and
the second needs `sudo`. The result is `flashable-focal/rootfs.img`.

**Check what actually downloaded:**

```bash
file <out>/ota-focal/ubuntu-touch-android9plus-rootfs-arm64.tar.gz
```

If that says "HTML document" and it is 11 KB, the CI job moved. Override the
source with environment variables (`ROOTFS_URL=…`) rather than editing the
script.

**Ubuntu Touch 24.04 is incompatible with a 4.14 kernel.** glib 2.80 watches
child processes through `pidfd`, which needs kernel ≥ 5.3. The nasty part is
that `CLONE_PIDFD` means something else on the old kernel, so the call
nominally succeeds, glib gets a useless descriptor and falls over:

```
glib/gmain.c:5802: waitid(pid:2624, pidfd=15) failed: Invalid argument (22)
```

49 service starts are affected, 35 of them the display manager. Hence **focal**.

---

## 7. Flashing

> **Our `boot.img` is written LAST.** `fastbootd` — the mode where logical
> partitions inside `super` are visible — lives in the recovery half of the
> **stock** `boot.img`. halium-boot does not have it. Flash our boot, then say
> `fastboot reboot fastboot`, and the phone has nowhere to boot: you get a loop
> the key combinations cannot break, because `lk` never reaches fastboot. The
> way out is BROM.

First check that `super` has a layout at all:

```bash
fastboot reboot fastboot
fastboot getvar is-userspace                 # must become yes
fastboot getvar partition-size:vendor_a      # must answer with a size
```

If `vendor_a`/`system_a`/`odm_a` answer `Could not open partition`, the `super`
metadata is gone and you need a full stock restore first.

The order:

```bash
stat -c%s <out>/flashable-focal/rootfs.img   # you need the size below

# 1. in fastbootd, hand the stock system_a space to our rootfs
fastboot reboot fastboot
fastboot delete-logical-partition system_a
fastboot create-logical-partition system_a <size in bytes>
fastboot flash system_a <out>/flashable-focal/rootfs.img

# 2. back to the normal bootloader, turn signature checking off
fastboot reboot bootloader
fastboot --disable-verity --disable-verification flash vbmeta vbmeta.img

# 3. dtbo, and ONLY NOW our boot
fastboot flash dtbo_a <stock dtbo.img>
fastboot erase expdb
fastboot flash boot_a <out>/boot.img

# 4. leftovers from the previous install get in init's way
fastboot -w
fastboot reboot
```

`vbmeta` is needed because our `boot.img` is not signed with Xiaomi's keys and
the stock vbmeta will reject it — a common cause of boot loops.

**Updating the kernel alone** on an installed system is far easier and needs no
key presses:

```bash
ssh -p 8022 phablet@<device> 'sudo reboot bootloader'
fastboot erase expdb
fastboot flash boot_a <image>
fastboot reboot
```

### What a successful boot looks like

RNDIS comes up and the phone answers on `ssh -p 8022 phablet@10.15.19.82`
(empty password). **10.15.19.82** is the working mode. **192.168.2.15** with
telnet is the emergency mode, and it means exactly one thing: the rootfs was
not found and not mounted. It does *not* mean "the kernel is broken".

Order of investigation for a failed first boot:

1. `parse-android-dynparts` did not find super → no `/dev/mapper/*`;
2. rootfs not mounted → `dmesg | grep -i halium` shows what init picked;
3. `WARNING: Android system image not found` → the image has no
   `var/lib/lxc/android/system.img`, i.e. the GSI never made it into the rootfs;
4. the container does not start → `lxc-ls -f`, `/var/log/lxc/android.log`.

---

## 8. Fixes, layer by layer

All kernel changes are in `kernel/patches/`.

### 8.1 Graphics

Work strictly bottom-up: `Mali + DRM` → `composer@2.1` → `libhybris` → `Mir`.

**a) The Mali version must match stock.** On opening `/dev/mali0` the blob
`libGLES_mali.so` checks the UK ABI and refuses to create a context on a
mismatch. That presents as `lightdm` crash-looping, which sends you the wrong
way entirely.

| | Mali DDK | UK ABI |
|---|---|---|
| stock kernel (what the blob was built for) | `r32p1-00bet5` | 11.31 |
| published `fleur-s-oss` sources | `r26p0-01eac0` | 11.27 |

The donor is the 4.19 tree, directory `mali-r32p1`. The fleur tree picks its
driver by a config string, so dropping the directory in and changing one word
is enough:

```bash
cp -a <donor>/mali-r32p1 <kernel>/drivers/misc/mediatek/gpu/gpu_mali/mali_valhall/
sed -i 's|"mali valhall r25p0"|"mali valhall r32p1"|' arch/arm64/configs/fleur_defconfig
```

Plus six 4.19 → 4.14 compatibility fixes (`mt-plat` paths, `mtk_ion` → `ion`,
`struct GPU_PMU` → `GPU_PMU`, `mmap_*`/`sysfs_emit` wrappers,
`kobj_type.default_groups` → `default_attrs`). They are in
`kernel/mali-r32p1-compat/`, and `scripts/setup-kernel-tree.sh` does all of
this for you. Verify with
`strings vmlinux | grep "UK version"` → `r32p1-00bet5`.

**b) The fight over the DRM master.** `/dev/dri/card0` hands "master" to
whoever opens it first. The vendor stack opens the node from three places at
once, and the loser spins on `failed to get drm master, retry: 1628101` —
**hundreds of thousands of times a second**. It does not test this with
`DRM_IOCTL_SET_MASTER` but with the vendor's `DRM_IOCTL_MTK_GET_MASTER_INFO`,
which simply returns `drm_is_current_master()`. So ordinary ioctl-failure
debugging shows nothing: the call **succeeds**, it just answers "no". The fix
is ownership within a single process plus "yes" to everyone on
`GET_MASTER_INFO`. **Careful:** answering "yes" to everyone is only safe while
the right to actually modeset stays narrow — loosen both and the composer and
the compositor program the panel simultaneously and the device hangs before the
boot finishes.

**c) The display must be owned by the Android service.** It only registers if
it opened `card0` before the compositor, and on a normal boot lightdm starts
first — so the two wait for each other. Fixed by
`mtk-display-hals-off.service` (`Before=lightdm.service`).

**d) The vendor HAL must not be let inside the compositor.** Mir tries to open
hwcomposer as a first-generation HAL and loads `hwcomposer.mt6781.so` into its
own process; two copies of the HAL fight and the service dies in
`validateDisplay`. Fixed by a drop-in that hides the module **from lightdm
only**:

```ini
[Service]
PrivateMounts=yes
BindPaths=/etc/systemd/system/empty-hal.so:/android/vendor/lib64/hw/hwcomposer.mt6781.so
```

A global `mount --bind` will not do — the container sees the same namespace.

**e) RGB332 versus C8.** The last link: the compositor reached `READY` and died
0.3 s later. It was not dying on its own — the vendor service aborted first:

```
[drm:drm_mode_setcrtc] Invalid pixel format RGB8 little-endian (0x38424752)
```

The vendor hwcomposer creates its dimming buffer as `DRM_FORMAT_RGB332`, while
in the published sources the same role is played by `DRM_FORMAT_C8`. Fixed in
`mtk_drm_mode_fb_create()` by normalising the incoming format.

### 8.2 Audio

Audio runs through the vendor HAL. The packaged `pulseaudio-modules-droid` is
no good: for focal, UBports only has builds up to API 30 (Android 11), and
fleur's vendor half is **API 31**. The HAL interface changed between 11 and 12
(`AUDIO_DEVICE_API_VERSION` 3.1 → 3.2) and the old module corrupts the heap.

So `pulseaudio-modules-droid-31` was built. **Two bugs that masked each other:**

1. **`.tarball-version` selects the API branch.** `PA_MAJOR` is computed in
   `configure.ac` from the *package* version, not the PulseAudio version. For
   focal it has to be exactly `14.2.97`. With a wrong value you get the
   `#if PULSEAUDIO_VERSION < 12` branch, which reads the
   `PA_SINK_MESSAGE_SET_STATE` field as an integer although it holds a pointer.
   The symptom is deceptive: **the module loads, the HAL opens, `pactl` reports
   RUNNING — and there is silence.** Quick test: the thread's CPU time
   (`awk '{print $14+$15}' /proc/PID/task/TID/stat`) stays at **zero**.
2. **44100 Hz destroys the HAL.** `double free or corruption` inside
   `out_write` on the very first call. Both fields in `/etc/pulse/daemon.conf`
   must be **48000**.

Microphone: the HAL only sets up playback and leaves the input side idle —
recording runs but every sample is zero. The route `AIN0` → preamplifier → ADC
→ UL1 is assembled by `mtk-audio-mic-route.service`.

To prove the kernel side is fine, bypassing the HAL:

```bash
amixer -c0 cset name='ADDA_DL_CH1 DL1_CH1' 1
amixer -c0 cset name='Ext_Speaker_Amp Switch' 1
aplay -D hw:0,0 tone.wav
```

### 8.3 The player: patching media-hub

`media-hub` asks D-Bus for the AppArmor profile name
(`GetConnectionCredentials` → `LinuxSecurityLabel`), gets an SELinux label
instead, fails to parse it and dies with SIGSEGV on every playback attempt. The
fix is one string constant in the binary; see
[fix-media-hub.md](fix-media-hub.md).

**Do not try to enable AppArmor.** A 4.14 kernel runs only **one** major LSM at
a time, and the vendor HALs need SELinux. Turn AppArmor on and: without
`androidboot.selinux=permissive` you get a boot loop; with it the screen
flickers and `lightdm` restarts six times in half a minute. This was tested —
AppArmor denies nothing in the meantime (`audit=1` caught a single denial in 45
seconds, and it was not about graphics). The damage comes from giving up
SELinux.

### 8.4 Camera

**Three kernel changes, all of them transplants from neighbouring MiCode branches:**

1. **`ISP_CMD_POWER_CTRL` (command 50)** — stills and the viewfinder.
   The vendor HAL sent `ioctl 0xC0086B32` = `_IOWR('k', 50, unsigned int*)` and
   our driver answered `Unknown Cmd` and `-EPERM` — **4002 times in a row**. The
   ISP never powered up, `seninf`/`imgsensor` never appeared in the log, the
   sensor produced not one frame. The command is in branches `camellian-t-oss`
   and `light-u-oss` (same `cameraisp/src/mt6853/` directory).

   Two subtleties in the transplant:
   * the donor revision moved to **per-module** clocking; ours is **shared**.
     The effect is the same, so the module number is only validated;
   * the donor's power-down path empties the counter in a loop — you **must
     not** do that here, it would drop clocks other modules still hold. One
     symmetric `ISP_EnableClock(MFALSE)` instead.

   `ISP_StopHW`/`ISP_StopSVHW` are defined further down the file than the new
   handler, so they need forward declarations or
   `-Werror=implicit-function-declaration` stops the build.

2. **`SHARE_BUF_SIZE` 72 → 80** in `include/uapi/linux/mtk_vcu_controls.h`. It
   determines `sizeof(struct share_obj)` and therefore the ioctl numbers for
   `VCU_GET_OBJECT` (`0xc058760a`). At 72 the driver answered "Invalid
   cmd_number". Both numbers were confirmed by disassembling
   `/vendor/bin/vpud`.

3. **IPI structure lengths** in `venc_ipi_msg.h` — fields added from
   `camellian-t-oss`: `meta_size`, `meta_fd`, `qpmap` in
   `venc_ap_ipi_msg_enc`; eight fields in `venc_vcu_config` (the first of which
   sits in `venc_vsi`, which is why `sizeimage[]` was read at the wrong offset
   and came out zero).

Changes 2 and 3 are two halves of a single vendor change.

**The sign of success is not the `isp pwr_ctrl` lines** — the very chatty
`ISP_BH_Workqueue` pushes them out of the ring buffer — but `P1_SOF`/`P1_DON`
in dmesg and the absence of `Unknown Cmd`.

**Messages that look like errors but are not.** These stay in the log even with
a fully working camera:

```
qml: updateViewfinderResolution: viewfinder resolutions is not known yet
(AalImageEncoderControl::setSize) Size QSize(-1, -1) is not supported by the camera
```

**False leads not worth revisiting:** the empty viewfinder resolution list (the
interface it needs does not exist in any version of `qtubuntu-camera`);
`m_surface is NULL` and `Already have a texture id` (that is
`libaalmediaplayer.so`, the shutter sound); `libminisf.so` (the whole userspace
stack turned out to be irrelevant — the kernel change was enough).

**The camera freezing after a video is stopped is fixed**, and video sound
started working along with it. See [fix-camera-hang.md](fix-camera-hang.md).

Still open: the video bitrate is absurd — 32 frames of 1920×1440 took 27 MB,
about 848 KB per frame, roughly 130 Mbit/s. The encoder barely compresses.

### 8.5 Video playback

Solved in hardware; the details and the software-decoding fallback are in
[fix-video-playback.md](fix-video-playback.md).

### 8.6 VPN

The real AmneziaVPN client cannot be built — it needs Qt 6.6, and this is Qt
5.12 with no Qt6 graphics layer for Mir/Lomiri. The protocol itself was built
(`amneziawg-go`, `awg`, `awg-quick`) and the GUI written from scratch. The
obfuscation is genuine: `awg show` lists `jc/jmin/jmax/s1/s2/h1..h4`.

The kernel only needs `CONFIG_TUN=y` (already there) and
`CONFIG_NETFILTER_XT_MATCH_ADDRTYPE=y` — without the latter `awg-quick` stops
at `Couldn't load match addrtype` and the tunnel never comes up.

---

## 9. The traps that cost the most time

**9.1. The expdb log is interleaved.** Before **every** boot test, run
`fastboot erase expdb`. Otherwise the dump holds records from all previous
boots, stock ones included, and they cannot be told apart: several hours went
into a `Kernel panic: Attempted to kill init` that turned out to be a trace of
the **stock** kernel.

```bash
strings -n 4 dump.bin | grep -c "Booting Linux on physical CPU"   # how many boots
strings -n 4 dump.bin | grep -E "^\[ *[0-9]+\.[0-9]{6}\]" | tail -30
```

**9.2. systemd drop-ins are applied alphabetically.** The packaged
`ubuntu-touch.conf` overrides anything set earlier. Ours are named `zz-…`, or
the setting is silently ignored.

**9.3. ssh disappears once the port starts working.** `10.15.19.82:8022` is
`usb-moded`'s rescue mode, which switches off when `graphical.target` is
reached. While the port was broken the link held by itself; the moment the
shell came up, it vanished. Hence `systemd.mask=usb-rescue-mode-off.service` in
the cmdline. Side effect: MTP and developer mode do not work.

**9.4. The app environment is scrubbed.** `lomiri-app-launch` throws away
`LD_PRELOAD` (verified: it is not in `/proc/PID/environ`), and launching around
Mir is refused — "Failed to connect: not accepted by server". Debugging an app
means rebuilding it.

**9.5. You can only add a file to the Android directories by overlaying.**
`/android/system/lib64` is mounted read-only, and the hybris linker looks only
there and **ignores `LD_LIBRARY_PATH`**:

```bash
mount -t overlay fleur-androidlibs \
  -o lowerdir=/android/system/lib64,upperdir=/userdata/…/upper,workdir=/userdata/…/work \
  /android/system/lib64
```

**9.6. The logs are full of spam.** In the kernel log, `[VCU] Invalid
cmd_number` thousands of lines a second; in the Android log,
`SpeechMessengerNormal: ccci not ready` every two seconds. Out of 38 396 logcat
lines, **one** was useful. Always filter: `dmesg | grep -av VCU`. And `grep -a`
is mandatory — the log contains binary fragments that make grep hide the text.

**9.7. The Android log lies about pids.** For host processes the pid field is
`0` and the real thread id is in the next field. It is easy to blame the wrong
process for somebody else's errors.

**9.8. `pgrep -f` over ssh lies** — the pattern matches the shell's own command
line, and a dead process looks alive.

**9.9. Count enumerations carefully.** The search for the ISP command nearly
dead-ended over a miscount: 46 entries instead of 50, leading to the conclusion
that no open branch had it. A reliable way:

```bash
sed -n '/enum ISP_CMD_ENUM/,/^};/p' inc/camera_isp.h \
  | grep -oE "^\s+[A-Z_0-9]+" | tr -d ' \t' | awk '{printf "%2d  %s\n", NR-1, $0}'
```

### Debugging techniques that earned their keep

* **Crash address → source line.** Turn off randomisation
  (`echo 0 > /proc/sys/kernel/randomize_va_space`), turn on exception tracing
  (`echo 1 > /proc/sys/debug/exception-trace`), take `pc` and the library base
  from `dmesg`, subtract and feed to `aarch64-linux-gnu-addr2line -f -C -i -e`.
* **Native stacks of a hung Android process:** `debuggerd <pid>` inside the
  container. It prints every thread. `wchan` is useless here — the thread sits
  in `nanosleep`.
* **Who is waiting for whom over binder:**
  `/sys/kernel/debug/binder/transactions` (needs `CONFIG_DEBUG_FS=y`).
* **Talking to the vendor HAL directly** — `tools/camprobe.c`. Needs a sysroot
  with **the same glibc as the phone** (2.31; the host cross-compiler targets
  2.34 and gives "GLIBC_2.34 not found"), plus `-static-libgcc`.
* **Counters in the USB gadget serial number** (`usb_setup` in
  `scripts/panic/telnet`) — the only channel that works when nothing else does.
  That is how the initrd failure was found: `blk96-part93-supN-map:none`.
* **Check whether a Halium patch is applied by looking at exported symbols**
  (`nm -DC --defined-only`), not at sources you think you have.

---

## 10. Emergency recovery

| Situation | What to do |
|---|---|
| Flickering screen, boot loop | flash a known-good `boot.img` |
| Does not boot, but fastboot works | `fastboot flash boot_a` with a working image |
| Fastboot unreachable by key combination | BROM + mtkclient |
| Need the whole stock back | the fastboot ROM |

An MT6781 device can be revived from **any** state through BROM, so no boot
image can brick it permanently.

---

## 11. If you are repeating this on another MediaTek device

Same order of work; the general conclusions are these.

1. **First find out what the manufacturer built the kernel with** — the
   `Linux version` string of the stock kernel. Use that compiler.
2. **Compare the published sources' hash against the flashed kernel.** If they
   diverge, prepare to transplant drivers from neighbouring branches.
3. **Run `mer_verify_kernel_config` immediately**; do not hunt for missing
   options by hand.
4. **Fix strictly bottom-up.** Every layer masks the failures of the next: a
   crash-looping lightdm can mean a Mali version mismatch, and a frozen
   viewfinder can mean a missing ioctl in the kernel.
5. **Do not take error messages literally.** "The compiler does not support
   `-fstack-protector-strong`" meant an old assembler; "the module is loaded and
   RUNNING" meant the output thread had never executed the body of its loop.
