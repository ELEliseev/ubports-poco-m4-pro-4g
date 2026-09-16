#!/bin/bash
# Fetch the third-party binaries the overlay needs but does not carry.
#
# Two things are deliberately missing from this repository:
#
#   * the libav/ffmpeg libraries behind gstreamer1.0-libav. They are stock
#     Ubuntu focal arm64 packages under LGPL/GPL; shipping the binaries would
#     mean shipping their sources too, and Ubuntu already does that properly.
#   * media-hub-server, which is GPL, version-bound, and only differs from the
#     stock binary by one string constant. Use scripts/patch-media-hub.sh.
#
# Why libav at all: the MediaTek hardware decoder on /dev/video0 only advertises
# vendor block formats (M21S, MM21, MT21 and friends). GStreamer 1.16 in focal
# does not understand any of them, and the image ships no software H.264
# decoder. See docs/fix-video-playback.md.
set -eu

HERE="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$HERE/overlay/usr/lib/aarch64-linux-gnu"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

MIRROR="${MIRROR:-http://ports.ubuntu.com/ubuntu-ports}"
SUITE="${SUITE:-focal}"

PACKAGES="
gstreamer1.0-libav
libavformat58
libavfilter7
libpostproc55
libswscale5
libbluray2
libmysofa1
librubberband2
libvidstab1.1
libssh-gcrypt-4
libsodium23
libzmq5
libnorm1
libpgm-5.2-0
"

need() { command -v "$1" >/dev/null || { echo "missing $1" >&2; exit 1; }; }
need curl; need dpkg-deb; need zstd || true

echo "==> reading package indices from $MIRROR ($SUITE, arm64)"
INDEX="$WORK/Packages"
: > "$INDEX"
for comp in main universe; do
    for pocket in "$SUITE" "$SUITE-updates" "$SUITE-security"; do
        url="$MIRROR/dists/$pocket/$comp/binary-arm64/Packages.gz"
        curl -sfL "$url" | gzip -d >> "$INDEX" || true
    done
done
[ -s "$INDEX" ] || { echo "could not fetch any package index" >&2; exit 1; }

mkdir -p "$DEST/gstreamer-1.0"

for pkg in $PACKAGES; do
    # last matching stanza wins: -updates and -security are appended after the
    # release pocket, so this picks the newest available version
    path=$(awk -v p="$pkg" '
        /^Package: /   { cur = $2 }
        /^Filename: /  { if (cur == p) f = $2 }
        END            { print f }' "$INDEX")
    [ -n "$path" ] || { echo "$pkg: not found in the index" >&2; exit 1; }
    echo "==> $pkg"
    curl -sfL -o "$WORK/pkg.deb" "$MIRROR/$path"
    dpkg-deb -x "$WORK/pkg.deb" "$WORK/x"
done

echo "==> installing shared objects into overlay"
find "$WORK/x/usr/lib/aarch64-linux-gnu" -maxdepth 1 -name '*.so.*' -exec cp -a {} "$DEST/" \;
find "$WORK/x/usr/lib/aarch64-linux-gnu/gstreamer-1.0" -name 'libgstlibav.so' \
     -exec cp -a {} "$DEST/gstreamer-1.0/" \; 2>/dev/null || true

echo
echo "Installed into $DEST:"
ls -1 "$DEST" "$DEST/gstreamer-1.0" 2>/dev/null
echo
echo "The V4L2 GStreamer plugin must stay disabled, or decodebin still picks"
echo "v4l2h264dec over avdec_h264 -- see docs/fix-video-playback.md."
