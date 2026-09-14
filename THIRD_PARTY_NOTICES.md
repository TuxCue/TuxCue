# Third-party components

TuxCue's own source is GPL-3.0-or-later. Third-party components retain their copyright notices and licenses; the project license does not replace them.

## Browser interface

React, React DOM, and scheduler use the MIT license. Lucide uses the ISC license and includes attribution to the Feather project (MIT). TypeScript uses Apache-2.0. Vite, Rollup, esbuild, and their helpers have their own MIT, ISC, BSD, Apache, and included component notices.

The build collects complete resolved package notices into the AppImage's `usr/bin/_internal/licenses/javascript/`. This includes the full Lucide/Feather attribution and React notices. The generated `components.json` records names, versions, and reported licenses.

## Python and native components

FastAPI and Pydantic use MIT; Starlette and Uvicorn use BSD-3-Clause; python-multipart uses Apache-2.0; QRCode carries BSD-3-Clause and inherited MIT notices. Supporting Python packages retain their own MIT/BSD/PSF/Apache/Unicode terms. PyInstaller's bootloader has the GPL exception described in its COPYING.txt; some PyInstaller files use Apache-2.0.

The Rust dependency records preserve the full pydantic-core Cargo lockfile, including development and other-platform dependencies. Their notices and exact crate sources are included conservatively; the inventory is not a claim that every listed dependency is linked into the Linux application.

Python uses the PSF license and included third-party terms. PyGObject, python-xlib, GStreamer, GTK, PulseAudio utilities, Ayatana libraries, and their dependencies carry LGPL/GPL and other component-specific notices. The release build maps actual packaged inputs to Ubuntu source package versions and includes their copyright files plus the complete common license texts.

## FFmpeg

The release recipe builds FFmpeg 8.1.2 from the upstream signed source archive, with no network protocols or external video-codec libraries. It includes LAME for MP3 encoding used by synthetic tests. This configuration does not enable GPL or nonfree FFmpeg options; the applicable FFmpeg and LAME notices remain in the package. Software licenses do not establish that every codec is patent-free in every jurisdiction.

Upstream: https://ffmpeg.org/legal.html

## AppImage runtime

The runtime is pinned by source commit and binary SHA-256 in `packaging/inputs.json`. Its MIT license and notices for statically included musl, libfuse, squashfuse, zstd, zlib, and mimalloc are preserved in `licenses/appimage-runtime/`. The separate source bundle includes runtime source, its libfuse patch, and the pinned libfuse and squashfuse source archives. The upstream prebuilt runtime does not provide an exact version inventory for its Alpine permissive libraries; `runtime-notices.json` records checksum-pinned upstream notice sources, not a claim about those binary versions.

## Source and redistribution

Each prepared release includes an application source archive and a third-party source archive alongside its AppImage. `COMPONENTS.json` maps dependency versions to sources; the third-party archive includes upstream archives, distro source packages and patches, recorded FFmpeg configuration, packaging scripts, and checksums.

Distributors must provide the corresponding source and preserve required notices under each applicable license. When publishing a binary, make the matching source archives available next to it. The files in this repository alone do not replace the source obligations for bundled third-party binaries. See [release procedure](docs/RELEASING.md).

The AppImage's full notices are under `usr/bin/_internal/licenses/` after `--appimage-extract`. They are also available from the desktop interface's license/notices links. TuxCue includes no sound library; users import their own content.
