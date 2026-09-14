#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
export PYTHONDONTWRITEBYTECODE=1
command -v pnpm >/dev/null || { echo 'Install the pnpm version in frontend/package.json.' >&2; exit 1; }
command -v docker >/dev/null || { echo 'Docker is required to build the AppImage.' >&2; exit 1; }
version=$(cd "$root" && python3 -c 'from soundboard import __version__; print(__version__)')
output=${TUXCUE_OUTPUT_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/tuxcue/releases/$version}
output=$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).expanduser().resolve())' "$output")
python3 "$root/scripts/check_release.py"
# Archive selection rejects output inside the checkout before writing anything.
python3 "$root/scripts/source_archive.py" "$output"
workspace=$(mktemp -d -t tuxcue-build-XXXXXXXX)
container=''
cleanup() {
    if [[ -n "$container" ]]; then docker rm "$container" >/dev/null; fi
    rm -rf -- "$workspace"
}
trap cleanup EXIT
# Compile precisely the selected source; dependencies and generated files stay here.
tar -xzf "$output/TuxCue-$version-source.tar.gz" -C "$workspace"
cd "$workspace/TuxCue-$version"
(cd frontend && pnpm install --frozen-lockfile && pnpm run build)
python3 scripts/frontend_notices.py
image="tuxcue-appimage:$version"
docker build --progress=plain -f packaging/Dockerfile -t "$image" .
container=$(docker create "$image")
docker cp "$container:/output/." "$output/"
chmod +x "$output/TuxCue-$version-x86_64.AppImage"
(cd "$output" && sha256sum "TuxCue-$version-x86_64.AppImage" "TuxCue-$version-source.tar.gz" "TuxCue-$version-third-party-sources.tar.xz" COMPONENTS.json > SHA256SUMS)
echo "Created TuxCue $version, checksums, component inventory, and both source archives in $output."
