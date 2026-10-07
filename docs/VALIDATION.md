# Validation

## Historical local validation

Before public-release preparation, version 0.4.3 passed 42 Python tests on Debian 13/Python 3.13 and in the Ubuntu 22.04/Python 3.10 packaging environment. Desktop checks covered audio routing with synthetic devices, preview isolation, editing, collection moves, phone pairing, tray registration, browser-launch environment restoration, and older-version handover.

Manual user testing confirmed Discord microphone-plus-clip routing, private preview, phone control, and phone grid preferences. Those reports establish the tested setup, not support for every distribution or browser.

## Release candidate

Local preparation checks on 2026-09-14:

- 44 Python tests passed on Debian 13/Python 3.13 and Ubuntu 22.04/Python 3.10.
- The packaging environment passed `python -m pip check` after installing the Cairo binding required by PyGObject.
- Frozen pnpm installation, strict TypeScript compilation, and Vite production build passed.
- Source selection and Git whitespace checks passed. No audio, personal collection, private paths, or obvious credentials were selected. The logo's AI provenance metadata is retained; its metadata scan found no local paths or credential patterns.
- AppDir checks passed: no audio files or collection data, required license notices present, FFmpeg 8.1.2, and working audio/tray/QR components.
- Native synthetic-audio checks passed for microphone mixing, private preview, overlapping clips, MP3 decoding, live collection moves, output removal/recovery, and resource cleanup. Default audio devices were preserved.
- X11 checks passed for shortcut registration, conflicts, editor suspension/resume, disabling, and cleanup. No key events were injected into other applications.
- The AppImage passed extract-and-run checks for import, edit/fades, original filenames, routing, preview isolation, collection moves, restart, phone pairing/playback/revocation, and desktop/phone license endpoints.
- The packaged tray registered with the desktop and exposed all four controls. Activating Open TuxCue through its D-Bus menu called the browser launcher with the expected URL and restored host environment. Browser startup checks also passed.
- An isolated 0.4.2 → 0.4.4 handover preserved collection data, microphone routing, and phone pairing. Same-version reuse and three simultaneous launches passed.
- Browser inspection confirmed the desktop footer and phone legal link/layout at 390×844 portrait and 844×390 landscape, with no phone browser console errors. This is browser viewport testing, not physical-device certification.
- The documented build command produced the AppImage and source archives outside the checkout. The output-directory guard rejected an in-repository destination. Generated dependencies, caches, and build files were removed from the checkout.

Normal FUSE execution could not be tested in the execution environment because `/dev/fuse` is unavailable. The AppImage's extract-and-run mode was used for the packaged tests. GitHub Actions and tag-triggered release publishing still need their first live run.

Run commands from [CONTRIBUTING.md](../CONTRIBUTING.md). Use temporary collections and generated tones; do not upload personal collections or unredacted logs. See THIRD_PARTY_NOTICES.md for the upstream runtime's version-inventory limitation.

## 0.4.9 source preparation

Local source checks on 2026-10-07:

- 53 Python tests passed in the Ubuntu 22.04/Python 3.10 packaging environment, including precise audio removal and fixed-runtime/checksum regression checks.
- Synthetic stereo audio checks verified exact retained samples when removing a middle, beginning, or ending section, unchanged originals, private result previews, fades, and limiter duration. Invalid removals were rejected.
- Strict TypeScript compilation and both Vite production builds passed using the frozen frontend lockfile.
- Browser checks with synthetic data verified the removal action, empty-result guidance, keyboard handle movement, result length, preview/save requests, and a narrow layout without horizontal overflow. No browser warnings or errors were recorded.

- The full local AppImage build passed license/source collection and the no-audio AppDir check, producing the AppImage, both source archives, component inventory, and checksums outside the checkout.
- Upstream runtime release `20251108` was verified against its SHA-256 and upstream GPG signature (key fingerprint `570C77ACEA40C0F1B758902CBF96CCA56490F695`). Its source archive matches the embedded runtime commit `dd6cebe`.
- The final v0.4.9 AppImage passed its extract-and-run component self-check without starting the application or accessing a personal collection.

Packaged desktop/Discord use and normal FUSE mounting remain unverified for v0.4.9.

## Remaining manual compatibility checks

- Normal FUSE-mounted AppImage launch through a desktop file manager.
- The tray's Open TuxCue action with the user's actual browser (automated checks use a recording browser launcher).
- Shortcut activation while a game has focus.
- Long-running Discord/game sessions and physical phone rotation.
- Other distributions, desktops, and native PulseAudio.
- Wayland global shortcuts are not implemented.
