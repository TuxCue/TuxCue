"""Saved sets contain tile assignments; audio lives in the shared library."""
from copy import deepcopy
import math
from pathlib import Path
import re
import threading
import uuid

from .library import atomic_json

MODIFIERS = ('Ctrl', 'Alt', 'Shift', 'Super')
SPECIAL_KEYS = {'Space', 'Enter', 'Escape', 'Tab', 'Backspace', 'Delete', 'Insert', 'Home', 'End',
                'PageUp', 'PageDown', 'Left', 'Right', 'Up', 'Down', 'Minus', 'Equal', 'Comma', 'Period',
                'Slash', 'Backslash', 'Semicolon', 'Apostrophe', 'BracketLeft', 'BracketRight', 'Backquote'}


def shortcut(value):
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError('Invalid shortcut.')
    if not value.strip():
        return ''
    parts = value.split('+')
    key, mods = parts[-1], parts[:-1]
    if len(set(mods)) != len(mods) or any(m not in MODIFIERS for m in mods):
        raise ValueError('Use Ctrl, Alt, Shift or Super modifiers.')
    if len(key) == 1 and key.isascii() and key.isalnum():
        key = key.upper()
    elif key not in SPECIAL_KEYS and not re.fullmatch(r'F(?:[1-9]|1[0-9]|2[0-4])', key):
        raise ValueError('Use a letter, number, function key or supported navigation key.')
    if not mods and not re.fullmatch(r'F(?:[1-9]|1[0-9]|2[0-4])', key):
        raise ValueError('Add a modifier such as Ctrl or Alt, or use a function key.')
    return '+'.join([m for m in MODIFIERS if m in mods] + [key])


def tile(sound_id):
    return {'id': uuid.uuid4().hex, 'sound_id': sound_id, 'label': '', 'color': '#c4ed83', 'volume': 1.0, 'shortcut': ''}


def validate_profile(p):
    if not isinstance(p, dict) or not isinstance(p.get('name'), str) or not 1 <= len(p['name'].strip()) <= 80:
        raise ValueError('Set names must contain 1–80 characters.')
    p['name'] = p['name'].strip()
    for field in ('rows', 'columns'):
        if type(p.get(field)) is not int or not 1 <= p[field] <= 12:
            raise ValueError('Choose 1–12 rows and columns.')
    if p.get('playback_mode') not in ('replace', 'overlap'):
        raise ValueError('Choose replace or overlap playback.')
    if not isinstance(p.get('tiles'), list) or len(p['tiles']) > 1000:
        raise ValueError('A set can contain up to 1,000 tile positions.')
    seen_keys, seen_ids = set(), set()
    for t in p['tiles']:
        if t is None:
            continue
        if not isinstance(t, dict) or not isinstance(t.get('sound_id'), str) or not re.fullmatch('[a-f0-9]{24}', t['sound_id']):
            raise ValueError('Invalid tile sound reference.')
        if not isinstance(t.get('id'), str) or t['id'] in seen_ids:
            raise ValueError('Invalid or duplicate tile identifier.')
        seen_ids.add(t['id'])
        if not isinstance(t.get('label'), str) or len(t['label']) > 120:
            raise ValueError('Tile labels must be at most 120 characters.')
        if not isinstance(t.get('color'), str) or not re.fullmatch('#[a-fA-F0-9]{6}', t['color']):
            raise ValueError('Choose a valid tile colour.')
        if type(t.get('volume')) not in (int, float) or not math.isfinite(t['volume']) or not 0 <= t['volume'] <= 1:
            raise ValueError('Tile volume must be between 0% and 100%.')
        t['shortcut'] = shortcut(t.get('shortcut', ''))
        if t['shortcut'] and t['shortcut'] in seen_keys:
            raise ValueError(f"{t['shortcut']} is already assigned in this set.")
        seen_keys.add(t['shortcut'])
    return p


class Boards:
    def __init__(self, path, library):
        import json
        self.path, self.library = Path(path), library
        self.lock = threading.RLock()
        self.on_change = None
        if self.path.exists():
            self.data = json.loads(self.path.read_text())
        else:
            first = self.new_profile('My sounds')
            first['tiles'] = [tile(s['id']) for s in library.list()]
            self.data = {'active_id': first['id'], 'profiles': {first['id']: first},
                         'hotkeys_enabled': True, 'stop_shortcut': 'Ctrl+Shift+Space'}
            atomic_json(self.path, self.data)

    @staticmethod
    def new_profile(name):
        return {'id': uuid.uuid4().hex, 'name': name, 'rows': 4, 'columns': 5, 'playback_mode': 'replace', 'tiles': []}

    def snapshot(self):
        with self.lock:
            return deepcopy(self.data)

    def active(self):
        with self.lock:
            return deepcopy(self.data['profiles'][self.data['active_id']])

    def _commit(self, data):
        if not 1 <= len(data['profiles']) <= 100:
            raise ValueError('Keep between 1 and 100 sound sets.')
        for p in data['profiles'].values():
            validate_profile(p)
            if any(t and t['shortcut'] and t['shortcut'] == data['stop_shortcut'] for t in p['tiles']):
                raise ValueError('That shortcut is reserved for Stop all.')
        atomic_json(self.path, data)
        self.data = data
        if self.on_change:
            self.on_change()

    def mutate(self, operation):
        with self.lock:
            data = deepcopy(self.data)
            result = operation(data)
            self._commit(data)
            return deepcopy(result)

    def profile(self, data, profile_id):
        if profile_id not in data['profiles']:
            raise ValueError('That sound set no longer exists.')
        return data['profiles'][profile_id]

    def create(self, name, duplicate_id=None):
        def change(d):
            p = deepcopy(self.profile(d, duplicate_id)) if duplicate_id else self.new_profile(name)
            p['id'], p['name'] = uuid.uuid4().hex, name
            for t in p['tiles']:
                if t:
                    t['id'] = uuid.uuid4().hex
            d['profiles'][p['id']] = p
            d['active_id'] = p['id']
            return p
        return self.mutate(change)

    def update(self, profile_id, changes):
        changes = dict(changes)
        global_changes = {k: changes.pop(k) for k in ('hotkeys_enabled', 'stop_shortcut') if k in changes}
        if 'stop_shortcut' in global_changes:
            global_changes['stop_shortcut'] = shortcut(global_changes['stop_shortcut'])
        def change(d):
            d.update(global_changes)
            self.profile(d, profile_id).update(changes)
        return self.mutate(change)

    def switch(self, profile_id):
        def change(d):
            self.profile(d, profile_id)
            d['active_id'] = profile_id
        self.mutate(change)

    def remove(self, profile_id):
        def change(d):
            self.profile(d, profile_id)
            if len(d['profiles']) == 1:
                raise ValueError('Keep at least one sound set.')
            del d['profiles'][profile_id]
            if d['active_id'] == profile_id:
                d['active_id'] = next(iter(d['profiles']))
        self.mutate(change)

    def set_tile(self, profile_id, index, changes):
        if type(index) is not int or not 0 <= index < 1000:
            raise ValueError('Invalid tile position.')
        def change(d):
            p = self.profile(d, profile_id)
            while len(p['tiles']) <= index:
                p['tiles'].append(None)
            if 'sound_id' in changes and changes['sound_id'] is None:
                p['tiles'][index] = None
            else:
                sound_id = changes.get('sound_id') or (p['tiles'][index] or {}).get('sound_id')
                self.library.get(sound_id)
                t = p['tiles'][index] or tile(sound_id)
                t.update(changes)
                p['tiles'][index] = t
            return p['tiles'][index]
        return self.mutate(change)

    def add(self, sound_id, profile_id=None):
        self.library.get(sound_id)
        def change(d):
            p = self.profile(d, profile_id or d['active_id'])
            index = next((i for i,t in enumerate(p['tiles']) if t is None), len(p['tiles']))
            t = tile(sound_id)
            if index == len(p['tiles']):
                p['tiles'].append(t)
            else:
                p['tiles'][index] = t
            return {'index': index, 'tile': t}
        return self.mutate(change)

    def reorder(self, profile_id, source, target):
        if any(type(i) is not int or not 0 <= i < 1000 for i in (source,target)):
            raise ValueError('Invalid tile positions.')
        def change(d):
            p = self.profile(d, profile_id)
            if source >= len(p['tiles']):
                raise ValueError('The dragged tile no longer exists.')
            while len(p['tiles']) <= target:
                p['tiles'].append(None)
            p['tiles'][source], p['tiles'][target] = p['tiles'][target], p['tiles'][source]
        self.mutate(change)

    def global_settings(self, changes):
        if 'stop_shortcut' in changes:
            changes['stop_shortcut'] = shortcut(changes['stop_shortcut'])
        self.mutate(lambda d: d.update(changes))
