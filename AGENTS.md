# TuxCue development guidance

TuxCue is a Linux soundboard with a Python backend and React browser interface.

- Preserve existing functionality, collection compatibility, audio ownership checks, and upgrade behavior.
- AppImage is the only supported user launch method. Keep its internal AppRun entry point and build scripts, but do not add user startup/setup helpers. Build in disposable directories and write artifacts outside the checkout; keep the same build command usable locally and in CI.
- Users provide their own audio. Never ship sounds, personal collections, pairing records, or development recordings in source releases or AppImages.
- Keep changes focused. No architecture rewrites, framework migrations, or unrelated formatting without an explicit reason and authorization.
- Source is GPL-3.0-or-later; preserve third-party notices and record provenance. Do not invent copyright ownership.
- TuxCue branding identifies the project. Do not rename it or imply Linux Foundation affiliation.
- Use `requirements.lock`, `requirements-build.lock`, and `frontend/pnpm-lock.yaml`. Verify changed dependencies against public advisories.
- Follow CONTRIBUTING.md for checks. Run appropriate tests and the frontend build; use temporary collections and synthetic audio for integration tests.
- Packaging must run `packaging/check_appdir.py` and produce license notices, component metadata, and corresponding-source archives.
- Never test against a user's collection or replace a running personal session without authorization.
- Explain potentially breaking changes and any unverified manual checks.
- Do not publish releases, push tags, change visibility, or merge unless explicitly authorized.
