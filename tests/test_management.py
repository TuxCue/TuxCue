"""Persistence, editor output, set bundles and API playback semantics."""
from array import array
from copy import deepcopy
import hashlib
import io
import json
import subprocess
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

    def test_remove_section_joins_audio_and_preserves_original(self):
        recording = io.BytesIO()
        # Distinct stereo sections make a missing segment, gap, or channel swap visible.
        with wave.open(recording, 'wb') as audio:
            audio.setparams((2, 2, 48000, 0, 'NONE', 'not compressed'))
            audio.writeframes(array('h', [1000, -2000] * 1440 + [0, 0] * 1920 +
                                    [-3000, 4000] * 1440).tobytes())
        sound = self.post('/import', files={'file': ('sections.wav', recording.getvalue())}).json()
        original_path = self.library.path(sound['id'])
        original_file = original_path.read_bytes()
        with wave.open(str(original_path)) as audio:
            width = audio.getnchannels() * audio.getsampwidth()
            original = audio.readframes(audio.getnframes())
        for start, end in ((.03, .07), (0, .07), (.03, .1)):
            with self.subTest(start=start, end=end):
                settings = {'start': start, 'end': end, 'operation': 'remove'}
                result = self.post(f'/sounds/{sound["id"]}/trim', json={'name': 'Joined', **settings})
                self.assertEqual(result.status_code, 200, result.text)
                clip = result.json()
                first, last = round(start * 48000), round(end * 48000)
                expected = original[:first * width] + original[last * width:]
                with wave.open(str(self.library.path(clip['id']))) as audio:
                    self.assertEqual(audio.getnframes(), len(expected) // width)
                    self.assertEqual(audio.readframes(audio.getnframes()), expected)
                self.assertAlmostEqual(clip['duration'], .1 - (end - start))
                self.assertEqual(clip['source_id'], sound['id'])
                preview = self.post(f'/sounds/{sound["id"]}/preview-selection', json=settings)
                self.assertTrue(preview.json()['started'], preview.text)
                preview_path, _, mode = self.app.state.audio.played
                self.assertEqual(mode, 'preview')
                with wave.open(str(preview_path)) as audio:
                    self.assertEqual(audio.readframes(audio.getnframes()), expected)
        self.assertEqual(original_path.read_bytes(), original_file)

    def test_remove_section_applies_fades_and_limiter_to_result(self):
        clip = self.library.save_selection(self.id, 'Joined fades', start=.03, end=.07,
                                          operation='remove', gain_db=12, fade_in=.025, fade_out=.025)
        # Fades total more than the removed section; they must fit the retained audio.
        with wave.open(str(self.library.path(clip['id']))) as audio:
            self.assertEqual(audio.getnframes(), 2880)
            samples = array('h', audio.readframes(audio.getnframes()))
            self.assertLess(abs(samples[0]), 5)
            self.assertLess(abs(samples[-1]), 10)
            self.assertGreater(abs(samples[len(samples) // 2]), 5000)

    def test_working_cuts_update_waveform_and_preview_without_saving(self):
        recording = io.BytesIO()
        with wave.open(recording, 'wb') as audio:
            audio.setparams((2, 2, 48000, 0, 'NONE', 'not compressed'))
            audio.writeframes(array('h', [1000, -2000] * 960 + [0, 0] * 960 +
                                    [-3000, 4000] * 960 + [0, 0] * 960 + [5000, -6000] * 960).tobytes())
        sound = self.post('/import', files={'file': ('working.wav', recording.getvalue())}).json()
        path = self.library.path(sound['id'])
        before = path.read_bytes()
        with wave.open(str(path)) as audio:
            original = audio.readframes(audio.getnframes())
        segment = lambda first, last: {'start_frame': first, 'end_frame': last}
        plans = ([segment(0, 960), segment(1920, 4800)],
                 [segment(0, 960), segment(1920, 2880), segment(3840, 4800)])
        tiles = deepcopy(self.boards.active()['tiles'])
        for plan in plans:
            expected = b''.join(original[s['start_frame'] * 4:s['end_frame'] * 4] for s in plan)
            result = self.post(f'/sounds/{sound["id"]}/editing-waveform', json={'segments': plan, 'count': 16})
            self.assertEqual(result.status_code, 200, result.text)
            metadata = result.json()
            self.assertEqual(metadata['frames'], len(expected) // 4)
            self.assertEqual(metadata['sample_rate'], 48000)
            values = {'segments': plan, 'start': 0, 'end': metadata['duration']}
            preview = self.post(f'/sounds/{sound["id"]}/preview-selection', json=values)
            self.assertTrue(preview.json()['started'], preview.text)
            preview_path, _, mode = self.app.state.audio.played
            self.assertEqual(mode, 'preview')
            with wave.open(str(preview_path)) as audio:
                self.assertEqual(audio.readframes(audio.getnframes()), expected)
            self.assertEqual(len(self.library.list()), 2, 'Working cuts must not add library sounds')
            self.assertEqual(self.boards.active()['tiles'], tiles)
        self.assertTrue(all(p > 0 for p in metadata['peaks']), 'Both silent sections were removed')
        saved = self.post(f'/sounds/{sound["id"]}/trim', json={'name': 'Final edit', **values})
        self.assertEqual(saved.status_code, 200, saved.text)
        with wave.open(str(self.library.path(saved.json()['id']))) as audio:
            self.assertEqual(audio.readframes(audio.getnframes()), expected)
        self.assertEqual(len(self.library.list()), 3)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.library.directory.glob('tmp*')), [], 'Working files must be cleaned up')

    def test_invalid_working_plans_are_rejected_and_cleaned_up(self):
        for segments in ([], [{'start_frame': 0, 'end_frame': 999999}],
                         [{'start_frame': 0, 'end_frame': 1}],
                         [{'start_frame': 0, 'end_frame': 2400}, {'start_frame': 2000, 'end_frame': 4800}],
                         [{'start_frame': -1, 'end_frame': 2400}],
                         [{'start_frame': .5, 'end_frame': 2400}],
                         [{'start_frame': 0, 'end_frame': 4800}] * 129):
            with self.subTest(segments=segments):
                for route, body in (('editing-waveform', {'segments': segments}),
                                    ('preview-selection', {'segments': segments, 'start': 0, 'end': .05})):
                    result = self.post(f'/sounds/{self.id}/{route}', json=body)
                    self.assertIn(result.status_code, (400, 422), result.text)
        result = self.post(f'/sounds/{self.id}/preview-selection', json={
            'segments': [{'start_frame': 0, 'end_frame': 2400}], 'start': 0, 'end': .05, 'fade_in': .1})
        self.assertEqual(result.status_code, 400, result.text)
        self.assertEqual(list(self.library.directory.glob('tmp*')), [])
        self.assertEqual(len(self.library.list()), 1)

    def test_invalid_removals_do_not_create_or_preview_clips(self):
        for settings in ({'start': 0, 'end': .1}, {'start': 0, 'end': .095},
                         {'start': .01, 'end': .09, 'fade_in': .03}):
            values = {'operation': 'remove', **settings}
            with self.subTest(settings=settings):
                result = self.post(f'/sounds/{self.id}/trim', json={'name': 'bad', **values})
                self.assertEqual(result.status_code, 400, result.text)
                result = self.post(f'/sounds/{self.id}/preview-selection', json=values)
                self.assertEqual(result.status_code, 400, result.text)
        self.assertEqual(self.post(f'/sounds/{self.id}/trim', json={
            'name': 'bad', 'start': .02, 'end': .08, 'operation': 'unknown'}).status_code, 422)
        self.assertEqual(len(self.library.list()), 1)
        self.assertIsNone(self.app.state.audio.played)

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

    def test_trash_restore_and_rename(self):
        self.post(f'/sounds/{self.id}/rename',json={'name':'My renamed sound'})
        self.assertEqual(self.post(f'/sounds/{self.id}/trash').status_code,200)
        self.assertEqual(self.library.list(),[])
        self.assertEqual(self.boards.active()['tiles'][0]['sound_id'],self.id)
        self.assertEqual(self.post('/play',json={'sound_id':self.id,'mode':'preview'}).status_code,400)
        self.assertEqual(self.post(f'/sounds/{self.id}/restore').status_code,200)
        persisted=Library(self.root/'.state/library')
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
        self.boards.set_tile(pid,2,{'sound_id':self.id})
        removed=self.post(f'/sets/{pid}/tiles/remove',json={'indexes':[1,2,2,999]})
        self.assertEqual(removed.status_code,200,removed.text)
        self.assertEqual(removed.json()['removed'],2)
        self.assertIsNone(self.boards.active()['tiles'][1])
        self.assertIsNone(self.boards.active()['tiles'][2])
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
        other_lib=Library(self.root/'other-library')
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

    def test_bundle_preserves_original_mp3_filename_and_bytes(self):
        source = self.root/'Victory tune.mp3'
        subprocess.run(['ffmpeg','-v','error','-i',str(self.library.path(self.id)),str(source)],check=True)
        sound = self.library.import_file(source,source.name)
        self.boards.add(sound['id'])
        bundle = self.root/'originals.zip'
        export_set(self.boards,self.library,self.profile['id'],bundle)
        with zipfile.ZipFile(bundle) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest['version'],2)
            self.assertEqual(set(archive.namelist()),{'manifest.json','audio/sample.wav','audio/Victory tune.mp3'})
            self.assertEqual(archive.read('audio/Victory tune.mp3'),source.read_bytes())
        other_lib = Library(self.root/'other-library')
        other_boards = Boards(self.root/'other-sets.json',other_lib)
        import_set(other_boards,other_lib,bundle)
        imported = other_lib.get(sound['id'])
        self.assertEqual(imported['stored_file'],source.name)
        self.assertEqual((other_lib.directory/imported['stored_file']).read_bytes(),source.read_bytes())
        second = self.root/'reexport.zip'
        export_set(other_boards,other_lib,other_boards.active()['id'],second)
        with zipfile.ZipFile(second) as archive:
            self.assertEqual(archive.read('audio/Victory tune.mp3'),source.read_bytes())

    def test_bundle_readable_collisions_and_wav_fallback(self):
        second = self.library.save_selection(self.id,'Another sound',start=0,end=.05)
        self.boards.add(second['id'])
        for filename in ('sample.wav','x'*216+'.wav'):
            self.library.items[self.id]['filename'] = filename
            self.library.items[second['id']]['filename'] = filename
            bundle = self.root/'collisions.zip'
            export_set(self.boards,self.library,self.profile['id'],bundle)
            with zipfile.ZipFile(bundle) as archive:
                audio = [n for n in archive.namelist() if n.startswith('audio/')]
                self.assertEqual(len(audio),2)
                self.assertEqual(len(set(n.casefold() for n in audio)),2)
                self.assertIn('audio/'+filename,audio)
                self.assertTrue(any(n.endswith(' (2).wav') for n in audio))
                self.assertTrue(all(len(Path(n).name.encode())<=220 for n in audio))
        self.library.items[self.id]['filename'] = 'Original song.mp3'
        (self.library.directory/self.sound['stored_file']).unlink()
        bundle = self.root/'fallback.zip'
        export_set(self.boards,self.library,self.profile['id'],bundle)
        with zipfile.ZipFile(bundle) as archive:
            self.assertEqual(archive.read('audio/Original song.wav'),self.library.path(self.id).read_bytes())

    def test_legacy_hashed_wav_bundle_still_imports(self):
        manifest = {'format':'soundboard-set','version':1,'profile':self.profile,
                    'sounds':[{**self.sound,'filename':'Old original.mp3','file':f'audio/{self.id}.wav'}]}
        bundle = self.root/'legacy.zip'
        with zipfile.ZipFile(bundle,'w') as archive:
            archive.writestr('manifest.json',json.dumps(manifest))
            archive.write(self.library.path(self.id),f'audio/{self.id}.wav')
        other_lib = Library(self.root/'legacy-library')
        other_boards = Boards(self.root/'legacy-sets.json',other_lib)
        imported = import_set(other_boards,other_lib,bundle)
        self.assertEqual(imported['tiles'][0]['sound_id'],self.id)
        self.assertEqual(other_lib.get(self.id)['stored_file'],'Old original.wav')
        self.assertTrue(other_lib.path(self.id).is_file())

    def test_bundle_rejects_unsafe_or_shared_named_audio_paths(self):
        bundle = self.root/'named.zip'
        export_set(self.boards,self.library,self.profile['id'],bundle)
        with zipfile.ZipFile(bundle) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            audio = archive.read(manifest['sounds'][0]['file'])
        other_lib = Library(self.root/'reject-library')
        other_boards = Boards(self.root/'reject-sets.json',other_lib)
        for name in ('audio/../escaped.wav','audio/subdir/sample.wav','audio/evil\\sample.wav','/audio/sample.wav','audio/sample.txt','audio/sample.wav'):
            changed = deepcopy(manifest)
            changed['sounds'][0]['file'] = name
            if name == 'audio/sample.wav':
                changed['sounds'].append({**changed['sounds'][0],'id':'a'*24})
            with zipfile.ZipFile(bundle,'w') as archive:
                archive.writestr('manifest.json',json.dumps(changed))
                archive.writestr(name,audio)
            before = other_boards.snapshot(),deepcopy(other_lib.items)
            with self.assertRaises(ValueError):
                import_set(other_boards,other_lib,bundle)
            self.assertEqual((other_boards.snapshot(),other_lib.items),before)

    def test_invalid_bundle_cannot_partially_publish_or_extract_paths(self):
        bundle=self.root/'good.zip';export_set(self.boards,self.library,self.profile['id'],bundle)
        with zipfile.ZipFile(bundle) as z:
            files={n:z.read(n) for n in z.namelist()}
        for variant in ('traversal','broken-audio','bad-filename'):
            entries=dict(files)
            if variant=='traversal':entries['../../escaped']=b'no'
            elif variant=='broken-audio':entries[json.loads(entries['manifest.json'])['sounds'][0]['file']]=b'broken'
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
