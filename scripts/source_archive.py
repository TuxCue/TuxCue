"""Create the matching application source archive without local user data."""
import sys
from pathlib import Path
import tarfile
from release_files import ROOT, files
from check_release import main as check
sys.path.insert(0, str(ROOT))
from soundboard import __version__

check()
if len(sys.argv) != 2:
    raise SystemExit('Usage: python3 scripts/source_archive.py /absolute/output/directory')
destination = Path(sys.argv[1]).resolve()/f'TuxCue-{__version__}-source.tar.gz'
if destination.is_relative_to(ROOT):
    raise SystemExit('Keep release artifacts outside the source repository.')
destination.parent.mkdir(parents=True, exist_ok=True)


def anonymous(info):
    info.uid = info.gid = 0
    info.uname = info.gname = ''
    return info


with tarfile.open(destination, 'w:gz') as archive:
    for path in files():
        archive.add(path, arcname=f'TuxCue-{__version__}/{path.relative_to(ROOT)}', recursive=False, filter=anonymous)
print('Created', destination.name)
