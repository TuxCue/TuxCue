"""Download only checksum-pinned upstream packaging inputs."""
import hashlib
import json
from pathlib import Path
import time
import urllib.request


def download(url, destination, expected, attempts=3):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        temporary = destination.with_suffix(destination.suffix + '.partial')
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(url, timeout=120) as response, temporary.open('wb') as output:
                    import shutil
                    shutil.copyfileobj(response, output)
                temporary.replace(destination)
                break
            except OSError:
                temporary.unlink(missing_ok=True)
                if attempt + 1 == attempts:
                    raise
                time.sleep(2 ** attempt)
    actual = hashlib.sha256(destination.read_bytes()).hexdigest()
    if actual != expected:
        raise RuntimeError(f'Checksum mismatch for {destination.name}; refusing to use this input.')
    return destination


if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    for name, entry in json.loads((root/'inputs.json').read_text()).items():
        download(entry['url'], Path('/build/inputs')/name, entry['sha256'])
        print('Verified', name, entry['version'], flush=True)
