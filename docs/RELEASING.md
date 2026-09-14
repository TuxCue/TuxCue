# Preparing a release

This is a manual maintainer procedure. The repository does not automatically publish or change visibility.

1. Review dependencies and upstream security advisories. Update explicit versions/hashes deliberately, including `packaging/inputs.json`. Verify FFmpeg's signature against the upstream key fingerprint before accepting a new hash.
2. Keep the version consistent in `soundboard/__init__.py`, `pyproject.toml`, `frontend/package.json`. Update integration-test defaults and the changelog.
3. Run source tests and `python3 scripts/check_release.py`. Review the Git diff and verify that no audio clips, private settings, screenshots, caches, or credentials are included.
4. Run `./scripts/build_appimage.sh`. A missing third-party source archive, notice, hash mismatch, or packaged audio file must fail preparation.
5. Exercise the candidate with temporary collections and synthetic audio, including preview/broadcast separation, trimming, phone pairing, tray/browser actions, and update handover. Confirm the manual checks in VALIDATION.md before claiming them.
6. Review `COMPONENTS.json` in the external output folder and the source archive contents. Preserve full required third-party notices, exact sources and distro patches, and build instructions. Verify that corresponding source is sufficient for covered components; escalate any unresolved license/provenance issue before publishing.
7. Only with explicit owner authorization, publish the reviewed source revision and release assets together. Do not change repository visibility as part of building. Enable and verify GitHub private vulnerability reporting when the repository becomes public.

## Assets that belong together

- `TuxCue-VERSION-x86_64.AppImage`
- `TuxCue-VERSION-source.tar.gz` — matching application source, including frontend sources and lockfiles.
- `TuxCue-VERSION-third-party-sources.tar.xz` — exact downloaded third-party sources, distro patches, packaging inputs and configuration.
- `COMPONENTS.json` and `SHA256SUMS`.

Provide both corresponding-source archives next to the binary at no additional charge. Do not rely solely on GitHub's automatically generated source ZIP for the bundled dependencies. Preserve these assets for each release instead of replacing old files with newer sources.

The third-party archive contains upstream source material and may include upstream test fixtures under their own licenses. Such material is not a built-in TuxCue sound library and is never copied into the AppImage.

## Rebuild information

The application source archive uses the AppImage build command documented in APPIMAGE.md. The third-party archive records exact Ubuntu source package versions and includes their `.dsc`, original tarballs, and packaging patches. Its `packaging/` directory records the AppImage recipe, pinned upstream inputs, and FFmpeg configuration. The runtime source includes the patch applied to libfuse and upstream rebuild scripts; a replacement runtime can be supplied to appimagetool using `--runtime-file`.

The checksums verify downloaded bytes, not the identity of an independently distributed checksum file. No package-signing key or payment account is configured by this procedure.
