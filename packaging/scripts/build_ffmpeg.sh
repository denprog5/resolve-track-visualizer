#!/usr/bin/env bash
set -euo pipefail

FFMPEG_VERSION=9.0.1

verify_dependencies() {
    local platform=$1
    local dependencies=$2
    local listed
    local unexpected

    case "$platform" in
        windows)
            listed=$(printf '%s\n' "$dependencies" | sed -n 's/.*DLL Name:[[:space:]]*//p' | tr -d '\r' | tr '[:upper:]' '[:lower:]')
            if [[ -z $listed ]]; then
                echo "Could not read Windows runtime dependencies" >&2
                exit 1
            fi
            unexpected=
            while IFS= read -r dependency; do
                case "$dependency" in
                    api-ms-win-*.dll|ext-ms-win-*.dll|advapi32.dll|bcrypt.dll|cfgmgr32.dll|comctl32.dll|comdlg32.dll|crypt32.dll|dwmapi.dll|gdi32.dll|imm32.dll|iphlpapi.dll|kernel32.dll|msvcrt.dll|ntdll.dll|ole32.dll|oleaut32.dll|powrprof.dll|psapi.dll|rpcrt4.dll|secur32.dll|setupapi.dll|shell32.dll|shlwapi.dll|ucrtbase.dll|user32.dll|version.dll|winmm.dll|winspool.drv|ws2_32.dll|wtsapi32.dll)
                        ;;
                    *)
                        unexpected="${unexpected}${unexpected:+$'\n'}${dependency}"
                        ;;
                esac
            done <<< "$listed"
            ;;
        macos)
            listed=$(printf '%s\n' "$dependencies" | sed -n '2,$s/^[[:space:]]*\([^[:space:]]*\).*/\1/p')
            if [[ -z $listed ]]; then
                echo "Could not read macOS runtime dependencies" >&2
                exit 1
            fi
            unexpected=
            while IFS= read -r dependency; do
                case "$dependency" in
                    /usr/lib/*|/System/Library/*|/Library/Apple/System/Library/*)
                        ;;
                    *)
                        unexpected="${unexpected}${unexpected:+$'\n'}${dependency}"
                        ;;
                esac
            done <<< "$listed"
            ;;
        linux)
            if printf '%s\n' "$dependencies" | grep -q 'not found'; then
                echo "Linux runtime dependency is missing:" >&2
                printf '%s\n' "$dependencies" >&2
                exit 1
            fi
            listed=$(
                printf '%s\n' "$dependencies" |
                    awk '
                        /=>/ { print $1; next }
                        $1 ~ /^linux-vdso/ { print $1; next }
                        $1 ~ /^\// { name=$1; sub(/^.*\//, "", name); print name }
                    '
            )
            if [[ -z $listed ]]; then
                echo "Could not read Linux runtime dependencies" >&2
                exit 1
            fi
            unexpected=
            while IFS= read -r dependency; do
                case "$dependency" in
                    ""|linux-vdso.so.1|ld-linux-x86-64.so.2|libanl.so.1|libatomic.so.1|libc.so.6|libcrypt.so.1|libdl.so.2|libgcc_s.so.1|libm.so.6|libnsl.so.1|libpthread.so.0|libresolv.so.2|librt.so.1|libutil.so.1)
                        ;;
                    *)
                        unexpected="${unexpected}${unexpected:+$'\n'}${dependency}"
                        ;;
                esac
            done <<< "$listed"
            ;;
        *)
            echo "Unsupported dependency platform: $platform" >&2
            exit 2
            ;;
    esac

    if [[ -n $unexpected ]]; then
        echo "Unexpected non-system runtime dependencies for $platform:" >&2
        printf '%s\n' "$unexpected" >&2
        exit 1
    fi
}

verify_prefix() {
    local prefix_dir=$1
    local suffix=
    if [[ ${MSYSTEM:-} == UCRT64 ]]; then
        suffix=.exe
    fi

    for program in ffmpeg ffprobe; do
        test -x "$prefix_dir/bin/$program$suffix"
    done
    test ! -e "$prefix_dir/bin/ffplay$suffix"
    if find "$prefix_dir" -type f \( -name '*.dll' -o -name '*.so' -o -name '*.dylib' \) -print -quit | grep -q .; then
        echo "The FFmpeg prefix unexpectedly contains a shared library" >&2
        exit 1
    fi

    for program in ffmpeg ffprobe; do
        local executable="$prefix_dir/bin/$program$suffix"
        local dependencies
        "$executable" -version
        if [[ ${MSYSTEM:-} == UCRT64 ]]; then
            dependencies=$(objdump -p "$executable" | sed -n '/DLL Name:/p')
            verify_dependencies windows "$dependencies"
        elif [[ $(uname -s) == Darwin ]]; then
            dependencies=$(otool -L "$executable")
            verify_dependencies macos "$dependencies"
        else
            dependencies=$(ldd "$executable")
            verify_dependencies linux "$dependencies"
        fi
        printf '%s\n' "$dependencies"
    done
}

if [[ $# -eq 2 && $1 == --verify-dependencies ]]; then
    verify_dependencies "$2" "$(cat)"
    exit 0
fi

if [[ $# -eq 2 && $1 == --verify-prefix ]]; then
    test -d "$2"
    verify_prefix "$(cd "$2" && pwd)"
    exit 0
fi

if [[ $# -ne 2 ]]; then
    echo "usage: $0 FFMPEG_SOURCE_DIR FFMPEG_PREFIX" >&2
    echo "       $0 --verify-prefix FFMPEG_PREFIX" >&2
    echo "       dependency-list | $0 --verify-dependencies PLATFORM" >&2
    exit 2
fi

ffmpeg_source_dir=$(cd "$1" && pwd)
prefix_parent=$(dirname "$2")
mkdir -p "$prefix_parent"
prefix_parent=$(cd "$prefix_parent" && pwd)
prefix_dir="$prefix_parent/$(basename "$2")"
ffmpeg_build_dir="$prefix_parent/ffmpeg-build"

if [[ ! -f "$ffmpeg_source_dir/VERSION" ]] || [[ $(tr -d '\r\n' < "$ffmpeg_source_dir/VERSION") != "$FFMPEG_VERSION" ]]; then
    echo "Expected the unmodified FFmpeg $FFMPEG_VERSION source tree at $ffmpeg_source_dir" >&2
    exit 1
fi
rm -rf "$ffmpeg_build_dir" "$prefix_dir"
mkdir -p "$ffmpeg_build_dir" "$prefix_dir"

jobs=2
if command -v getconf >/dev/null 2>&1; then
    jobs=$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)
elif command -v sysctl >/dev/null 2>&1; then
    jobs=$(sysctl -n hw.ncpu 2>/dev/null || echo 2)
fi

export LC_ALL=C
export TZ=UTC
export SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-1704067200}

cd "$ffmpeg_build_dir"
extra_configure_flags=()
if [[ ${MSYSTEM:-} == UCRT64 ]]; then
    extra_configure_flags+=(--extra-ldflags=-static)
fi
"$ffmpeg_source_dir/configure" \
    --prefix="$prefix_dir" \
    --enable-gpl \
    --enable-version3 \
    --enable-static \
    --disable-shared \
    --disable-autodetect \
    --disable-everything \
    --disable-network \
    --disable-ffplay \
    --disable-doc \
    --disable-debug \
    --disable-x86asm \
    --pkg-config=false \
    --enable-ffmpeg \
    --enable-ffprobe \
    --enable-decoder=aac,alac,flac,mp3float,opus,pcm_s16be,pcm_s16le,rawvideo,vorbis \
    --enable-encoder=pcm_s16le,prores_ks,qtrle \
    --enable-demuxer=aac,aiff,flac,mov,mp3,ogg,rawvideo,wav \
    --enable-muxer=mov,s16le \
    --enable-parser=aac,flac,mpegaudio,opus,vorbis \
    --enable-protocol=file,pipe \
    --enable-filter=abuffer,abuffersink,aformat,aresample,buffer,buffersink,format,scale \
    "${extra_configure_flags[@]}"

make -j"$jobs"
make install

# Release packaging needs only the statically linked command-line programs.
rm -rf "$prefix_dir/include" "$prefix_dir/lib" "$prefix_dir/share"
verify_prefix "$prefix_dir"
