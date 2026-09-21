# Changelog

## 0.4.7

- Add a headphone button to every populated board tile for local-only preview, including while the virtual microphone is connected.
- Pin Ubuntu binary and source packages to the same archive snapshot so AppImage source collection is not broken by mirror rotation.

## 0.4.6

- Correct release metadata, dependency locks, documentation, and release validation for the AppImage build.

## 0.4.5

- Sort the Library, Trash, and tile sound picker alphabetically with natural number ordering.
- Style dropdown options with dark backgrounds and green selection highlights.
- Preserve readable audio filenames and original formats when exporting a set.

## 0.4.4

- Prepare the source repository for public release under GPL-3.0-or-later.
- Update Click, h11, and idna to patched versions and record dependency artifact hashes.
- Build the AppImage's FFmpeg from verified 8.1.2 source; pin the AppImage packaging tool and runtime hash.
- Include third-party license notices and generate matching source archives and a component inventory.
- Reject audio files and collection data during packaging. Users supply all sounds.
- Add public documentation, contribution/security guidance, and release checks.

## Earlier local versions

- **0.4.3:** gracefully replace an older running version and coordinate concurrent launches.
- **0.4.2:** restore the host desktop environment when opening the browser from an AppImage or tray.
- **0.4.1:** phone-specific grids, square tiles, compact view, and portrait/landscape preferences.
- **0.4.0:** optional paired-phone control and a desktop tray menu.
- **0.3.0:** TuxCue branding, configurable collection location, original filenames, and AppImage packaging.
- Earlier development added saved sets, shortcuts, audio editing, Trash/restore, and virtual microphone routing.
