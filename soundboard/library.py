"""Owned audio library. Never edits files in the supplied sample directory."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import uuid
import wave
from array import array

EXTENSIONS = {".mp3", ".wav", ".flac", ".ogg", ".opus", ".m4a", ".aac", ".aiff", ".wma"}
FORMATS = "mp3,wav,flac,ogg,mov,aac,aiff,asf"
MAX_BYTES = 100 * 1024 * 1024
MAX_SECONDS = 600


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as f:
        tmp = Path(f.name)
        json.dump(value, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def readable_filename(value):
    # Imports may supply Windows paths. Preserve ordinary punctuation, spaces and
    # underscores, while keeping every owned file directly inside the library.
    name = str(value).replace('\\', '/').rsplit('/', 1)[-1]
    name = re.sub(r'[\x00-\x1f\x7f]', '_', name).lstrip('.').strip() or 'Untitled.wav'
    suffix = Path(name).suffix
    stem = name[:-len(suffix)] if suffix else name
    while len((stem + suffix).encode('utf-8')) > 220:
        stem = stem[:-1]
    return (stem or 'Untitled') + suffix


class Library:
    def __init__(self, directory: Path, samples: Path):
        self.directory = directory
        self.samples = samples.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.index = directory / "library.json"
        self.lock = threading.RLock()
        self.items = json.loads(self.index.read_text()) if self.index.exists() else {}
        self._migrate_legacy_files()

    def _collection_path(self, relative):
        parts = Path(relative).parts
        if not (len(parts) == 1 or (len(parts) == 2 and parts[0] == '.cache')) or any(p in ('.', '..', '/') for p in parts):
            raise ValueError('The library contains an invalid saved audio path.')
        path = self.directory / relative
        if path.is_symlink() or path.parent.is_symlink():
            raise ValueError('Saved audio files must not be symbolic links.')
        return path

    def _pcm_path(self, item):
        if 'pcm_file' in item:
            return self._collection_path(item['pcm_file'])
        if not re.fullmatch('[a-f0-9]{24}', item['id']):
            raise ValueError('The library contains an invalid sound identifier.')
        return self.directory / item['id'] / 'audio.wav'

    def _publish_copy(self, source, folder, filename):
        folder.mkdir(parents=True, exist_ok=True)
        if folder.is_symlink():
            raise ValueError('The audio folder must not be a symbolic link.')
        filename = readable_filename(filename)
        base = Path(filename)
        occupied = {p.name.casefold() for p in folder.iterdir()}
        # A complete temporary copy is linked into place exclusively, so even an
        # unrelated file created during import can never be overwritten.
        with tempfile.NamedTemporaryFile(dir=folder, prefix='.import-', delete=False) as temp:
            temporary = Path(temp.name)
        try:
            shutil.copyfile(source, temporary)
            if hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(temporary.read_bytes()).digest():
                raise ValueError('The copied audio did not verify. The original is unchanged.')
            with temporary.open('rb') as copied:
                os.fsync(copied.fileno())
            number = 1
            while True:
                name = filename if number == 1 else f'{base.stem} ({number}){base.suffix}'
                candidate = folder / name
                if name.casefold() not in occupied:
                    try:
                        os.link(temporary, candidate)
                        return candidate
                    except FileExistsError:
                        occupied.add(name.casefold())
                number += 1
        finally:
            temporary.unlink(missing_ok=True)

    def store_audio(self, item, source, pcm, filename):
        """Publish a named original and, when needed, a separate playback cache."""
        with self.lock:
            created = []
            try:
                original = self._publish_copy(source, self.directory, filename)
                created.append(original)
                playback = original
                if source != pcm:
                    playback = self._publish_copy(pcm, self.directory / '.cache', item['id'] + '.wav')
                    created.append(playback)
                saved = {**item, 'stored_file': original.name,
                         'pcm_file': str(playback.relative_to(self.directory))}
                updated = {**self.items, item['id']: saved}
                atomic_json(self.index, updated)
                self.items = updated
                return dict(saved)
            except Exception:
                for path in created:
                    path.unlink(missing_ok=True)
                raise

    def _migrate_legacy_files(self):
        for sound_id, item in list(self.items.items()):
            if not re.fullmatch('[a-f0-9]{24}', sound_id):
                raise ValueError('The library contains an invalid sound identifier.')
            legacy = self.directory / sound_id / 'audio.wav'
            if not legacy.is_file():
                continue
            if legacy.is_symlink() or legacy.parent.is_symlink():
                raise ValueError('Saved audio files must not be symbolic links.')
            if 'stored_file' not in item:
                filename = readable_filename(item.get('filename', item['name'] + '.wav'))
                original = self.samples / filename
                if (not item.get('source_id') and original.is_file() and not original.is_symlink()
                        and hashlib.sha256(original.read_bytes()).hexdigest()[:24] == sound_id):
                    item = self.store_audio(item, original, legacy, filename)
                else:
                    # Older versions retained only PCM. Keep those exact samples
                    # when the imported original is no longer available.
                    item = self.store_audio(item, legacy, legacy, Path(filename).stem + '.wav')
            playback = self._pcm_path(item)
            if playback.is_file() and hashlib.sha256(playback.read_bytes()).digest() == hashlib.sha256(legacy.read_bytes()).digest():
                legacy.unlink()
                try:
                    legacy.parent.rmdir()
                except OSError:
                    pass  # Never remove unrelated files inside an old directory.

    def list(self, trashed=False):
        with self.lock:
            return sorted((dict(i) for i in self.items.values() if bool(i.get('trashed')) == trashed), key=lambda item: item["name"].casefold())

    def get(self, sound_id, include_trash=False):
        with self.lock:
            item = self.items.get(sound_id)
            if not item or (item.get('trashed') and not include_trash):
                raise ValueError('That sound is no longer in the library.')
            return dict(item)

    def rename(self, sound_id, name):
        name = name.strip()
        if not name or len(name) > 120:
            raise ValueError('Sound names must contain 1–120 characters.')
        with self.lock:
            self.get(sound_id)
            self.items[sound_id] = {**self.items[sound_id], 'name': name}
            atomic_json(self.index, self.items)
            return dict(self.items[sound_id])

    def trash(self, sound_id, restore=False):
        with self.lock:
            self.get(sound_id, include_trash=True)
            self.items[sound_id] = {**self.items[sound_id], 'trashed': not restore}
            atomic_json(self.index, self.items)
            return dict(self.items[sound_id])

    def path(self, sound_id: str, include_trash=False) -> Path:
        with self.lock:
            item = self.get(sound_id, include_trash=include_trash)
            path = self._pcm_path(item)
            if not path.is_file() and item.get('pcm_file', '').startswith('.cache/'):
                original = self._collection_path(item['stored_file'])
                if original.is_file():
                    with tempfile.TemporaryDirectory(dir=self.directory) as temp:
                        output = Path(temp) / 'audio.wav'
                        self._decode(original, output)
                        path = self._publish_copy(output, self.directory / '.cache', item['id'] + '.wav')
                        updated = {**self.items, sound_id: {**item, 'pcm_file': str(path.relative_to(self.directory))}}
                        try:
                            atomic_json(self.index, updated)
                        except Exception:
                            path.unlink(missing_ok=True)
                            raise
                        self.items = updated
            if not path.is_file():
                raise ValueError("The saved audio file is missing. Import the sound again.")
            return path

    @staticmethod
    def _decode(source, output):
        try:
            subprocess.run([
                'ffmpeg', '-v', 'error', '-nostdin', '-protocol_whitelist', 'file,pipe',
                '-format_whitelist', FORMATS, '-i', str(source), '-map', '0:a:0', '-vn',
                '-t', str(MAX_SECONDS), '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', str(output),
            ], capture_output=True, text=True, timeout=90, check=True)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            raise ValueError('The audio file could not be decoded. Try importing it again.') from error

    def sample_names(self):
        if not self.samples.is_dir():
            return []
        return sorted(p.name for p in self.samples.iterdir()
                      if p.is_file() and not p.is_symlink() and p.suffix.lower() in EXTENSIONS)

    def import_sample(self, name: str):
        if name not in self.sample_names():
            raise ValueError("Choose a sound from the sample folder.")
        return self.import_file(self.samples / name, name, restore=False)

    def import_file(self, path: Path, filename: str, restore=True, max_bytes=MAX_BYTES):
        # Hashing and conversion run outside the metadata lock; publishing is atomic.
        if Path(filename).suffix.lower() not in EXTENSIONS:
            raise ValueError("Choose an MP3, WAV, FLAC, OGG, OPUS, M4A, AAC, AIFF or WMA file.")
        if path.stat().st_size > max_bytes:
            raise ValueError("Audio files must be smaller than 100 MB.")
        sound_id = hashlib.sha256(path.read_bytes()).hexdigest()[:24]
        with self.lock:
            if sound_id in self.items and self._pcm_path(self.items[sound_id]).is_file():
                if restore and self.items[sound_id].get('trashed'):
                    return self.trash(sound_id, restore=True)
                return dict(self.items[sound_id])
        try:
            probe = subprocess.run([
                "ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe",
                "-format_whitelist", FORMATS, "-show_entries", "format=duration:stream=codec_type",
                "-of", "json", str(path),
            ], capture_output=True, text=True, timeout=20, check=True)
            metadata = json.loads(probe.stdout)
            duration = float(metadata.get("format", {}).get("duration", "nan"))
            if not math.isfinite(duration) or not 0 < duration <= MAX_SECONDS:
                raise ValueError("Choose an audio file between 0 and 10 minutes long.")
            if not any(s.get("codec_type") == "audio" for s in metadata.get("streams", [])):
                raise ValueError("This file does not contain audio.")
            with tempfile.TemporaryDirectory(dir=self.directory) as temp:
                output = Path(temp) / "audio.wav"
                self._decode(path, output)
                with wave.open(str(output)) as audio:
                    duration = audio.getnframes() / audio.getframerate()
                item = {"id": sound_id, "name": re.sub(r"[_\s]+", " ", Path(filename).stem).strip()[:120] or "Untitled sound",
                        "filename": Path(filename).name, "duration": duration}
                with self.lock:
                    # Two concurrent decodes of one source share one library item.
                    if sound_id in self.items and self._pcm_path(self.items[sound_id]).is_file():
                        if restore and self.items[sound_id].get('trashed'):
                            return self.trash(sound_id, restore=True)
                        return dict(self.items[sound_id])
                    return self.store_audio(item, path, output, filename)
        except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError) as e:
            raise ValueError("The audio file could not be decoded. Try a different file.") from e
        except subprocess.TimeoutExpired as e:
            raise ValueError("Audio conversion took too long. Try a shorter clip.") from e

    def waveform(self, sound_id: str, count=96, start=0.0, end=None):
        if not math.isfinite(start) or (end is not None and not math.isfinite(end)):
            raise ValueError('Enter finite waveform positions.')
        peaks = []
        with wave.open(str(self.path(sound_id))) as audio:
            rate = audio.getframerate()
            total = audio.getnframes()
            first = max(0, min(total, round(start * rate)))
            last = total if end is None else max(first, min(total, round(end * rate)))
            audio.setpos(first)
            remaining = last - first
            chunk = max(1, math.ceil(remaining / count))
            while remaining and (data := audio.readframes(min(chunk, remaining))):
                remaining -= len(data) // (audio.getnchannels() * audio.getsampwidth())
                values = array("h", data)
                import sys
                if sys.byteorder != "little":
                    values.byteswap()
                peaks.append(max(abs(n) for n in values) / 32768)
        return peaks

    def render_selection(self, sound_id, destination, *, start, end, gain_db=0.0, fade_in=0.0, fade_out=0.0):
        path = self.path(sound_id)
        with wave.open(str(path)) as audio:
            rate, frames = audio.getframerate(), audio.getnframes()
        values = (start, end, gain_db, fade_in, fade_out)
        if not all(math.isfinite(v) for v in values):
            raise ValueError('Enter finite selection and volume values.')
        if not 0 <= start < end <= frames / rate + 0.000001:
            raise ValueError('Selection must start before it ends and stay within the sound.')
        first, last = round(start * rate), min(frames, round(end * rate))
        duration = (last - first) / rate
        if duration < .01:
            raise ValueError('Select at least 0.01 seconds of audio.')
        if not -24 <= gain_db <= 12 or min(fade_in, fade_out) < 0 or fade_in + fade_out > duration + .000001:
            raise ValueError('Use gain between −24 and +12 dB; fades must fit inside the selection.')
        filters = [f'atrim=start_sample={first}:end_sample={last}', 'asetpts=PTS-STARTPTS', f'volume={gain_db}dB']
        if fade_in:
            filters.append(f'afade=t=in:d={fade_in}')
        if fade_out:
            filters.append(f'afade=t=out:st={duration-fade_out}:d={fade_out}')
        # Pad and trim the limiter's 5 ms look-ahead explicitly. This also works
        # with FFmpeg 4.4, whose limiter has no automatic latency compensation.
        if gain_db > 0:
            delay = max(0, int(rate * .005) - 1)
            filters.extend([f'apad=pad_len={delay}', 'alimiter=limit=0.98:level=false:attack=5',
                            f'atrim=start_sample={delay}:end_sample={delay + last - first}', 'asetpts=PTS-STARTPTS'])
        try:
            subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-i', str(path), '-af', ','.join(filters),
                            '-c:a', 'pcm_s16le', str(destination)], capture_output=True, text=True, timeout=90, check=True)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            raise ValueError('Could not render this selection. Try a shorter clip.') from e
        return duration

    def save_selection(self, sound_id, name, **settings):
        name = name.strip()
        if not name or len(name) > 120:
            raise ValueError('Give the new clip a name of 1–120 characters.')
        with tempfile.TemporaryDirectory(dir=self.directory) as temp:
            output = Path(temp) / 'audio.wav'
            duration = self.render_selection(sound_id, output, **settings)
            new_id = uuid.uuid4().hex[:24]
            item = {'id': new_id, 'name': name, 'filename': name + '.wav', 'duration': duration,
                    'source_id': sound_id, 'edit': settings}
            return self.store_audio(item, output, output, name + '.wav')
