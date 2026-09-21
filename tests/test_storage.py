from pathlib import Path
import json
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from soundboard.storage import Storage, MOVED_MARKER, browse_folders
from soundboard.library import Library, atomic_json
from soundboard.boards import Boards
from soundboard.server import create_app, NoHotkeys
from test_api import FakeAudio, wav_bytes


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.project=self.root/'project';self.project.mkdir()
        self.config=self.root/'config/tuxcue/storage.json'
        self.default=self.root/'home/TuxCue'
        self.source=self.project/'.state'
        self.lib=Library(self.source/'library')
        wav=self.root/'sample.wav';wav.write_bytes(wav_bytes())
        self.sound=self.lib.import_file(wav,'sample.wav')
        self.boards=Boards(self.source/'sets.json',self.lib)
        self.boards.set_tile(self.boards.active()['id'],0,{'shortcut':'Ctrl+1'})
        atomic_json(self.source/'audio-settings.json',{'microphone':'chosen-mic','monitor_volume':.4})
        self.storage=None

    def tearDown(self):
        if self.storage:self.storage.close()
        self.temp.cleanup()

    def open(self):
        self.storage=Storage.open(self.project,config_file=self.config,default_directory=self.default)
        return self.storage

    def test_upgrade_keeps_original_and_remembers_new_location(self):
        original=self.lib.path(self.sound['id']).read_bytes()
        store=self.open()
        self.assertEqual(store.directory,self.default)
        self.assertEqual(self.lib.path(self.sound['id']).read_bytes(),original)
        self.assertEqual(Library(self.default/'library').path(self.sound['id']).read_bytes(),original)
        self.assertEqual(json.loads((self.default/'sets.json').read_text())['active_id'],self.boards.active()['id'])
        self.assertTrue((self.source/MOVED_MARKER).exists())
        self.assertEqual(json.loads(self.config.read_text())['folder'],str(self.default))
        self.storage.close();self.open()
        self.assertEqual(self.storage.directory,self.default)
        with self.assertRaisesRegex(ValueError,'backup'):
            Storage(self.source,self.config,self.default)

    def test_busy_destination_nonempty_nested_and_failed_config_leave_source_active(self):
        store=self.open()
        occupied=self.root/'occupied';occupied.mkdir();(occupied/'keep.txt').write_text('precious')
        for destination in (occupied,self.default/'nested',self.default.parent):
            with self.assertRaises(ValueError):store.relocate(destination)
        self.assertEqual((occupied/'keep.txt').read_text(),'precious')
        def fail_preference(path,value):
            if path==self.config:raise OSError('disk full')
            atomic_json(path,value)
        with patch('soundboard.storage.atomic_json',side_effect=fail_preference):
            with self.assertRaises(ValueError):store.relocate(self.root/'failed')
        self.assertFalse((self.root/'failed').exists())
        self.assertFalse((self.default/MOVED_MARKER).exists())
        self.assertEqual(store.directory,self.default)
        self.assertEqual(json.loads(self.config.read_text())['folder'],str(self.default))

    def test_verification_failure_does_not_switch_or_mark_original(self):
        store=self.open()
        from soundboard.storage import fingerprint
        def corrupted(path):
            values=fingerprint(path)
            if path.name.startswith('.tuxcue-copy-'):values['extra']='bad'
            return values
        with patch('soundboard.storage.fingerprint',side_effect=corrupted):
            with self.assertRaisesRegex(ValueError,'verify'):store.relocate(self.root/'bad-copy')
        self.assertEqual(store.directory,self.default)
        self.assertFalse((self.default/MOVED_MARKER).exists())
        self.assertFalse((self.root/'bad-copy').exists())

    def test_lock_moves_with_folder_and_missing_drive_never_creates_empty_library(self):
        store=self.open()
        target=self.root/'new collection'
        store.relocate(target)
        with self.assertRaisesRegex(ValueError,'already open'):
            Storage.open(self.project,config_file=self.config,default_directory=self.default)
        store.close();self.storage=None
        target.rename(self.root/'disconnected-drive')
        with self.assertRaisesRegex(ValueError,'unavailable'):
            self.open()
        self.assertFalse(target.exists())

    def test_restart_recovers_location_after_interrupted_preference_commit(self):
        store=self.open()
        target=self.root/'recovered'
        store.relocate(target)
        store.close();self.storage=None
        atomic_json(self.config,{'folder':str(self.default)})
        self.open()
        self.assertEqual(self.storage.directory,target)
        self.assertEqual(json.loads(self.config.read_text())['folder'],str(target))

    def test_api_moves_live_references_and_subsequent_edits_persist_there(self):
        store=self.open()
        class Audio(FakeAudio):
            def __init__(self,directory):
                super().__init__(directory);self.lock=threading.RLock()
        app=create_app(self.project,store.directory,audio_factory=Audio,hotkeys_factory=NoHotkeys,storage=store)
        headers={'X-Soundboard-Request':'1'}
        target=self.root/'with spaces/new TuxCue'
        with TestClient(app,base_url='http://127.0.0.1:8765') as client:
            response=client.post('/api/storage',json={'folder':str(target)},headers=headers)
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(app.state.audio.module_file,target/'audio-session.json')
            self.assertEqual(client.get('/api/state').json()['storage']['folder'],str(target))
            response=client.post(f"/api/sounds/{self.sound['id']}/rename",json={'name':'Moved sound'},headers=headers)
            self.assertEqual(response.status_code,200,response.text)
            response=client.post(f"/api/sounds/{self.sound['id']}/trim",json={'name':'Edited after move','start':0,'end':.05},headers=headers)
            self.assertEqual(response.status_code,200,response.text)
            self.assertTrue((target/'library'/'Edited after move.wav').exists())
            self.assertEqual(client.post('/api/storage',json={'folder':str(self.root/'denied')}).status_code,403)
        saved=Library(target/'library')
        self.assertEqual(saved.get(self.sound['id'])['name'],'Moved sound')
        self.assertEqual(Library(self.default/'library').get(self.sound['id'])['name'],'sample')
        self.assertEqual(browse_folders(target.parent)['folders'],['new TuxCue'])

if __name__=='__main__':unittest.main()
