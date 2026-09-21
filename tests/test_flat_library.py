"""Readable originals, safe collision handling and migration of existing collections."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from soundboard.library import Library, atomic_json
from soundboard.boards import Boards
from test_api import wav_bytes


class FlatLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.samples = self.root/'samples'; self.samples.mkdir()
        self.directory = self.root/'library'
        self.wav = self.root/'source.wav'; self.wav.write_bytes(wav_bytes())

    def tearDown(self):
        self.temp.cleanup()

    def test_original_mp3_bytes_and_name_survive_import_and_cache_rebuild(self):
        source = self.samples/'Goose_honk - Hello!.mp3'
        subprocess.run(['ffmpeg','-v','error','-i',str(self.wav),str(source)],check=True)
        library = Library(self.directory)
        sound = library.import_file(source,source.name)
        self.assertEqual(sound['stored_file'],source.name)
        self.assertEqual((self.directory/source.name).read_bytes(),source.read_bytes())
        self.assertEqual(library.path(sound['id']).parent,self.directory/'.cache')
        self.assertFalse((self.directory/sound['id']).exists())
        before = library.path(sound['id']).read_bytes()
        library.path(sound['id']).unlink()
        self.assertEqual(library.path(sound['id']).read_bytes(),before)
        self.assertEqual(library.import_file(source,'different.mp3')['id'],sound['id'])
        self.assertEqual(len(library.list()),1)

    def test_collisions_unsafe_names_and_edits_never_overwrite_other_files(self):
        library = Library(self.directory)
        existing = self.directory/'Hello.wav'; existing.write_bytes(b'Keep me')
        first = library.import_file(self.wav,'Hello.wav')
        self.assertEqual(first['stored_file'],'Hello (2).wav')
        edited = library.save_selection(first['id'],'Hello',start=0,end=.05)
        self.assertEqual(edited['stored_file'],'Hello (3).wav')
        self.assertEqual(library.path(edited['id']),self.directory/'Hello (3).wav')
        self.assertEqual(existing.read_bytes(),b'Keep me')
        clip = library.save_selection(first['id'],'../../Another clip',start=0,end=.05)
        self.assertEqual(clip['stored_file'],'Another clip.wav')
        self.assertTrue(all(p.name=='.cache' for p in self.directory.iterdir() if p.is_dir()))
        library.rename(first['id'],'My title')
        library.trash(first['id']); library.trash(first['id'],restore=True)
        reopened = Library(self.directory)
        self.assertEqual(reopened.get(first['id'])['name'],'My title')
        self.assertEqual((self.directory/first['stored_file']).read_bytes(),self.wav.read_bytes())

    def test_legacy_upgrade_keeps_audio_ids_titles_trash_and_set_assignments(self):
        self.directory.mkdir()
        present = self.samples/'Original_Name.wav'; present.write_bytes(self.wav.read_bytes())
        first_id = hashlib.sha256(present.read_bytes()).hexdigest()[:24]
        missing_id = 'a'*24
        items = {
            first_id: {'id':first_id,'name':'Custom title','filename':present.name,'duration':.1},
            missing_id: {'id':missing_id,'name':'Missing original','filename':'Missing original.mp3','duration':.1,'trashed':True},
        }
        for sound_id in items:
            folder=self.directory/sound_id; folder.mkdir(); (folder/'audio.wav').write_bytes(self.wav.read_bytes())
        atomic_json(self.directory/'library.json',items)
        # A saved tile refers to an ID, independently of the file's storage path.
        sets=self.root/'sets.json'
        atomic_json(sets, {'untouched':'Saved board bytes'})
        before=sets.read_bytes()
        library=Library(self.directory,legacy_originals=self.samples)
        self.assertEqual(set(library.items),set(items))
        for sid,old in items.items():
            self.assertEqual({k:library.items[sid][k] for k in old},old)
            self.assertEqual(library.path(sid,include_trash=True).read_bytes(),self.wav.read_bytes())
            self.assertFalse((self.directory/sid).exists())
        self.assertEqual((self.directory/present.name).read_bytes(),present.read_bytes())
        self.assertTrue((self.directory/'Missing original.wav').exists())
        self.assertEqual(sets.read_bytes(),before)
        stable=deepcopy(library.items)
        self.assertEqual(Library(self.directory).items,stable)
        boards=Boards(self.root/'actual-sets.json',library)
        boards.set_tile(boards.active()['id'],0,{'sound_id':first_id,'shortcut':'Ctrl+1'})
        self.assertEqual(Boards(self.root/'actual-sets.json',Library(self.directory)).active()['tiles'][0]['sound_id'],first_id)

    def test_failed_metadata_commit_rolls_back_import_and_migration(self):
        library=Library(self.directory)
        with patch('soundboard.library.atomic_json',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):library.import_file(self.wav,'Keep_Name.wav')
        self.assertEqual(library.items,{})
        self.assertEqual([p for p in self.directory.rglob('*') if p.is_file()],[])
        sid='a'*24; legacy=self.directory/sid; legacy.mkdir()
        (legacy/'audio.wav').write_bytes(self.wav.read_bytes())
        items={sid:{'id':sid,'name':'Legacy','filename':'Legacy.mp3','duration':.1}}
        atomic_json(self.directory/'library.json',items)
        with patch('soundboard.library.atomic_json',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):Library(self.directory)
        self.assertEqual(json.loads((self.directory/'library.json').read_text()),items)
        self.assertEqual((legacy/'audio.wav').read_bytes(),self.wav.read_bytes())
        self.assertFalse((self.directory/'Legacy.wav').exists())
        self.assertTrue(Library(self.directory).path(sid).is_file())


if __name__=='__main__':unittest.main()
