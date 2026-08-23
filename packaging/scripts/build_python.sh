#!/usr/bin/env bash
set -euo pipefail

PYTHON_VERSION=3.12.13
LIBFFI_VERSION=3.4.8

if [[ $# -ne 3 ]]; then
    echo "usage: $0 PYTHON_SOURCE_DIR LIBFFI_SOURCE_DIR PYTHON_PREFIX" >&2
    exit 2
fi

python_source_dir=$(cd "$1" && pwd)
libffi_source_dir=$(cd "$2" && pwd)
prefix_parent=$(dirname "$3")
mkdir -p "$prefix_parent"
prefix_parent=$(cd "$prefix_parent" && pwd)
prefix_dir="$prefix_parent/$(basename "$3")"
python_build_dir="$prefix_parent/python-build"
libffi_build_dir="$prefix_parent/libffi-build"
libffi_prefix_dir="$prefix_parent/libffi-prefix"

if ! grep -Eq "^#define[[:space:]]+PY_VERSION[[:space:]]+\"$PYTHON_VERSION\"$" \
    "$python_source_dir/Include/patchlevel.h"; then
    echo "Expected CPython $PYTHON_VERSION source at $python_source_dir" >&2
    exit 1
fi
if ! grep -Fq "PACKAGE_VERSION='$LIBFFI_VERSION'" "$libffi_source_dir/configure"; then
    echo "Expected libffi $LIBFFI_VERSION source at $libffi_source_dir" >&2
    exit 1
fi

rm -rf "$python_build_dir" "$libffi_build_dir" "$libffi_prefix_dir" "$prefix_dir"
mkdir -p "$python_build_dir" "$libffi_build_dir" "$libffi_prefix_dir" "$prefix_dir"

jobs=$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)
if (( jobs > 4 )); then
    jobs=4
fi

export LC_ALL=C
export TZ=UTC
export SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-1704067200}

cd "$libffi_build_dir"
CFLAGS="-fPIC" "$libffi_source_dir/configure" \
    --prefix="$libffi_prefix_dir" \
    --disable-shared \
    --enable-static
make -j"$jobs"
make install

libffi_header=$(find "$libffi_prefix_dir" -type f -name ffi.h -print -quit)
libffi_library=$(find "$libffi_prefix_dir" -type f -name libffi.a -print -quit)
if [[ -z "$libffi_header" || -z "$libffi_library" ]]; then
    echo "The static libffi build did not install ffi.h and libffi.a" >&2
    exit 1
fi

cd "$python_build_dir"
LIBFFI_CFLAGS="-I$(dirname "$libffi_header")" \
LIBFFI_LIBS="$libffi_library" \
    "$python_source_dir/configure" \
    --prefix="$prefix_dir" \
    --enable-shared \
    --without-static-libpython \
    --without-ensurepip
make -j"$jobs"
make install

ln -sf python3.12 "$prefix_dir/bin/python"
mkdir -p "$prefix_dir/lib/python3.12"
cp "$python_source_dir/LICENSE" "$prefix_dir/lib/python3.12/LICENSE.txt"
cp "$libffi_source_dir/LICENSE" "$prefix_dir/lib/python3.12/libffi-LICENSE.txt"

runtime_library_path="$prefix_dir/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
LD_LIBRARY_PATH="$runtime_library_path" "$prefix_dir/bin/python" - <<'PY'
import platform
import sysconfig
import zlib
import ctypes

expected = "3.12.13"
actual = platform.python_version()
if actual != expected:
    raise SystemExit(f"Expected Python {expected}, found {actual}")
if sysconfig.get_config_var("Py_ENABLE_SHARED") != 1:
    raise SystemExit("CPython release runtime was not built with shared-library support")
print(f"Python {actual}, shared={sysconfig.get_config_var('Py_ENABLE_SHARED')}, zlib={zlib.ZLIB_VERSION}")
PY
test -f "$prefix_dir/lib/libpython3.12.so.1.0"
ctypes_extension=$(find "$prefix_dir/lib/python3.12/lib-dynload" -type f -name '_ctypes*.so' -print -quit)
if [[ -z "$ctypes_extension" ]]; then
    echo "CPython did not install its required _ctypes extension" >&2
    exit 1
fi
if ldd "$ctypes_extension" | grep -Fq libffi; then
    echo "The CPython _ctypes extension must link the verified libffi build statically" >&2
    ldd "$ctypes_extension" >&2
    exit 1
fi
