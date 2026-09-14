"""Self-contained set bundles. Never extract archive paths onto the filesystem."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import uuid
import zipfile

from .boards import validate_profile
from .library import Library, atomic_json, MAX_SECONDS

MAX_UNPACKED = 512 * 1024 * 1024


def export_set(boards, library, profile_id, output):
    snapshot = boards.snapshot()
    profile = deepcopy(boards.profile(snapshot, profile_id))
    available = {s['id']:s for s in library.list()}
    profile['tiles'] = [t if t and t['sound_id'] in available else None for t in profile['tiles']]
    ids = {t['sound_id'] for t in profile['tiles'] if t}
    if sum(library.path(i).stat().st_size for i in ids) > MAX_UNPACKED:
        raise ValueError('This set exceeds the 512 MB audio bundle limit. Split it into smaller sets.')
    sounds = [{**available[i], 'file':f'audio/{i}.wav'} for i in sorted(ids)]
    manifest = {'format':'soundboard-set','version':1,'profile':profile,'sounds':sounds}
    manifest_bytes = json.dumps(manifest, ensure_ascii=False).encode('utf-8')
    if sum(library.path(i).stat().st_size for i in ids) + len(manifest_bytes) > MAX_UNPACKED:
        raise ValueError('This set exceeds the 512 MB bundle limit. Split it into smaller sets.')
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json', manifest_bytes)
        for sound in sounds:
            archive.write(library.path(sound['id']), sound['file'])


def import_set(boards, library, archive_path):
    try:
        with zipfile.ZipFile(archive_path) as archive, tempfile.TemporaryDirectory() as temp:
            entries = archive.infolist()
            names = [i.filename for i in entries]
            if len(entries) > 1001 or len(names) != len(set(names)) or sum(i.file_size for i in entries) > MAX_UNPACKED:
                raise ValueError('The bundle is too large or contains duplicate entries.')
            info = archive.getinfo('manifest.json')
            if info.file_size > 2 * 1024 * 1024:
                raise ValueError('The bundle manifest is too large.')
            manifest = json.loads(archive.read('manifest.json'))
            if manifest.get('format') != 'soundboard-set' or manifest.get('version') != 1:
                raise ValueError('Choose a Soundboard set bundle exported by this app.')
            profile = validate_profile(deepcopy(manifest['profile']))
            sounds = manifest['sounds']
            if not isinstance(sounds, list) or len(sounds) > 1000:
                raise ValueError('Invalid bundle sound list.')
            by_id = {}
            for item in sounds:
                sound_id = item.get('id')
                if not isinstance(sound_id,str) or not re.fullmatch('[a-f0-9]{24}',sound_id) or sound_id in by_id:
                    raise ValueError('Invalid or duplicate sound identifiers in the bundle.')
                if not isinstance(item.get('name'),str) or not 1 <= len(item['name'].strip()) <= 120:
                    raise ValueError('Invalid sound name in the bundle.')
                if item.get('file') != f'audio/{sound_id}.wav':
                    raise ValueError('Invalid audio path in the bundle.')
                if not isinstance(item.get('filename', 'audio.wav'), str):
                    raise ValueError('Invalid audio filename in the bundle.')
                by_id[sound_id] = item
            if any(t and t['sound_id'] not in by_id for t in profile['tiles']):
                raise ValueError('The bundle is missing audio used by its tiles.')
            allowed = {'manifest.json'} | {i['file'] for i in sounds}
            if set(names) != allowed:
                raise ValueError('The bundle contains unexpected or missing files.')
            # Decode and validate everything in a temporary library before publishing.
            staging = Library(Path(temp)/'library', Path(temp)/'samples')
            prepared = []
            for old_id, item in by_id.items():
                original = Path(temp)/'incoming.wav'
                with archive.open(item['file']) as src, original.open('wb') as dst:
                    shutil.copyfileobj(src,dst,1024*1024)
                checked = staging.import_file(original, 'incoming.wav', max_bytes=MAX_SECONDS*48000*4+65536)
                prepared.append((old_id,item,checked,staging.path(checked['id'])))
            remap = {}
            for old_id,item,checked,path in prepared:
                final_id = old_id
                old_path = library._pcm_path(library.items[old_id]) if old_id in library.items else None
                if old_path and old_path.exists() and hashlib.sha256(old_path.read_bytes()).digest() != hashlib.sha256(path.read_bytes()).digest():
                    final_id = uuid.uuid4().hex[:24]
                remap[old_id] = final_id
            for t in profile['tiles']:
                if t:
                    t['id'] = uuid.uuid4().hex
                    t['sound_id'] = remap[t['sound_id']]
            profile['id'] = uuid.uuid4().hex
            profile['name'] = profile['name'] + ' (imported)' if len(profile['name']) <= 69 else profile['name']
            validate_profile(profile)
            # Validate the destination set/stop shortcut constraints before adding audio.
            snapshot = boards.snapshot()
            if len(snapshot['profiles']) >= 100:
                raise ValueError('The soundboard already contains 100 sets.')
            if any(t and t['shortcut'] and t['shortcut'] == snapshot['stop_shortcut'] for t in profile['tiles']):
                raise ValueError('An imported tile uses the current Stop all shortcut. Change Stop all first.')
            with library.lock:
                for old_id,item,checked,path in prepared:
                    final_id = remap[old_id]
                    if final_id not in library.items or not library._pcm_path(library.items[final_id]).is_file():
                        filename = Path(item.get('filename','audio.wav')).name
                        library.store_audio({'id':final_id,'name':item['name'].strip(),
                                             'filename':filename,'duration':checked['duration']},
                                            path, path, Path(filename).stem + '.wav')
                    else:
                        library.items[final_id]['trashed'] = False
                atomic_json(library.index,library.items)
            def publish(data):
                data['profiles'][profile['id']] = profile
                data['active_id'] = profile['id']
            boards.mutate(publish)
            return profile
    except (zipfile.BadZipFile,KeyError,TypeError,AttributeError,json.JSONDecodeError,RuntimeError) as e:
        raise ValueError('The set bundle is invalid or incomplete.') from e
