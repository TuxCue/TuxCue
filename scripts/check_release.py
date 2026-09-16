"""Check public-source selection, version consistency, and obvious private data."""
import json
import re
import sys

from release_files import ROOT, files
sys.path.insert(0, str(ROOT))
from soundboard import __version__


def main():
    selected = list(files())
    forbidden = {'.wav', '.mp3', '.flac', '.ogg', '.opus', '.m4a', '.aac', '.aiff', '.wma', '.zip', '.appimage'}
    patterns = ['/' + r'home/[^/\s]+/', '/' + r'Users/[^/\s]+/', r'[A-Z]:\\Users\\',
                r'gh[pousr]_[A-Za-z0-9]{20,}', r'github_pat_[A-Za-z0-9_]{20,}',
                r'glpat-[A-Za-z0-9_-]{20,}', r'AKIA[0-9A-Z]{16}',
                r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----']
    for path in selected:
        relative = path.relative_to(ROOT)
        if path.suffix.lower() in forbidden or path.name in {'sets.json', 'library.json', 'remote-settings.json', '.env'}:
            raise ValueError(f'Private data or binary artifact selected: {relative}')
        if path.suffix == '.png':
            continue
        text = path.read_text()
        if any(re.search(pattern, text) for pattern in patterns):
            raise ValueError(f'Potential private data in {relative}; inspect locally (value redacted).')
    package = json.loads((ROOT/'frontend/package.json').read_text())
    project = (ROOT/'pyproject.toml').read_text()
    if package['version'] != __version__ or f'version = "{__version__}"' not in project:
        raise ValueError('Python/frontend version metadata do not match.')
    if 'GPL-3.0-or-later' not in project:
        raise ValueError('Missing explicit project license designation.')
    print(f'Public-source check passed: {len(selected)} files, version {__version__}, no audio or obvious private data.')


if __name__ == '__main__':
    main()
