# AppImage

The package is `TuxCue-0.4.4-x86_64.AppImage`. It contains the application, browser interface, logo, Python, audio libraries, FFmpeg/ffprobe, pactl, and tray/shortcut support. **It contains no audio clips or user collections.**

## Requirements and launch

Use an x86_64 Linux desktop with glibc, a running PipeWire/PulseAudio-compatible service, a browser, and `xdg-open`. Global shortcuts need X11. A StatusNotifier/Ayatana-compatible tray or X11 tray is needed for the tray icon.

The build baseline is Ubuntu 22.04. Debian 13/Cinnamon/X11 is the tested desktop; other distributions are not certified. Automated package checks use extract-and-run; normal FUSE-mounted launch still needs manual verification.

```bash
chmod +x TuxCue-0.4.4-x86_64.AppImage
./TuxCue-0.4.4-x86_64.AppImage
```

If mounting is unavailable, use:

```bash
./TuxCue-0.4.4-x86_64.AppImage --appimage-extract-and-run
```

Optional application arguments include `--no-browser`, `--open-browser`, `--no-tray`, `--port 8770`, and `--data-dir /absolute/test/folder`. The last uses a separate temporary collection selection and disables changing the saved location in Settings.

Verify downloaded artifacts using their matching `SHA256SUMS` file:

```bash
sha256sum -c SHA256SUMS
```

The desktop interface is normally at <http://127.0.0.1:8765>. The optional phone listener defaults to port 8766. Choose different ports if running isolated test instances.

## Updates and storage

Store the new AppImage wherever convenient and start it. A newer version requests a graceful shutdown of the older instance using the same collection and port, waits for cleanup, then starts. If the virtual microphone was connected, it reconnects. Playback is briefly interrupted; an interrupted clip is not replayed. The same or an older version reuses the existing instance.

The default collection is `~/TuxCue`; its location is configurable in Settings. Updating or deleting the AppImage does not delete the collection. Keep backups of the whole collection. Other programs on the same machine are not automatically stopped.

## Build locally

Install Docker, Python 3, Node.js 22.13+, and pnpm 11.19.0. From the project root:

```bash
./scripts/build_appimage.sh
```

The script makes a temporary snapshot of the selected source and rebuilds the frontend from its frozen lockfile, collects its notices, checks public source selection, and builds in an Ubuntu container. FFmpeg is compiled from the verified 8.1.2 source with audio-focused configuration. No system-wide audio configuration is changed by building.

Docker runs the Python tests, freezes the application with PyInstaller, checks its components, collects licenses and exact third-party sources, and rejects audio/collection files in the AppDir. The output includes the AppImage, checksums, component inventory, and both source archives. Network access and several GB of free space are required, especially for corresponding sources.

Generated files stay outside the checkout. The default output folder is `${XDG_CACHE_HOME:-$HOME/.cache}/tuxcue/releases/0.4.4`. To choose a folder:

```bash
TUXCUE_OUTPUT_DIR="$HOME/TuxCue-builds/0.4.4" ./scripts/build_appimage.sh
```

The folder must be outside the source checkout. Docker retains its normal build cache, and pnpm uses its external package store. Temporary build files are removed when the script exits. `packaging/AppRun` is the internal AppImage entry point, not a separate user launcher.

For a future GitHub Actions packaging job, install the same prerequisites and invoke this script with `TUXCUE_OUTPUT_DIR="$RUNNER_TEMP/tuxcue-release"`, then collect files from that folder as workflow artifacts. The current workflow only checks source and browser builds; it does not build or publish releases.

The Ubuntu image is pinned by digest; Python/npm dependencies and downloaded packaging tools have recorded versions and hashes. Ubuntu packages still resolve from signed repository metadata at build time. Their actual binary/source versions are recorded, so byte-identical rebuilds are **not** claimed. A changed upstream runtime download fails its pinned hash check rather than silently changing the runtime.

Source archives and release assets must be kept together. See [RELEASING.md](RELEASING.md) and [third-party notices](../THIRD_PARTY_NOTICES.md).
