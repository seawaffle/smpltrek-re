#!/usr/bin/env bash
# Builds a TI C6x-only GNU binutils (objdump with the tic6x target) into ./tools/tic6x.
# Needs curl, tar, gcc, make. No sudo. Takes a few minutes.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TOOLS="$(dirname "$HERE")"   # outputs go in tools/, where the analysis and emulator look
WORK="$TOOLS/binutils-build"
PREFIX="$TOOLS/tic6x"
mkdir -p "$WORK" && cd "$WORK"
[ -f binutils-2.42.tar.xz ] || curl -sSL -o binutils-2.42.tar.xz https://ftp.gnu.org/gnu/binutils/binutils-2.42.tar.xz
[ -d binutils-2.42 ] || tar xf binutils-2.42.tar.xz
# Local fix (tools/toolchain/patches): the compact-instruction RS bit was applied to 5-bit and 1-bit register
# fields, so objdump printed compact MV and CMPGT/CMPLT with registers 16 too high in RS=1 packets.
PATCH="$HERE/patches/binutils-2.42-tic6x-compact-rs.patch"
if ! patch -p1 -R -s -f --dry-run -d binutils-2.42 < "$PATCH" > /dev/null 2>&1; then
  patch -p1 -s -d binutils-2.42 < "$PATCH"
fi
mkdir -p build && cd build
../binutils-2.42/configure --target=tic6x-elf --prefix="$PREFIX" \
  --disable-gdb --disable-gold --disable-gprof \
  --disable-gprofng --disable-sim --disable-werror --disable-nls > configure.log 2>&1
make -j"$(nproc)" MAKEINFO=true > make.log 2>&1
make install MAKEINFO=true > install.log 2>&1
echo "BUILD_OK: $PREFIX/bin/tic6x-elf-objdump"
