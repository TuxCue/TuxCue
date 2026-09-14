"""Fail packaging if private data, audio clips, or missing legal files are found."""
from pathlib import Path
import sys

AUDIO = {'.mp3', '.wav', '.flac', '.ogg', '.opus', '.m4a', '.aac', '.aiff', '.aif', '.wma', '.mp4'}
PRIVATE = {'sound-files', '.state', '.env', 'sets.json', 'audio-settings.json',
           'remote-settings.json', 'library.json', 'audio-session.json', 'storage.json'}


def check(root):
    root = Path(root)
    for path in root.rglob('*'):
        if path.name in PRIVATE:
            raise ValueError(f'Private collection/configuration in package: {path.relative_to(root)}')
        if not path.is_file():
            continue
        if path.suffix.lower() in AUDIO:
            raise ValueError(f'Audio must never ship with TuxCue: {path.relative_to(root)}')
        with path.open('rb') as data:
            header = data.read(16)
        if (header.startswith((b'ID3', b'OggS', b'fLaC'))
                or header[:4] == b'RIFF' and header[8:12] == b'WAVE'
                or header[:4] == b'FORM' and header[8:12] in (b'AIFF', b'AIFC')):
            raise ValueError(f'Audio content in package: {path.relative_to(root)}')
    internal = root/'usr/bin/_internal'
    for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md', 'licenses/components.json', 'licenses/common/GPL-3'):
        if not (internal/name).is_file():
            raise ValueError(f'Missing release notice: {name}')
    print('AppDir verified: no audio or collection data; release notices present.')


if __name__ == '__main__':
    check(Path(sys.argv[1]))
