"""Choose and relocate the user's collection without editing the original copy."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from .library import atomic_json

DATA_ENTRIES = ('library', 'sets.json', 'audio-settings.json', 'audio-session.json', 'remote-settings.json', 'backups')
MOVED_MARKER = '.tuxcue-moved.json'


def folder_path(value: str | Path) -> Path:
    if not str(value).strip() or '\x00' in str(value):
        raise ValueError('Enter a folder path.')
    path = Path(str(value).strip()).expanduser()
    if not path.is_absolute():
        raise ValueError('Use an absolute folder path, or a path beginning with ~/.')
    return path.resolve()


def lock_folder(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    handle = (directory/'app.lock').open('a+')
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise ValueError('This collection is already open in another TuxCue process.')
    return handle


def fingerprint(directory: Path):
    result = {}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise ValueError('The collection contains a symbolic link. Use ordinary files before moving it.')
        if path.is_file() and path.name != 'app.lock':
            digest = hashlib.sha256()
            with path.open('rb') as data:
                while chunk := data.read(1024*1024):
                    digest.update(chunk)
            result[str(path.relative_to(directory))] = digest.hexdigest()
    return result


def active_folder(directory):
    seen=set()
    while (directory/MOVED_MARKER).exists():
        if directory in seen or len(seen)>100:
            raise ValueError('The storage history contains a loop. Check the saved collection location.')
        seen.add(directory)
        directory=folder_path(json.loads((directory/MOVED_MARKER).read_text())['folder'])
    return directory


class Storage:
    def __init__(self, directory, config_file, default_directory, *, managed=True):
        self.directory = folder_path(directory)
        self.config_file = Path(config_file)
        self.default_directory = folder_path(default_directory)
        self.managed = managed
        self.handle = lock_folder(self.directory)
        if (self.directory/MOVED_MARKER).exists():
            self.close()
            raise ValueError('This is a backup of a moved collection. Start TuxCue with its saved storage location.')

    @classmethod
    def open(cls, project, *, override=None, config_file=None, default_directory=None):
        default = folder_path(default_directory or Path.home()/'TuxCue')
        config = Path(config_file) if config_file else Path(os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config')/'tuxcue'/'storage.json'
        if override is not None:
            return cls(override, config, default, managed=False)
        if config.exists():
            try:
                directory = active_folder(folder_path(json.loads(config.read_text())['folder']))
            except (KeyError, TypeError, json.JSONDecodeError):
                raise ValueError(f'The storage preference in {config} is invalid.')
            if not directory.is_dir():
                raise ValueError(f'The saved collection folder is unavailable: {directory}. Reconnect its drive before starting TuxCue.')
            result=cls(directory, config, default)
            try:
                atomic_json(config, {'folder':str(directory)})
            except Exception:
                result.close(); raise
            return result
        legacy = Path(project)/'.state'
        if (legacy/MOVED_MARKER).exists():
            # Recover the active location if the small preference file was removed.
            directory = active_folder(legacy)
            if not directory.is_dir():
                raise ValueError(f'The moved collection is unavailable: {directory}')
            result = cls(directory, config, default)
        elif (legacy/'library/library.json').exists() or (legacy/'sets.json').exists():
            result = cls(legacy, config, default)
            try:
                result.relocate(default)
                return result
            except Exception:
                result.close()
                raise
        else:
            result = cls(default, config, default)
        try:
            atomic_json(config, {'folder':str(result.directory)})
        except Exception:
            result.close()
            raise
        return result

    def info(self):
        return {'folder':str(self.directory), 'default_folder':str(self.default_directory),
                'can_change':self.managed}

    def relocate(self, destination):
        if not self.managed:
            raise ValueError('This launch uses --data-dir. Start without that override to change the saved folder.')
        target = folder_path(destination)
        source = self.directory
        if target == source:
            atomic_json(self.config_file, {'folder':str(source)})
            return {**self.info(), 'changed':False, 'backup_folder':None}
        if source in target.parents or target in source.parents:
            raise ValueError('Choose a folder outside the current collection, not one of its parent folders.')
        if target.exists() and (not target.is_dir() or any(target.iterdir())):
            raise ValueError('Choose a new or empty folder. Existing files will not be overwritten.')
        if target == self.config_file.parent or target in self.config_file.parents:
            raise ValueError('Keep the collection separate from the TuxCue configuration folder.')
        target_existed = target.exists()
        target.mkdir(parents=True, exist_ok=True)
        new_handle = None
        stage = None
        published_entries = []
        marker_written = False
        try:
            # Stage inside the chosen folder: no access to neighbouring folders is
            # required, and the destination lock excludes another TuxCue process.
            new_handle = lock_folder(target)
            stage = Path(tempfile.mkdtemp(prefix='.tuxcue-copy-', dir=target))
            for name in DATA_ENTRIES:
                original = source/name
                if not original.exists():
                    continue
                if original.is_symlink() or (original.is_dir() and any(p.is_symlink() for p in original.rglob('*'))):
                    raise ValueError('The collection contains symbolic links. Use ordinary files before moving it.')
                if original.is_dir():
                    shutil.copytree(original,stage/name)
                else:
                    shutil.copy2(original,stage/name)
            expected = {}
            for name in DATA_ENTRIES:
                original = source/name
                if original.is_dir():
                    expected.update({f'{name}/{p}':v for p,v in fingerprint(original).items()})
                elif original.is_file():
                    expected[name] = hashlib.sha256(original.read_bytes()).hexdigest()
            if fingerprint(stage) != expected:
                raise ValueError('The copied files did not verify. Your original collection is still active.')
            for path in stage.rglob('*'):
                if path.is_file():
                    with path.open('rb') as f:
                        os.fsync(f.fileno())
            if any(p not in (stage,target/'app.lock') for p in target.iterdir()):
                raise ValueError('The destination is no longer empty. Choose another folder.')
            for entry in stage.iterdir():
                destination=target/entry.name
                entry.rename(destination)
                published_entries.append(destination)
            stage.rmdir()
            atomic_json(source/MOVED_MARKER, {'folder':str(target)})
            marker_written = True
            atomic_json(self.config_file, {'folder':str(target)})
        except Exception as error:
            if marker_written:
                (source/MOVED_MARKER).unlink(missing_ok=True)
            for entry in published_entries:
                if entry.is_dir():shutil.rmtree(entry)
                else:entry.unlink(missing_ok=True)
            if stage and stage.exists():shutil.rmtree(stage)
            if new_handle:
                new_handle.close()
                (target/'app.lock').unlink(missing_ok=True)
            if not target_existed:
                try:target.rmdir()
                except OSError:pass
            if isinstance(error, OSError):
                raise ValueError('Could not move the collection. Check folder permissions and free disk space; the original folder is still active.') from error
            raise
        old_handle = self.handle
        self.directory, self.handle = target, new_handle
        old_handle.close()
        return {**self.info(), 'changed':True, 'backup_folder':str(source)}

    def close(self):
        if self.handle:
            self.handle.close()
            self.handle = None


def browse_folders(value=None):
    path = folder_path(value or Path.home())
    if not path.is_dir():
        raise ValueError('That folder is unavailable. Enter an existing folder to browse it.')
    try:
        folders = sorted((p.name for p in path.iterdir() if p.is_dir()), key=str.casefold)
        return {'folder':str(path), 'parent':str(path.parent) if path.parent != path else None,
                'folders':folders[:1000]}
    except PermissionError:
        raise ValueError('You do not have permission to browse that folder.')
