"""Download only checksum-pinned upstream packaging inputs."""
import hashlib
import json
from pathlib import Path
import urllib.request


def download(url, destination, expected):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        temporary = destination.with_suffix(destination.suffix + '.partial')
        try:
            with urllib.request.urlopen(url, timeout=120) as response, temporary.open('wb') as output:
                import shutil
                shutil.copyfileobj(response, output)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    actual = hashlib.sha256(destination.read_bytes()).hexdigest()
    if actual != expected:
        raise RuntimeError(f'Checksum mismatch for {destination.name}; refusing to use this input.')
    return destination


if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    for name, entry in json.loads((root/'inputs.json').read_text()).items():
        download(entry['url'], Path('/build/inputs')/name, entry['sha256'])
        print('Verified', name, entry['version'], flush=True)
