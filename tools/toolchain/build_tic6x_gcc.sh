#!/usr/bin/env bash
# Builds a bare-metal GCC for TI C6x (tic6x-elf, C only, with libgcc) into ./tools/tic6x,
# next to the binutils from build_tic6x_binutils.sh (run that first: GCC uses its as and ld).
# Needs curl, tar, gcc, g++, make, flex, bison. No sudo: GMP, MPFR, MPC and ISL are fetched and
# built in-tree by GCC's own download_prerequisites. Takes 10-30 minutes.
#
# Why GCC 13: a 2024 report (GCC bug 114910) shows a GCC 14 tic6x cross build failing through
# crosstool-ng with newlib; 13.3.0 is the last release before that. No libc is built here
# (--without-headers --with-newlib is GCC's stage-1 recipe for libgcc without a libc).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TOOLS="$(dirname "$HERE")"   # outputs go in tools/, where the analysis and emulator look
WORK="$TOOLS/gcc-build"
PREFIX="$TOOLS/tic6x"
VER="${GCC_VERSION:-13.3.0}"
[ -x "$PREFIX/bin/tic6x-elf-as" ] || { echo "run tools/toolchain/build_tic6x_binutils.sh first" >&2; exit 1; }
mkdir -p "$WORK" && cd "$WORK"
[ -f "gcc-$VER.tar.xz" ] || curl -sSL -o "gcc-$VER.tar.xz" "https://ftp.gnu.org/gnu/gcc/gcc-$VER/gcc-$VER.tar.xz"
[ -d "gcc-$VER" ] || tar xf "gcc-$VER.tar.xz"
if [ ! -d "gcc-$VER/gmp" ]; then
  (cd "gcc-$VER" && ./contrib/download_prerequisites > ../prerequisites.log 2>&1)
fi
mkdir -p build && cd build
if [ ! -f Makefile ]; then
  "../gcc-$VER/configure" --target=tic6x-elf --prefix="$PREFIX" \
    --enable-languages=c --without-headers --with-newlib \
    --disable-shared --disable-threads --disable-nls --disable-werror \
    --disable-libssp --disable-libquadmath --disable-libgomp --disable-libatomic \
    --disable-decimal-float --disable-libstdcxx \
    --with-gnu-as --with-gnu-ld --with-as="$PREFIX/bin/tic6x-elf-as" --with-ld="$PREFIX/bin/tic6x-elf-ld" \
    > configure.log 2>&1
fi
make -j"$(nproc)" MAKEINFO=true all-gcc > make-gcc.log 2>&1
make install-gcc MAKEINFO=true > install-gcc.log 2>&1
make -j"$(nproc)" MAKEINFO=true all-target-libgcc > make-libgcc.log 2>&1
make install-target-libgcc MAKEINFO=true > install-libgcc.log 2>&1
echo "BUILD_OK: $PREFIX/bin/tic6x-elf-gcc"
"$PREFIX/bin/tic6x-elf-gcc" --version | head -1
