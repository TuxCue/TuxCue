# TuxCue

<img src="frontend/public/tuxcue-logo.png" width="128" alt="TuxCue penguin wearing lime headphones">

A Linux soundboard for playing your own clips in Discord and other voice chats. Hear a private preview, or send a sound together with your microphone through **TuxCue Microphone**. An optional phone controller lets you trigger sounds from your browser over the same trusted network.

TuxCue ships with **no audio files or built-in sound library**. You import your own sounds.

## Features

- Configurable sound tiles, rows, columns, colors, labels, and clip volumes.
- Global keyboard shortcuts on X11, with conflict reporting.
- Saved sound sets, import/export, and a shared library with original filenames.
- Trim a selection, adjust gain, add fades, and save a new clip while keeping the original.
- Separate microphone, listening-device, and broadcast controls.
- System-tray controls to open, stop, restart, or quit.
- Optional paired-phone control with separate portrait and landscape layouts.
- Graceful handover when a newer version starts, preserving the collection and settings.

## Status and supported environment

TuxCue is an early **0.x** project. Version **0.4.4** is being prepared as the first public release.

Tested environment: **Debian 13, Cinnamon, X11, and PipeWire's PulseAudio compatibility service**. The x86_64 AppImage uses an Ubuntu 22.04 build baseline. Other distributions, native PulseAudio, and normal FUSE-mounted execution still need compatibility testing. Global shortcuts currently require X11; Wayland global shortcuts are not implemented.

## Install and start

The supported package format is an **x86_64 AppImage**. Release preparation does not mean a download has already been published. When an official release is available, obtain it from [TuxCue releases](https://github.com/TuxCue/TuxCue/releases).

With the AppImage in your current folder:

```bash
chmod +x TuxCue-0.4.4-x86_64.AppImage
./TuxCue-0.4.4-x86_64.AppImage
```

If FUSE mounting is unavailable:

```bash
./TuxCue-0.4.4-x86_64.AppImage --appimage-extract-and-run
```

The app opens your default browser. Its desktop interface is also at <http://127.0.0.1:8765>. Closing the browser leaves TuxCue running; use **Quit TuxCue** in the tray or the interface to stop it. See [AppImage details](docs/APPIMAGE.md) for requirements, checksums, and rebuilding.

## First use

1. Choose **Import sounds** and select your audio files.
2. Select your microphone and headphones/speakers. Use **Preview only** to listen privately.
3. Choose **Connect virtual microphone**.
4. In Discord, choose **TuxCue Microphone** as the input device. If noise suppression cuts off clips, adjust Discord's processing settings. With push-to-talk, hold the talk key while triggering a sound.
5. Use a tile's pencil button to assign its sound and shortcut. Open **Settings** to change the grid, collection folder, or remote control.

For phone control, enable **Remote control**, open the displayed address on the phone, and pair using the QR code or temporary code. The phone and PC must share a trusted network. Phone sounds play on the PC. See [phone setup and network limits](docs/REMOTE.md).

Supported import extensions: MP3, WAV, FLAC, OGG, OPUS, M4A, AAC, AIFF, and WMA. Files must be at most 100 MB and 10 minutes long; individual codec support depends on FFmpeg.

## Your sounds and privacy

The default collection folder is `~/TuxCue`. Change it in **Settings → Storage**. A move verifies the copied data and retains the previous collection as a backup. Sound sets, edited clips, playback caches, preferences, and paired-phone records belong to this collection. The location preference is in `$XDG_CONFIG_HOME/tuxcue/storage.json`, or `~/.config/tuxcue/storage.json` by default.

Original filenames are preserved, with a suffix added for collisions. Playback WAVs are cached in `library/.cache/`. Trash is reversible; it does not immediately erase the underlying audio. Back up the whole collection folder.

There is no cloud account or built-in telemetry. Phone control is off by default and uses **unencrypted HTTP on your trusted local network**. Pairing is access control, not encryption. Do not expose its port to the internet. The desktop API trusts local processes; this is not a security boundary between users of a shared PC. Compatible browsers may expose the app's optional sound-list/play/stop tools to their assistant integration.

Users are responsible for ensuring they have the necessary rights to any audio or other content they import into TuxCue. Exported sets contain their assigned audio, so share them accordingly.

## Build the AppImage

The repository contains application source, tests, documentation, and build recipes. Users launch the resulting AppImage directly; no startup script or source installation is required.

On an x86_64 Linux build machine, install Docker, Python 3.10+, Node.js 22.13+, and pnpm 11.19.0, then run:

```bash
./scripts/build_appimage.sh
```

The same command builds locally and in GitHub Actions on the project's self-hosted runner. Pushing a reviewed version tag builds and publishes the AppImage and corresponding sources; see [the release procedure](docs/RELEASING.md). The script builds a temporary source snapshot and writes release files outside the checkout, by default to `${XDG_CACHE_HOME:-$HOME/.cache}/tuxcue/releases/0.4.4`. Set `TUXCUE_OUTPUT_DIR` to choose another external folder. No generated dependencies, browser assets, AppImages, or source archives belong in Git.

See [build details](docs/APPIMAGE.md) and [contribution/testing instructions](CONTRIBUTING.md).

## Feedback and contributions

Report reproducible bugs and suggest features through [GitHub issues](https://github.com/TuxCue/TuxCue/issues). Include your TuxCue version, distribution, desktop/session type, and steps to reproduce. Remove private paths, pairing codes, and personal content from logs and screenshots.

For vulnerabilities, follow [SECURITY.md](SECURITY.md). For pull requests, read [CONTRIBUTING.md](CONTRIBUTING.md). Changes are recorded in [CHANGELOG.md](CHANGELOG.md).

## License, development, and project identity

TuxCue's source is licensed under **GPL-3.0-or-later**. See [LICENSE](LICENSE) and [third-party notices](THIRD_PARTY_NOTICES.md). It is provided without warranty. Third-party components retain their own licenses.

TuxCue was developed with extensive assistance from generative AI. Product direction, feature decisions, testing, and maintenance are handled by the TuxCue project.

The name and logo identify the project; [TRADEMARKS.md](TRADEMARKS.md) explains appropriate attribution and avoiding misleading official branding. TuxCue is independent and is not affiliated with or endorsed by the Linux Foundation. Linux is a registered trademark of Linus Torvalds.
