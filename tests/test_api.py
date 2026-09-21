import io
import json
from pathlib import Path
import tempfile
import unittest
import wave

from fastapi.testclient import TestClient
from soundboard.server import create_app, NoHotkeys
from soundboard.library import Library


class FakeAudio:
    def __init__(self, directory):
        self.played = None
    def close(self): pass
    def devices(self): return {"inputs":[],"outputs":[],"server":"test"}
    def status(self): return {"connected":False}
    def play(self, path, sound_id, mode, **options): self.played=(path,sound_id,mode); self.options=options
    def stop(self, sound_id=None): self.played=None
    def configure(self, changes): pass


def wav_bytes():
    data=io.BytesIO()
    with wave.open(data,"wb") as f:
        f.setparams((1,2,48000,0,"NONE","not compressed"));f.writeframes(b'\x00\x08'*4800)
    return data.getvalue()


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.project=Path(self.temp.name)
        self.app=create_app(self.project,audio_factory=FakeAudio,hotkeys_factory=NoHotkeys)
        self.client=TestClient(self.app,base_url="http://127.0.0.1:8765")
        self.client.__enter__()
        self.headers={"X-Soundboard-Request":"1","Origin":"http://127.0.0.1:8765"}
    def tearDown(self):
        self.client.__exit__(None,None,None);self.temp.cleanup()
    def test_external_origin_and_rebinding_cannot_control_audio(self):
        self.assertEqual(self.client.post('/api/stop').status_code,403)
        self.assertEqual(self.client.post('/api/stop',headers={**self.headers,"Origin":"https://example.com"}).status_code,403)
        self.assertEqual(self.client.get('/api/state',headers={"Host":"malicious.example"}).status_code,403)
        self.assertEqual(self.client.post('/api/stop',headers=self.headers).status_code,200)
    def test_import_play_deduplicate_and_persist(self):
        payload=wav_bytes()
        result=self.client.post('/api/import',files={"file":("a weird ' sound.wav",payload,"audio/wav")},headers=self.headers)
        self.assertEqual(result.status_code,200,result.text)
        item=result.json()
        self.assertAlmostEqual(item["duration"],.1,places=2)
        response=self.client.post('/api/play',json={"sound_id":item["id"],"mode":"preview"},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.app.state.audio.played[2],"preview")
        again=self.client.post('/api/import',files={"file":("copy.wav",payload)},headers=self.headers)
        self.assertEqual(again.json()["id"],item["id"])
        persisted=Library(self.project/'.state/library')
        self.assertEqual(len(persisted.list()),1)
        self.assertTrue(persisted.path(item["id"]).is_file())
        self.assertTrue(self.client.get(f'/api/sounds/{item["id"]}/waveform').json()["peaks"])
    def test_invalid_audio_and_unknown_sound_do_not_play(self):
        result=self.client.post('/api/import',files={"file":("broken.mp3",b'not audio')},headers=self.headers)
        self.assertEqual(result.status_code,400)
        self.assertEqual(self.app.state.library.list(),[])
        result=self.client.post('/api/play',json={"sound_id":"../../etc/passwd","mode":"preview"},headers=self.headers)
        self.assertEqual(result.status_code,400)
        self.assertIsNone(self.app.state.audio.played)
    def test_invalid_settings_and_oversized_upload(self):
        self.assertEqual(self.client.post('/api/settings',json={"send_volume":4},headers=self.headers).status_code,422)
        self.assertEqual(self.client.post('/api/settings',json={"arbitrary":"x"},headers=self.headers).status_code,422)
        result=self.client.post('/api/import',content=b'',headers={**self.headers,"Content-Length":"999999999"})
        self.assertEqual(result.status_code,413)
    def test_graceful_shutdown_uses_service_callback(self):
        called=[]
        self.app.state.shutdown=lambda:called.append(True)
        self.assertEqual(self.client.post('/api/shutdown').status_code,403)
        self.assertEqual(called,[])
        self.assertEqual(self.client.post('/api/shutdown',headers=self.headers).status_code,200)
        self.assertEqual(called,[True])


if __name__=='__main__':unittest.main()
