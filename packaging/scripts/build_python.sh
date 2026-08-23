#!/usr/bin/env bash
set -euo pipefail

PYTHON_VERSION=3.12.13

if [[ $# -ne 2 ]]; then
    echo "usage: $0 PYTHON_SOURCE_DIR PYTHON_PREFIX" >&2
    exit 2
fi

python_source_dir=$(cd "$1" && pwd)
prefix_parent=$(dirname "$2")
mkdir -p "$prefix_parent"
prefix_parent=$(cd "$prefix_parent" && pwd)
prefix_dir="$prefix_parent/$(basename "$2")"
python_build_dir="$prefix_parent/python-build"

if ! grep -Fq "#define PY_VERSION \"$PYTHON_VERSION\"" "$python_source_dir/Include/patchlevel.h"; then
    echo "Expected the unmodified CPython $PYTHON_VERSION source tree at $python_source_dir" >&2
    exit 1
fi

rm -rf "$python_build_dir" "$prefix_dir"
mkdir -p "$python_build_dir" "$prefix_dir"

jobs=$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)
if (( jobs > 4 )); then
    jobs=4
fi

export LC_ALL=C
export TZ=UTC
export SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-1704067200}

cd "$python_build_dir"
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

runtime_library_path="$prefix_dir/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
LD_LIBRARY_PATH="$runtime_library_path" "$prefix_dir/bin/python" - <<'PY'
import platform
import sysconfig
import zlib

expected = "3.12.13"
actual = platform.python_version()
if actual != expected:
    raise SystemExit(f"Expected Python {expected}, found {actual}")
if sysconfig.get_config_var("Py_ENABLE_SHARED") != 1:
    raise SystemExit("CPython release runtime was not built with shared-library support")
print(f"Python {actual}, shared={sysconfig.get_config_var('Py_ENABLE_SHARED')}, zlib={zlib.ZLIB_VERSION}")
PY
test -f "$prefix_dir/lib/libpython3.12.so.1.0"
