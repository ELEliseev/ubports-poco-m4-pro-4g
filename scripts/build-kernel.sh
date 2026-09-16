#!/bin/bash
# Build the fleur kernel.
#
# Four things here are mandatory; each was found the hard way:
#
#   clang-r383902                 anything else boots for two seconds and hangs
#                                 without printing a word. The vendor's own
#                                 compiler is named in the stock kernel banner:
#                                 "Android (6443078 based on r383902) clang 11.0.2".
#   CROSS_COMPILE=aarch64-...     without it clang reports that
#                                 -fstack-protector-strong is unsupported. That
#                                 message is a lie: the real problem is the GNU
#                                 assembler shipped with GCC 4.9, which does not
#                                 know cortex-a55.
#   LD=ld.lld                     GNU ld fails linking vmlinux with
#                                 "relocation truncated to fit: R_AARCH64_LDST64_ABS_LO12_NC".
#   KCFLAGS=-fno-builtin-stpcpy   clang folds strcpy+strlen into stpcpy, which
#                                 the kernel does not provide.
set -u

HERE="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${KERNEL_SRC:-$HERE/../kernel-src/fleur-official}"
OBJ="${KERNEL_OBJ:-$HERE/../kernel-src/KERNEL_OBJ}"
TOOLCHAIN="${CLANG_PATH:-$HOME/toolchains/clang-r383902/bin}"

[ -d "$SRC" ] || { echo "no kernel tree at $SRC; run scripts/setup-kernel-tree.sh" >&2; exit 1; }
[ -x "$TOOLCHAIN/clang" ] || { echo "no clang-r383902 at $TOOLCHAIN; see docs/porting-guide.md" >&2; exit 1; }

export PATH="$TOOLCHAIN:$PATH"
mkdir -p "$OBJ"

MAKE_ARGS=(-C "$SRC" O="$OBJ" ARCH=arm64 CC=clang
           CROSS_COMPILE=aarch64-linux-gnu- LD=ld.lld
           KCFLAGS=-fno-builtin-stpcpy)

if [ "${1:-}" = "-c" ]; then
    make "${MAKE_ARGS[@]}" fleur_defconfig halium.config || exit 1
    shift
fi

make "${MAKE_ARGS[@]}" -j"$(nproc)" Image.gz-dtb 2>&1 | tail -400
exit "${PIPESTATUS[0]}"
