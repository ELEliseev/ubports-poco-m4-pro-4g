# Video playback

**Solved.** The stock player decodes video in hardware through the vendor's
Codec2 (`c2.mtk.avc.decoder` → SurfaceTexture → hybrissink). Getting there took
three fixes, and all three are collisions between Ubuntu's defaults and
Android's requirements. A software path is kept as a fallback and is described
at the end.

## The three fixes that made hardware decoding work

### 1. `kernel.pid_max = 32768`

`overlay/etc/sysctl.d/99-android-pid-max.conf`

The vendor's `android.hardware.media.c2@1.2-mediatek` is a 32-bit process, and
32-bit bionic refuses to work with a pid above 65535:
*"32 bit bionic libc only accepts pid <= 65535"*. Ubuntu sets 4194304 by
default (`/lib/sysctl.d/50-pid-max.conf`), so after about a day of uptime the
counter runs past the limit, the Codec2 service wedges in a futex, hwbinder
transactions pile up unanswered, video stops decoding, and
`gst-inspect-1.0 hybris` reports 0 features.

**The file name must sort AFTER `50-pid-max.conf`**, or Ubuntu's default wins.
That one has already caught us out.

### 2. `/dev/ion` mode 0666

`overlay/etc/udev/rules.d/70-mtk-media.rules`

`/vendor/etc/ueventd.rc` asks for `/dev/ion 0666 system graphics`. Inside the
Halium container there is no ueventd to do it, so the node stays `0600
root:root`. Without the permission the client half of Codec2 (`c2.mtk.*`)
cannot open ION, gets an empty allocator, and dies inside `libcodec2_vndk.so`
copying a `std::string` from a null pointer. From the outside that reads as
"media-hub died, playback error".

### 3. Kernel: `vidioc_vdec_qbuf` must treat `reserved2 == 0` as "no general buffer"

`kernel/patches/0011-vcodec-vdec-zero-means-no-general-buffer.patch`

Xiaomi's published sources expect `0xFFFFFFFF` as the "no buffer" marker; the
vendor userspace sends `0`. The driver therefore called `dma_buf_get(0)`,
rejected every frame buffer, and Codec2 answered `C2_CORRUPTED`.

## The software fallback

Worth keeping because it is independent of the vendor stack.

**The problem.** The MediaTek hardware decoder (`/dev/video0`, `mtk-vcodec-dec`)
on this SoC only advertises vendor block formats (M21S, MM21, MT21 and
friends). There are no plain NV12/YV12 entries in the V4L2 enumeration at all,
and GStreamer 1.16 from focal does not understand block formats:

```
gstv4l2object.c: V4L2 format M21S not supported
ERROR: pipeline doesn't want to preroll
```

The UBports image had no software H.264 decoder either: `gstreamer1.0-libav` is
not installed, and the available plugins are only `libde265dec` (H.265) and
`vpx` (VP8/VP9). Hence "Missing element: H.264 (High Profile) decoder".

**Part one — install the software decoders.** 14 focal arm64 packages, ~10 MB:
`gstreamer1.0-libav` and its dependencies (`libavformat58`, `libavfilter7`,
`libpostproc55`, `libswscale5`, `libbluray2`, `libmysofa1`, `librubberband2`,
`libvidstab1.1`, `libssh-gcrypt-4`, `libsodium23`, `libzmq5`, `libnorm1`,
`libpgm-5.2-0`). That brings in `avdec_h264`, `avdec_h265`, `avdec_vp9`,
`avdec_mpeg4` and some 360 more elements.

`scripts/fetch-prebuilts.sh` downloads them into `overlay/usr/lib/aarch64-linux-gnu/`.

**Part two — turn the V4L2 plugin off.** Otherwise `decodebin` still picks
`v4l2h264dec`: its rank is primary+1 (257) against `avdec_h264`'s primary
(256), and when the hardware decoder fails during format negotiation
`decodebin` no longer falls back — playback just dies.

Do it with Debian's own mechanism, which survives package upgrades and is
reversible:

```bash
sudo mount -o remount,rw /
sudo dpkg-divert --rename \
  --divert /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstvideo4linux2.so.disabled \
  --add /usr/lib/aarch64-linux-gnu/gstreamer-1.0/libgstvideo4linux2.so
sudo mount -o remount,ro /
```

To undo, the same with `--remove` instead of `--add`.

Do **not** rebuild the plugin registry by hand, and do **not** delete
`~/.cache/gstreamer-1.0/registry.aarch64.bin`: a full rescan hangs on this
device (`gst-inspect` sat there for six minutes). When a single file
disappears, the registry updates that one entry, quickly.

`GST_PLUGIN_FEATURE_RANK` does **not** help here — it arrived in GStreamer 1.18
and the image has 1.16.3 (verified: the rank does not change).

The V4L2 plugin is not needed on this port anyway: the camera goes through the
Android HAL (`camera_service`/binder), not `v4l2src`.

**Two more things the software path needs:**

1. media-hub would not load `libgstlibav.so`:
   `libgomp.so.1: cannot allocate memory in static TLS block`. Fixed with a
   drop-in, `~/.config/systemd/user/media-hub.service.d/tls.conf`:

   ```ini
   [Service]
   Environment=LD_PRELOAD=/lib/aarch64-linux-gnu/libgomp.so.1
   ```

2. Video output is the wall after that. `hybrissink` is hardware-only by
   design: in the gst-hybris sources `gst_mir_image_memory_is_mappable()`
   returns FALSE, `mem_map()` returns NULL, and `render()` never touches the
   pixels (the copy is behind `#if 0`). A software decoder cannot write into
   its pool.

**In practice** decoding happens on the CPU: 1080p H.264 keeps up, 4K does not.
A hardware path through GStreamer would need MediaTek block format (MM21
detiling) support, which 1.16 does not have.

Measured: a 1920×1080 test clip, 600 frames, decoded without clock sync in
1.55 s — about 390 fps. Plenty of headroom for 1080p30.

## A loose end

The driver reports a minimum of 16 with a step of 32 or 64 in
`VIDIOC_ENUM_FRAMESIZES`, so GStreamer prints

```
gst_value_set_int_range_step: assertion 'start % step == 0' failed
```

It is only a warning and does not stop playback. The cure would be rounding the
minimum up in `vidioc_enum_framesizes` (`mtk_vcodec_dec.c`).

## Ranks, for reference

The hardware element `amcviddec-c2mtkavcdecoder` has rank 258 against
`avdec_h264`'s 256, so `decodebin` reaches for the hardware first and the
software path stays a genuine fallback. The V4L2 plugin stays diverted: there
is no working hardware path through `/dev/video0` on this SoC, and its rank is
higher than the software decoder's.
