"""Persistence, editor output, set bundles and API playback semantics."""
from array import array
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import wave
import zipfile

from fastapi.testclient import TestClient
from soundboard.server import create_app, NoHotkeys
from soundboard.library import Library
from soundboard.boards import Boards
from soundboard.bundles import import_set, export_set
from test_api import FakeAudio, wav_bytes


class ManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.app = create_app(self.root, audio_factory=FakeAudio, hotkeys_factory=NoHotkeys)
        self.client = TestClient(self.app, base_url='http://127.0.0.1:8765')
        self.client.__enter__()
        self.headers = {'X-Soundboard-Request':'1'}
        self.sound = self.post('/import', files={'file':('sample.wav',wav_bytes())}).json()
        self.library, self.boards = self.app.state.library, self.app.state.boards
        self.profile = self.boards.active()
        self.id = self.sound['id']

    def tearDown(self):
        self.client.__exit__(None,None,None)
        self.temp.cleanup()

    def post(self,path,**kwargs):
        return self.client.post('/api'+path,headers=self.headers,**kwargs)

    def test_trim_is_precise_and_preserves_original(self):
        before = hashlib.sha256(self.library.path(self.id).read_bytes()).digest()
        with wave.open(str(self.library.path(self.id))) as original:
            original_sample = array('h',original.readframes(1))[0]
        result = self.post(f'/sounds/{self.id}/trim',json={'name':'Small clip','start':.02,'end':.08,'gain_db':-6,'fade_in':.01,'fade_out':.01})
        self.assertEqual(result.status_code,200,result.text)
        clip = result.json()
        self.assertNotEqual(clip['id'],self.id)
        self.assertEqual(hashlib.sha256(self.library.path(self.id).read_bytes()).digest(),before)
        with wave.open(str(self.library.path(clip['id']))) as f:
            self.assertEqual(f.getnframes(),2880)
            values = array('h',f.readframes(f.getnframes()))
        self.assertLess(abs(values[0]),5)
        self.assertLess(abs(values[-1]),5)
        self.assertAlmostEqual(values[1440]/original_sample,10**(-6/20),delta=.003)
        self.assertEqual(clip['name'],'Small clip')
        self.assertAlmostEqual(clip['duration'],.06)
        self.assertEqual(self.boards.active()['tiles'][-1]['sound_id'],clip['id'])
        boosted = self.library.save_selection(self.id,'Boosted',start=.02,end=.08,gain_db=12)
        with wave.open(str(self.library.path(boosted['id']))) as f:
            self.assertEqual(f.getnframes(),2880, 'Limiter must compensate its delay')
            boosted_values = array('h',f.readframes(f.getnframes()))
            expected = original_sample * 10**(12/20)
            self.assertAlmostEqual(boosted_values[0],expected,delta=2)
            self.assertAlmostEqual(boosted_values[-1],expected,delta=2)

    def test_invalid_selections_do_not_create_clips(self):
        for values in ({'start':.08,'end':.02},{'start':0,'end':1},{'start':0,'end':.001},
                       {'start':0,'end':.05,'fade_in':.03,'fade_out':.03}):
            result=self.post(f'/sounds/{self.id}/trim',json={'name':'bad',**values})
            self.assertEqual(result.status_code,400,result.text)
        self.assertEqual(len(self.library.list()),1)
        self.assertEqual(self.client.get(f'/api/sounds/{self.id}/waveform?end=nan').status_code,400)
        self.assertEqual(self.client.get(f'/api/sounds/{self.id}/waveform?count=999999').status_code,422)
        peaks=self.client.get(f'/api/sounds/{self.id}/waveform?count=40&start=.02&end=.04').json()['peaks']
        self.assertEqual(len(peaks),40)
        self.assertTrue(all(.04<p<.05 for p in peaks))

    def test_selection_preview_is_local_and_stop_cancels_render(self):
        result=self.post(f'/sounds/{self.id}/preview-selection',json={'start':0,'end':.05})
        self.assertTrue(result.json()['started'])
        self.assertEqual(self.app.state.audio.played[2],'preview')
        started, release = threading.Event(), threading.Event()
        original=self.library.render_selection
        def delayed(*args,**kwargs):
            started.set()
            if not release.wait(3):raise AssertionError('Test render did not resume')
            return original(*args,**kwargs)
        self.library.render_selection=delayed
        responses=[]
        worker=threading.Thread(target=lambda:responses.append(self.post(f'/sounds/{self.id}/preview-selection',json={'start':0,'end':.05})))
        worker.start()
        try:
            self.assertTrue(started.wait(3))
            self.assertEqual(self.post('/stop').status_code,200)
        finally:
            release.set();worker.join(4)
        self.assertFalse(responses[0].json()['started'])
        self.assertIsNone(self.app.state.audio.played)

    def test_trash_restore_rename_and_sample_reimport(self):
        self.post(f'/sounds/{self.id}/rename',json={'name':'My renamed sound'})
        self.assertEqual(self.post(f'/sounds/{self.id}/trash').status_code,200)
        self.assertEqual(self.library.list(),[])
        self.assertEqual(self.boards.active()['tiles'][0]['sound_id'],self.id)
        self.assertEqual(self.post('/play',json={'sound_id':self.id,'mode':'preview'}).status_code,400)
        samples=self.root/'sound-files';samples.mkdir();(samples/'sample.wav').write_bytes(wav_bytes())
        self.post('/samples/import')
        self.assertEqual(self.library.list(),[], 'Bulk sample import must not resurrect trashed sounds')
        self.assertEqual(self.post(f'/sounds/{self.id}/restore').status_code,200)
        persisted=Library(self.root/'.state/library',samples)
        self.assertEqual(persisted.get(self.id)['name'],'My renamed sound')
        self.assertTrue(persisted.path(self.id).is_file())
        self.assertEqual(self.boards.active()['tiles'][0]['sound_id'],self.id)

    def test_grid_settings_persist_and_resize_keeps_assignments(self):
        pid=self.profile['id']
        self.boards.set_tile(pid,25,{'sound_id':self.id,'shortcut':'Alt+Ctrl+2','volume':.4})
        result=self.post(f'/sets/{pid}/settings',json={'rows':1,'columns':2,'name':'Game night','playback_mode':'overlap','hotkeys_enabled':False,'stop_shortcut':'Ctrl+Alt+Space'})
        self.assertEqual(result.status_code,200,result.text)
        loaded=Boards(self.root/'.state/sets.json',self.library)
        self.assertEqual(loaded.active()['tiles'][25]['shortcut'],'Ctrl+Alt+2')
        self.assertFalse(loaded.snapshot()['hotkeys_enabled'])
        self.assertEqual(loaded.active()['rows'],1)
        self.assertEqual(loaded.active()['name'],'Game night')
        t=loaded.active()['tiles'][25]
        response=self.post('/play',json={'sound_id':self.id,'tile_id':t['id'],'mode':'preview'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.app.state.audio.options['volume'],.4)
        self.assertTrue(self.app.state.audio.options['overlap'])
        self.post(f'/sets/{pid}/move',json={'source':25,'target':1})
        self.assertEqual(self.boards.active()['tiles'][1]['id'],t['id'])
        self.assertIsNone(self.boards.active()['tiles'][25])
        self.post(f'/sets/{pid}/tiles/1',json={'sound_id':None})
        self.assertEqual(len(self.library.list()),1, 'Removing a tile keeps shared audio')

    def test_shortcut_conflicts_roll_back_whole_settings_change(self):
        pid=self.profile['id']
        self.boards.set_tile(pid,0,{'shortcut':'Ctrl+1'})
        for body in ({'sound_id':self.id,'shortcut':'Ctrl+1'},{'sound_id':self.id,'shortcut':'Ctrl+Shift+Space'}):
            response=self.post(f'/sets/{pid}/tiles/1',json=body)
            self.assertEqual(response.status_code,400,response.text)
        before=self.boards.snapshot()
        result=self.post(f'/sets/{pid}/settings',json={'name':'Should roll back','stop_shortcut':'Ctrl+1'})
        self.assertEqual(result.status_code,400,result.text)
        self.assertEqual(self.boards.snapshot(),before)
        self.assertEqual(self.post(f'/sets/{pid}/tiles/0',json={'shortcut':'1'}).status_code,400)

    def test_duplicate_switch_and_bundle_round_trip(self):
        pid=self.profile['id']
        self.boards.set_tile(pid,0,{'shortcut':'Ctrl+1','label':'Hello','color':'#abcdef','volume':.6})
        duplicate=self.post('/sets',json={'name':'Another session','duplicate_id':pid}).json()
        self.assertNotEqual(duplicate['tiles'][0]['id'],self.boards.snapshot()['profiles'][pid]['tiles'][0]['id'])
        self.boards.set_tile(duplicate['id'],0,{'label':'Changed'})
        self.assertEqual(self.boards.snapshot()['profiles'][pid]['tiles'][0]['label'],'Hello')
        self.post(f'/sets/{pid}/switch')
        response=self.client.get(f'/api/sets/{pid}/export')
        self.assertEqual(response.status_code,200)
        archive=self.root/'bundle.zip';archive.write_bytes(response.content)
        other_lib=Library(self.root/'other-library',self.root/'empty-samples')
        other_boards=Boards(self.root/'other-sets.json',other_lib)
        imported=import_set(other_boards,other_lib,archive)
        self.assertEqual(imported['tiles'][0]['label'],'Hello')
        self.assertEqual(imported['tiles'][0]['shortcut'],'Ctrl+1')
        self.assertEqual(imported['tiles'][0]['volume'],.6)
        self.assertEqual(other_lib.get(self.id)['duration'],.1)
        with wave.open(str(other_lib.path(self.id))) as a,wave.open(str(self.library.path(self.id))) as b:
            self.assertEqual(a.readframes(a.getnframes()),b.readframes(b.getnframes()))
        # Reimporting the same audio should not multiply copies despite metadata differences.
        import_set(other_boards,other_lib,archive)
        self.assertEqual(len(other_lib.list()),1)
        result=self.post('/sets/import',files={'file':('session.zip',response.content)})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(self.boards.active()['id'],result.json()['id'])

    def test_invalid_bundle_cannot_partially_publish_or_extract_paths(self):
        bundle=self.root/'good.zip';export_set(self.boards,self.library,self.profile['id'],bundle)
        with zipfile.ZipFile(bundle) as z:
            files={n:z.read(n) for n in z.namelist()}
        for variant in ('traversal','broken-audio','bad-filename'):
            entries=dict(files)
            if variant=='traversal':entries['../../escaped']=b'no'
            elif variant=='broken-audio':entries[f'audio/{self.id}.wav']=b'broken'
            else:
                manifest=json.loads(entries['manifest.json']);manifest['sounds'][0]['filename']={}
                entries['manifest.json']=json.dumps(manifest).encode()
            invalid=self.root/'invalid.zip'
            with zipfile.ZipFile(invalid,'w') as z:
                for name,data in entries.items():z.writestr(name,data)
            before=self.boards.snapshot(),deepcopy(self.library.items)
            with self.assertRaises(ValueError):import_set(self.boards,self.library,invalid)
            self.assertEqual((self.boards.snapshot(),self.library.items),before)
        self.assertFalse((self.root.parent/'escaped').exists())

if __name__=='__main__':unittest.main()
