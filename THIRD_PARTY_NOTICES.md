# Third-Party Notices

Resolve Track Visualizer depends on and may bundle third-party software. Copyright remains with the respective authors.

| Component | Use | License |
| --- | --- | --- |
| CPython 3.12 (3.12.10 on Windows; 3.12.13 on Linux) | Runtime bundled by PyInstaller | Python Software Foundation License 2.0 |
| libffi 3.4.4 (Windows); 3.4.8 (Linux) | CPython `_ctypes` runtime dependency | MIT |
| OpenSSL 3.0.16 (Windows) | CPython `_ssl` and `_hashlib` runtime dependency | Apache License 2.0 |
| Mutagen | Audio metadata parsing | GPL-2.0-or-later |
| Pillow 12.2.0 and its wheel-bundled native libraries | Image processing | See the exact wheel-provided license and copyright notices |
| PyInstaller | Release build tool and bundled bootloader | GPL-2.0-or-later with the PyInstaller bootloader exception |
| FFmpeg 9.0.1 and FFprobe | Media probing and legacy rendering | GPL-3.0-or-later for the configured release build |

Development-only Lua parsing uses `luaparser` under the MIT license.

Project links:

- CPython: <https://www.python.org/psf/license/>
- Windows libffi 3.4.4 source: <https://github.com/python/cpython-source-deps/archive/refs/tags/libffi-3.4.4.tar.gz> (SHA-256 `9d802681adfea27d84cae0487a785fb9caa925bdad44c401b364c59ab2b8edda`)
- Linux libffi 3.4.8 source: <https://github.com/libffi/libffi/releases/download/v3.4.8/libffi-3.4.8.tar.gz> (SHA-256 `bc9842a18898bfacb0ed1252c4febcc7e78fa139fd27fdc7a3e30d9d9356119b`)
- Windows OpenSSL 3.0.16 source: <https://github.com/python/cpython-source-deps/archive/refs/tags/openssl-3.0.16.tar.gz> (SHA-256 `6bb739ecddbd2cfb6d255eb5898437a9b5739277dee931338d3275bac5d96ba2`)
- Mutagen 1.47.0 source: <https://files.pythonhosted.org/packages/81/e6/64bc71b74eef4b68e61eb921dcf72dabd9e4ec4af1e11891bbd312ccbb77/mutagen-1.47.0.tar.gz> (SHA-256 `719fadef0a978c31b4cf3c956261b3c58b6948b32023078a2117b1de09f0fc99`)
- Pillow 12.2.0: <https://github.com/python-pillow/Pillow>
- PyInstaller: <https://pyinstaller.org/en/stable/license.html>
- FFmpeg source: <https://ffmpeg.org/releases/ffmpeg-9.0.1.tar.xz>
- FFmpeg legal information: <https://ffmpeg.org/legal.html>
- luaparser: <https://github.com/boolangery/py-lua-parser>

Release FFmpeg and FFprobe binaries are built from the unmodified official FFmpeg 9.0.1 archive with SHA-256 `cf38e0e28c7e5605942c4a77755349b0145804a397af37eb1fb4c77cb237f635`. The build enables GPL version-3 terms, uses `--disable-everything` followed by the application-specific component allowlist, does not enable nonfree components or external libraries, and disables network support. FFmpeg libraries are linked statically into the programs; operating-system runtime libraries remain platform dependencies.

The assembled release bundle includes the exact FFmpeg, Mutagen, CPython, and target-specific CPython dependency source archives under `source/`. Each Windows GitHub Release attaches the same archives next to the installer; the Linux canary bundle stays private and unpublished. Windows source artifacts include the libffi 3.4.4 and OpenSSL 3.0.16 `python/cpython-source-deps` tag archives identified by the official Python 3.12.10 installer SBOM; Linux source artifacts include libffi 3.4.8. Each package also contains the applicable licenses and source records. FFmpeg packages include complete configuration/license output and the exact build recipe. The installed CPython PSF license is staged as `licenses/Python-LICENSE.txt`. Windows packages include `licenses/libffi-LICENSE.txt` and `licenses/OpenSSL-LICENSE.txt`; Linux packages include `licenses/libffi-LICENSE.txt`. The exact Pillow wheel notice is staged under `licenses/Pillow/pillow-12.2.0.dist-info/licenses/LICENSE`; it contains Pillow's MIT-CMU notice and the notices shipped for Pillow's bundled native libraries. Release construction fails if any required CPython, libffi, OpenSSL, or Pillow notice is absent or invalid. This summary does not replace those license texts.
