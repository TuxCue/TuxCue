# Contributing to TuxCue

Bug reports, documentation improvements, and focused fixes are welcome. Open an issue before substantial changes so the maintainer can discuss the scope. Keep changes small and preserve existing audio routing, saved collections, and upgrade behavior.

## Development

The frontend uses React/TypeScript/Vite; Python provides the local service, audio routing, and tray. Use the pinned dependency files. The supported application launch method is the AppImage; build it with `./scripts/build_appimage.sh` as described in [APPIMAGE.md](docs/APPIMAGE.md). That command runs the Python suite in the packaging container and builds both browser interfaces in a temporary directory.

For a faster source-only test cycle, install the distribution's Python 3.10+, venv, PyGObject/GStreamer, Xlib, FFmpeg, and PulseAudio utilities. On Debian, the native packages are `python3-venv python3-gi python3-cairo python3-xlib gir1.2-gstreamer-1.0 gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-pulseaudio ffmpeg pulseaudio-utils`. Keep the test environment outside the checkout:

```bash
export PYTHONDONTWRITEBYTECODE=1
export TUXCUE_TEST_ENV="${XDG_CACHE_HOME:-$HOME/.cache}/tuxcue/test-venv"
python3 -m venv --system-site-packages "$TUXCUE_TEST_ENV"
"$TUXCUE_TEST_ENV/bin/python" -m pip install --upgrade --no-deps --require-hashes -r requirements-build.lock
"$TUXCUE_TEST_ENV/bin/python" -m pip install --ignore-installed --require-hashes -r requirements.lock
"$TUXCUE_TEST_ENV/bin/python" -m unittest discover -s tests -v
python3 scripts/check_release.py
```

The Python tests use temporary collections and generated audio. They need local socket access, but do not need your sound collection or a physical microphone. The GitHub Actions check workflow runs equivalent checks without publishing anything.

On a desktop, optional integration checks are:

```bash
export TUXCUE_APPIMAGE="${XDG_CACHE_HOME:-$HOME/.cache}/tuxcue/releases/0.4.6/TuxCue-0.4.6-x86_64.AppImage"
"$TUXCUE_TEST_ENV/bin/python" scripts/check_audio.py
"$TUXCUE_TEST_ENV/bin/python" scripts/check_hotkeys.py
"$TUXCUE_TEST_ENV/bin/python" scripts/check_appimage.py
"$TUXCUE_TEST_ENV/bin/python" scripts/check_browser_launch.py
"$TUXCUE_TEST_ENV/bin/python" scripts/check_tray.py
# Optional: provide an existing historical AppImage outside the checkout.
export TUXCUE_OLD_APPIMAGE="$HOME/TuxCue-builds/0.4.2/TuxCue-0.4.2-x86_64.AppImage"
"$TUXCUE_TEST_ENV/bin/python" scripts/check_upgrade.py
```

Native checks create temporary synthetic audio devices and clean up their own resources. Run them in your desktop session. The tray check requires a StatusNotifier-compatible tray such as Cinnamon's. Never commit AppImages, virtual environments, node_modules, generated frontend files, test output, or personal collections.

Explain what changed, why, and what you tested in the pull request. Mention collection-format, configuration, or compatibility changes explicitly. Do not reformat or refactor unrelated code.

## Content and licensing

TuxCue ships no sounds. Do not contribute movie clips, game audio, music, memes, private collections, or screenshots containing personal data. Generate test tones in tests instead.

Submit only contributions you are entitled to provide. Contributions are offered under GPL-3.0-or-later, with third-party provenance and applicable notices identified. Disclose substantial AI assistance and review its output; AI assistance does not remove the need for permission to contribute third-party material.

Contributors retain whatever rights they hold. No copyright assignment or Contributor License Agreement is required. Future licensing changes may require permission from outside copyright holders.

Be respectful, describe problems constructively, and allow time for review. This is an early project with limited maintainer capacity.
