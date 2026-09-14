"""Copy full notices for resolved npm packages; no network and no audio assets."""
import json
from pathlib import Path
import shutil


def main():
    root = Path(__file__).resolve().parent.parent/'frontend'
    output = root/'dist/licenses'
    output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root.parent/'LICENSE', output/'LICENSE')
    records = {}
    for manifest in (root/'node_modules/.pnpm').glob('*/node_modules/**/package.json'):
        # Only package roots, not examples and embedded test fixtures.
        relative = manifest.relative_to(root/'node_modules/.pnpm')
        if len(relative.parts) not in (4, 5) or len(relative.parts) == 5 and not relative.parts[2].startswith('@'):
            continue
        data = json.loads(manifest.read_text())
        name, version = data['name'], data['version']
        key = f'{name}@{version}'
        if key in records:
            continue
        licenses = [p for p in manifest.parent.iterdir() if p.is_file()
                    and p.name.lower().startswith(('license', 'copying', 'notice', 'copyright'))]
        # Platform-only binaries have the same license as their parent project.
        if not licenses and name.startswith(('@rollup/', '@esbuild/', '@napi-rs/')):
            continue
        if not licenses:
            raise RuntimeError(f'No license text found for {key}')
        target = output/key.replace('/', '__')
        target.mkdir(exist_ok=True)
        for source in licenses:
            shutil.copy2(source, target/source.name)
        records[key] = {'name': name, 'version': version, 'license': data.get('license')}
    (output/'components.json').write_text(json.dumps(list(records.values()), indent=2)+'\n')
    print(f'Collected {len(records)} frontend dependency notices.')


if __name__ == '__main__':
    main()
