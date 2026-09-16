#!/bin/bash
# Clone the vendor kernel and apply this port's patches.
#
# The kernel sources are Xiaomi's, not ours, so they are not vendored here.
# This script fetches them at the exact commit the port was built against and
# applies kernel/patches/*.patch plus the Mali r32p1 driver.
set -eu

HERE="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${1:-$HERE/../kernel-src/fleur-official}"
DONOR="${DONOR:-}"

KERNEL_URL=https://github.com/MiCode/Xiaomi_Kernel_OpenSource
KERNEL_BRANCH=fleur-s-oss
DONOR_URL=https://github.com/StasGr12/kernel_ubports_mt6781.git

if [ -e "$DEST" ]; then
    echo "$DEST already exists; refusing to touch it." >&2
    exit 1
fi

echo "==> cloning $KERNEL_BRANCH into $DEST"
git clone --depth 1 --branch "$KERNEL_BRANCH" "$KERNEL_URL" "$DEST"

echo "==> applying kernel/patches"
for p in "$HERE"/kernel/patches/*.patch; do
    echo "    $(basename "$p")"
    git -C "$DEST" apply "$p"
done

echo "==> installing halium.config"
cp "$HERE/kernel/halium.config" "$DEST/arch/arm64/configs/halium.config"

# The stock fleur tree ships Mali r26p0 (UK ABI 11.27). The vendor blob
# libGLES_mali.so was built against r32p1 (UK ABI 11.31) and refuses to create a
# context on a mismatch, which looks like lightdm crash-looping. r32p1 is not in
# the Xiaomi tree; it comes from the MT6781 4.19 donor tree and needs a handful
# of 4.19 -> 4.14 compatibility fixes, kept as a patch here.
MALI_DST="$DEST/drivers/misc/mediatek/gpu/gpu_mali/mali_valhall/mali-r32p1"
MALI_SRC_REL=drivers/gpu/mediatek/gpu_mali/mali_valhall/mali-r32p1

if [ -z "$DONOR" ]; then
    DONOR="$(dirname "$DEST")/kernel_ubports_mt6781"
    [ -e "$DONOR" ] || git clone --depth 1 "$DONOR_URL" "$DONOR"
fi

echo "==> installing Mali r32p1 from $DONOR"
mkdir -p "$(dirname "$MALI_DST")"
cp -a "$DONOR/$MALI_SRC_REL" "$MALI_DST"
( cd "$MALI_DST" && patch -p1 --no-backup-if-mismatch \
    < "$HERE/kernel/mali-r32p1-compat/0001-mali-r32p1-kernel-4.14-compat.patch" )

echo
echo "Kernel tree ready: $DEST"
echo "Build it with scripts/build-kernel.sh"
