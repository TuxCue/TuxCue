"""Collect notices and exact source archives for the files selected by PyInstaller.

Run inside the disposable Ubuntu build container, after freezing the application.
Unknown file owners or missing source packages fail the build.
"""
import gzip
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import urllib.request

from fetch_inputs import download

ROOT = Path('/build')
INTERNAL = ROOT/'AppDir/usr/bin/_internal'
LICENSES = INTERNAL/'licenses'
SOURCES = ROOT/'release-sources'


def rust_sources(source_archive):
    """Preserve pydantic-core's statically linked Rust dependencies and their notices."""
    result = []
    supplements = json.loads((ROOT/'packaging/rust-sources.json').read_text())
    with tarfile.open(source_archive) as archive:
        lock = next((member for member in archive if member.name.endswith('/Cargo.lock')), None)
        if lock is None:
            return result
        text = archive.extractfile(lock).read().decode()
    for section in re.split(r'(?m)^\[\[package\]\]\s*$', text):
        fields = dict(re.findall(r'(?m)^(name|version|source|checksum) = "([^"]+)"$', section))
        if 'source' not in fields:
            continue
        if fields['source'] != 'registry+https://github.com/rust-lang/crates.io-index':
            raise RuntimeError('Unreviewed Rust dependency origin: '+fields['source'])
        name, version, digest = fields['name'], fields['version'], fields['checksum']
        url = f'https://static.crates.io/crates/{name}/{name}-{version}.crate'
        path = download(url, SOURCES/'rust'/f'{name}-{version}.crate', digest)
        target = LICENSES/'rust'/f'{name}-{version}'
        notices = 0
        with tarfile.open(path) as crate:
            for member in crate:
                relative = Path(member.name)
                if not member.isfile() or '..' in relative.parts or relative.is_absolute():
                    continue
                if any(part.lower().startswith(('license', 'licence', 'copying', 'notice', 'copyright'))
                       for part in relative.parts[1:]) or (
                        relative.name == 'AUTHORS' and b'Permission is hereby granted' in crate.extractfile(member).read()):
                    destination = target/Path(*relative.parts[1:])
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(crate.extractfile(member).read())
                    notices += 1
            manifest = crate.extractfile(f'{name}-{version}/Cargo.toml').read().decode()
            expression = re.search(r'(?m)^license = "([^"]+)"$', manifest)
        supplement = supplements.get(f'{name}@{version}')
        if supplement:
            extra = download(supplement['url'], SOURCES/'rust'/f'{name}-{supplement["revision"]}.tar.gz', supplement['sha256'])
            with tarfile.open(extra) as upstream:
                for member in upstream:
                    relative = Path(member.name)
                    if member.isfile() and len(relative.parts) == 2 and relative.name.lower().startswith(('license', 'copying', 'notice', 'copyright')):
                        target.mkdir(parents=True, exist_ok=True)
                        (target/relative.name).write_bytes(upstream.extractfile(member).read())
                        notices += 1
        if not notices:
            raise RuntimeError(f'Rust dependency {name} {version} has no collected license notice')
        result.append({'name': name, 'version': version, 'source_url': url, 'sha256': digest,
                       'license': expression.group(1) if expression else None, 'supplement': supplement})
    return result


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False)+'\n')


def main():
    LICENSES.mkdir(parents=True, exist_ok=True)
    SOURCES.mkdir(parents=True, exist_ok=True)
    shutil.copytree('/usr/share/common-licenses', LICENSES/'common', dirs_exist_ok=True)
    shutil.copytree(ROOT/'packaging', SOURCES/'packaging', ignore=shutil.ignore_patterns('__pycache__'))
    for name in ('requirements.lock', 'requirements-build.lock', 'THIRD_PARTY_NOTICES.md', 'LICENSE'):
        shutil.copy2(ROOT/name, SOURCES/name)
    # The frontend notice generator copies the full license files, including inherited notices.
    shutil.copytree(ROOT/'frontend/dist/licenses', LICENSES/'javascript', dirs_exist_ok=True)
    components = {'python': [], 'debian': [], 'rust': [],
                  'ubuntu_snapshot': os.environ['TUXCUE_UBUNTU_SNAPSHOT'],
                  'upstream': json.loads((ROOT/'packaging/inputs.json').read_text())}
    components['javascript'] = json.loads((ROOT/'frontend/dist/licenses/components.json').read_text())
    components['javascript_sources'] = json.loads((ROOT/'packaging/javascript-sources.json').read_text())
    for name, entry in components['javascript_sources'].items():
        download(entry['url'], SOURCES/'javascript'/f'{name}-{entry["revision"]}.tar.gz', entry['sha256'])
    # Fetch exact source distributions without running arbitrary packaging metadata hooks.
    for distribution in metadata.distributions(path=['/opt/venv/lib/python3.10/site-packages']):
        name, version = distribution.metadata['Name'], distribution.version
        folder = LICENSES/'python'/f'{name}-{version}'
        files = [f for f in distribution.files or [] if any(
            part.lower().startswith(('license', 'copying', 'notice', 'copyright')) for part in f.parts)]
        if not files:
            raise RuntimeError(f'No license files found for Python distribution {name}')
        for file in files:
            source = distribution.locate_file(file)
            if source.is_file():
                # Keep directory structure because vendored components may have separate licenses.
                target = folder/str(file).replace('../', '')
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        with urllib.request.urlopen(f'https://pypi.org/pypi/{name}/{version}/json', timeout=60) as response:
            info = json.load(response)
        sdists = [f for f in info['urls'] if f['packagetype'] == 'sdist']
        if len(sdists) != 1:
            raise RuntimeError(f'Expected one exact source distribution for {name} {version}')
        archive = sdists[0]
        source_archive = download(archive['url'], SOURCES/'python'/archive['filename'], archive['digests']['sha256'])
        if name.lower().replace('-', '_') == 'pydantic_core':
            components['rust'].extend(rust_sources(source_archive))
        components['python'].append({'name': name, 'version': version,
            'license': distribution.metadata.get('License-Expression') or distribution.metadata.get('License'),
            'source_url': archive['url'], 'source_sha256': archive['digests']['sha256']})
    # Map each distro-owned input to its binary package, then exact source package/version.
    owners = {}
    for listing in Path('/var/lib/dpkg/info').glob('*.list'):
        package = listing.name[:-5]
        for line in listing.read_text().splitlines():
            owners.setdefault(line, set()).add(package)
    selected = set()
    unmatched = []
    for filename in json.loads((ROOT/'native-files.json').read_text()):
        path = Path(filename)
        if filename.startswith(('/build/', '/opt/venv/', '/opt/tuxcue-media/')):
            continue
        # These three files are generated by distro package triggers, so dpkg
        # does not list them directly. Preserve their generators and source inputs.
        generated = {
            '/lib/x86_64-linux-gnu/gio/modules/giomodule.cache':
                (list(path.parent.glob('*.so')), 'gio-querymodules'),
            '/usr/share/glib-2.0/schemas/gschemas.compiled':
                (list(path.parent.glob('*.xml')) + list(path.parent.glob('*.override')), 'glib-compile-schemas'),
            '/usr/share/mime/mime.cache':
                (list((path.parent/'packages').glob('*.xml')), 'update-mime-database'),
        }
        if filename in generated:
            inputs, generator = generated[filename]
            executable = shutil.which(generator)
            if not executable:
                executable = next(Path('/usr/lib').glob('*/glib-2.0/'+generator), None)
            if not inputs or not executable:
                raise RuntimeError('Missing source inputs for generated cache: '+filename)
            for source_input in [*inputs, Path(executable)]:
                matches = owners.get(str(source_input)) or owners.get(str(source_input.resolve()))
                if not matches:
                    raise RuntimeError('Unmapped generated cache source: '+str(source_input))
                selected.update(matches)
            continue
        matches = owners.get(filename) or owners.get(str(path.resolve()))
        if matches:
            selected.update(matches)
        elif path.exists():
            unmatched.append(filename)
    if unmatched:
        raise RuntimeError('Unmapped packaged inputs: '+repr(unmatched))
    downloads = set()
    apt = SOURCES/'debian'
    apt.mkdir(exist_ok=True)
    # Let APT keep its download sandbox instead of falling back to root.
    shutil.chown(apt, user='_apt', group='root')
    for package in sorted(selected):
        fields = subprocess.check_output(['dpkg-query', '-W', '-f',
            '${binary:Package}\t${Version}\t${source:Package}\t${source:Version}', package], text=True).split('\t')
        binary, version, source, source_version = fields
        copyright_file = Path('/usr/share/doc')/binary.split(':')[0]/'copyright'
        if not copyright_file.is_file():
            raise RuntimeError(f'Missing copyright file for {binary}')
        target = LICENSES/'debian'/binary
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(copyright_file, target/'copyright')
        components['debian'].append({'package': binary, 'version': version,
            'source': source, 'source_version': source_version})
        if (source, source_version) not in downloads:
            subprocess.run(['apt-get', '-o', 'Acquire::Retries=3', 'source', '--download-only', '--yes',
                            f'{source}={source_version}'], cwd=apt, check=True)
            downloads.add((source, source_version))
    # Preserve preferred source/build scripts, not copies of downloaded tool binaries.
    shutil.copytree(ROOT/'inputs', SOURCES/'upstream', dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('appimagetool', 'runtime'))
    shutil.copy2(ROOT/'ffmpeg-config.mak', SOURCES/'ffmpeg-config.mak')
    shutil.copy2(ROOT/'ffmpeg-config.h', SOURCES/'ffmpeg-config.h')
    ffmpeg_notices = LICENSES/'ffmpeg'
    ffmpeg_notices.mkdir(exist_ok=True)
    for path in (ROOT/'ffmpeg-source').glob('COPYING*'):
        shutil.copy2(path, ffmpeg_notices/path.name)
    shutil.copy2(ROOT/'ffmpeg-source/LICENSE.md', ffmpeg_notices/'LICENSE.md')
    # This pinned runtime does not implement --appimage-license. Collect full
    # upstream notices from its source archives and checksum-pinned notice texts.
    runtime_notices = LICENSES/'appimage-runtime'
    runtime_notices.mkdir(exist_ok=True)
    for archive_name in ('runtime-source', 'runtime-libfuse', 'runtime-squashfuse'):
        with tarfile.open(ROOT/'inputs'/archive_name) as archive:
            for member in archive:
                path = Path(member.name)
                if member.isfile() and len(path.parts) == 2 and path.name.lower().startswith(('license', 'copying', 'lgpl', 'gpl', 'authors')):
                    (runtime_notices/(archive_name+'-'+path.name)).write_bytes(archive.extractfile(member).read())
    components['runtime_notice_sources'] = json.loads((ROOT/'packaging/runtime-notices.json').read_text())
    for name, entry in components['runtime_notice_sources'].items():
        notice = download(entry['url'], SOURCES/'runtime-notices'/f'{name}.txt', entry['sha256'])
        shutil.copy2(notice, runtime_notices/notice.name)
    write_json(LICENSES/'components.json', components)
    write_json(SOURCES/'components.json', components)
    inventory = {}
    for path in SOURCES.rglob('*'):
        if path.is_file():
            inventory[str(path.relative_to(SOURCES))] = hashlib.sha256(path.read_bytes()).hexdigest()
    write_json(SOURCES/'SHA256SUMS.json', inventory)
    print(f'Collected {len(selected)} native package notices and {len(downloads)} exact distro source packages.', flush=True)


if __name__ == '__main__':
    main()
