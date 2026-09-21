# Preparing a release

Maintainers review and authorize releases by pushing a version tag. The release workflow then builds and publishes the assets; ordinary pushes to `main` only run source checks. Neither workflow changes repository visibility.

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

## Publish through GitHub Actions

After completing the review above, commit the version and release changes to `main` and push that branch. For version 0.4.7:

```bash
git tag -a v0.4.7 -m "TuxCue 0.4.7"
git push origin v0.4.7
```

Pushing this tag authorizes publication. The `Release AppImage` workflow checks that the tag is exactly `vMAJOR.MINOR.PATCH`, matches the application version, and points to a commit reachable from `origin/main`. It invokes the existing build script, including Python tests, frontend compilation, license/source collection, and the no-audio AppDir check. It verifies checksums, uploads all five assets to a draft, and publishes only after successful uploads. It uses the workflow's automatic `GITHUB_TOKEN` with `contents: write`; no runner-registration PAT or extra release secret is needed.

Both workflows use the repository's configured runner. Source checks run on pushes to `main` or manually from the Actions page; pull requests do not automatically execute on the persistent runner. Builds require Docker access and several GB of free disk space. Existing Docker containers are not pruned or stopped.

If an upload fails, the release remains a draft. Use **Re-run failed jobs** on the tag workflow to rebuild and replace that draft's assets. Published releases are never overwritten; use a new version and tag for changes. Preserve the corresponding-source archives alongside each AppImage.

## Rebuild information

The application source archive uses the AppImage build command documented in APPIMAGE.md. The third-party archive records exact Ubuntu source package versions and includes their `.dsc`, original tarballs, and packaging patches. Its `packaging/` directory records the AppImage recipe, pinned upstream inputs, and FFmpeg configuration. The runtime source includes the patch applied to libfuse and upstream rebuild scripts; a replacement runtime can be supplied to appimagetool using `--runtime-file`.

The checksums verify downloaded bytes, not the identity of an independently distributed checksum file. No package-signing key or payment account is configured by this procedure.
