"""Pairing boundaries and the phone's shared playback actions."""
import hashlib
import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from soundboard.server import create_app, NoHotkeys
from soundboard.remote import RemoteControl, COOKIE
from soundboard.storage import Storage
from test_api import FakeAudio, wav_bytes


class PhoneAudio(FakeAudio):
    def __init__(self,directory):
        super().__init__(directory);self.connected=True;self.lock=threading.RLock()
    def status(self):
        return {'connected':self.connected,'playing':[{'tile_id':self.options.get('tile_id')}] if self.played else [],'error':None}


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.storage=Storage(self.root/'collection',self.root/'config/storage.json',self.root/'collection')
        self.app=create_app(self.root,self.storage.directory,audio_factory=PhoneAudio,hotkeys_factory=NoHotkeys,storage=self.storage)
        self.local=TestClient(self.app,base_url='http://127.0.0.1:8765');self.local.__enter__()
        self.headers={'X-Soundboard-Request':'1'}
        with socket.socket() as s:s.bind(('127.0.0.1',0));self.port=s.getsockname()[1]
        self.remote=self.app.state.remote
        self.phone=TestClient(self.remote.app,base_url=f'http://192.168.1.9:{self.port}',client=('192.168.1.20',12345))
        self.mobile_headers={'X-TuxCue-Remote':'1'}

    def tearDown(self):
        self.phone.close();self.local.__exit__(None,None,None);self.storage.close();self.temp.cleanup()

    def post(self,path,body=None):
        return self.local.post('/api'+path,json=body or {},headers=self.headers)

    def enable(self):
        result=self.post('/remote/settings',{'enabled':True,'port':self.port})
        self.assertEqual(result.status_code,200,result.text)
        return result.json()

    def pair(self):
        self.enable()
        ticket=self.post('/remote/pairing').json()['pairing']
        result=self.phone.post('/remote/api/pair',json={'code':ticket['code'],'name':'Test phone'},headers=self.mobile_headers)
        self.assertEqual(result.status_code,200,result.text)
        return ticket

    def test_disabled_listener_local_admin_and_unauthenticated_boundaries(self):
        self.assertFalse(self.local.get('/api/remote').json()['enabled'])
        self.enable()
        for path in ('/remote/api/state','/remote/api/play','/remote/api/stop'):
            result=self.phone.get(path) if path.endswith('state') else self.phone.post(path,json={},headers=self.mobile_headers)
            self.assertEqual(result.status_code,401,result.text)
        self.pair()
        for path in ('/api/state','/api/storage/folders','/api/shutdown','/api/connect','/api/remote','/openapi.json'):
            self.assertEqual(self.phone.get(path).status_code,404,path)
        self.assertEqual(self.phone.post('/remote/api/stop',json={}).status_code,403)
        self.assertEqual(self.phone.post('/remote/api/stop',json={},headers={**self.mobile_headers,'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.phone.get('/remote/api/state',headers={'Host':'evil.example'}).status_code,403)
        outsider=TestClient(self.remote.app,base_url=f'http://192.168.1.9:{self.port}',client=('8.8.8.8',12345))
        self.assertEqual(outsider.get('/').status_code,403)
        outsider.close()
        self.assertEqual(self.post('/remote/settings',{'enabled':False,'port':self.port}).status_code,200)
        with self.assertRaises(OSError):socket.create_connection(('127.0.0.1',self.port),timeout=.2)

    def test_pairing_is_single_use_expiring_rate_limited_and_hashes_sessions(self):
        ticket=self.pair()
        raw=self.phone.cookies.get(COOKIE)
        saved=json.loads(self.remote.settings_file.read_text())
        self.assertNotIn(raw,json.dumps(saved));self.assertIn(hashlib.sha256(raw.encode()).hexdigest(),json.dumps(saved))
        self.assertEqual(self.phone.post('/remote/api/pair',json={'code':ticket['token']},headers=self.mobile_headers).status_code,401)
        self.assertEqual(self.phone.post('/remote/api/pair',json={'code':'žžž'},headers=self.mobile_headers).status_code,401)
        self.remote.pair_ticket();self.remote.pairing['expires_at']=0
        self.assertEqual(self.phone.post('/remote/api/pair',json={'code':self.remote.pairing['code']},headers=self.mobile_headers).status_code,401)
        for _ in range(3):result=self.phone.post('/remote/api/pair',json={'code':'invalid'},headers=self.mobile_headers)
        self.assertEqual(result.status_code,429)
        self.remote.forget()
        self.assertEqual(self.phone.get('/remote/api/state').status_code,401)

    def test_tiles_use_pc_routing_volume_overlap_and_stale_set_protection(self):
        sound=self.local.post('/api/import',files={'file':('test.wav',wav_bytes())},headers=self.headers).json()
        profile=self.app.state.boards.active();tile=profile['tiles'][0]
        self.app.state.boards.set_tile(profile['id'],0,{'volume':.3,'shortcut':'Ctrl+1'})
        self.app.state.boards.update(profile['id'],{'playback_mode':'overlap'})
        self.pair()
        body={'set_id':profile['id'],'tile_id':tile['id']}
        self.assertEqual(self.phone.post('/remote/api/play',json=body,headers=self.mobile_headers).status_code,200)
        audio=self.app.state.audio
        self.assertEqual(audio.played[2],'broadcast');self.assertEqual(audio.options['volume'],.3);self.assertTrue(audio.options['overlap'])
        state=self.phone.get('/remote/api/state').json()
        self.assertEqual(state['playing'][0]['tile_id'],tile['id'])
        for private in ('storage','devices','settings','filename','stored_file','pcm_file'):
            self.assertNotIn('"'+private+'"',json.dumps(state))
        self.phone.post('/remote/api/play',json={**body,'mode':'preview'},headers=self.mobile_headers)
        self.assertEqual(audio.played[2],'preview')
        audio.connected=False
        self.phone.post('/remote/api/play',json=body,headers=self.mobile_headers)
        self.assertEqual(audio.played[2],'preview')
        self.phone.post('/remote/api/stop',json={},headers=self.mobile_headers);self.assertIsNone(audio.played)
        other=self.app.state.boards.create('Second set')
        self.assertEqual(self.phone.post('/remote/api/set',json={'set_id':other['id']},headers=self.mobile_headers).status_code,200)
        self.assertEqual(self.phone.post('/remote/api/play',json=body,headers=self.mobile_headers).status_code,400)
        self.phone.post('/remote/api/set',json={'set_id':profile['id']},headers=self.mobile_headers)
        self.post(f"/sounds/{sound['id']}/trash")
        self.assertEqual(self.phone.post('/remote/api/play',json=body,headers=self.mobile_headers).status_code,400)
        self.assertEqual(self.phone.get('/remote/api/state').json()['profile']['tiles'],[])

    def test_pairing_survives_restart_and_storage_move_but_revocation_is_immediate(self):
        self.pair();old=self.remote.settings_file
        result=self.post('/storage',{'folder':str(self.root/'moved')})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(self.remote.settings_file,self.root/'moved/remote-settings.json')
        self.assertEqual(self.phone.get('/remote/api/state').status_code,200)
        self.remote.close();self.remote.restore()
        self.assertEqual(self.phone.get('/remote/api/state').status_code,200)
        clone=RemoteControl(self.remote.settings_file,self.root,lambda:{},lambda *a:None,lambda:None,lambda *a:None)
        self.assertIsNotNone(clone._session(self.phone.cookies.get(COOKIE)))
        device=self.remote.status()['devices'][0]['id']
        self.post('/remote/forget/'+device)
        self.assertEqual(self.phone.get('/remote/api/state').status_code,401)
        self.assertEqual(json.loads(self.remote.settings_file.read_text())['devices'],{})
        self.assertNotEqual(json.loads(old.read_text())['devices'],{})

    def test_qr_uses_fragment_and_real_listener_enforces_pairing(self):
        self.enable();ticket=self.post('/remote/pairing').json()['pairing']
        with patch('soundboard.remote.network_addresses',return_value=[{'address':'192.168.1.9','interface':'wlan0'}]):
            result=self.local.get('/api/remote/qr?address=192.168.1.9')
            self.assertEqual(result.status_code,200);self.assertIn('<svg',result.text)
            self.assertEqual(self.local.get('/api/remote/qr?address=evil.example').status_code,400)
        with httpx.Client(base_url=f'http://127.0.0.1:{self.port}') as phone:
            self.assertEqual(phone.get('/remote/api/state').status_code,401)
            r=phone.post('/remote/api/pair',json={'code':ticket['token']},headers=self.mobile_headers)
            self.assertEqual(r.status_code,200,r.text)
            self.assertIn('HttpOnly',r.headers['set-cookie']);self.assertIn('SameSite=strict',r.headers['set-cookie'])
            self.assertEqual(phone.get('/remote/api/state').status_code,200)
            self.assertEqual(phone.post('/remote/api/leave',json={},headers=self.mobile_headers).status_code,200)
            self.assertEqual(phone.get('/remote/api/state').status_code,401)

    def test_occupied_port_and_failed_save_do_not_enable_or_leave_a_listener(self):
        with socket.socket() as occupied:
            occupied.bind(('0.0.0.0',self.port));occupied.listen()
            self.assertEqual(self.post('/remote/settings',{'enabled':True,'port':self.port}).status_code,400)
        self.assertFalse(self.remote.running);self.assertFalse(self.remote.settings['enabled'])
        with patch('soundboard.remote.atomic_json',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.remote.configure(True,self.port)
        self.assertFalse(self.remote.running);self.assertFalse(self.remote.settings['enabled'])
        with self.assertRaises(OSError):socket.create_connection(('127.0.0.1',self.port),timeout=.2)

if __name__=='__main__':unittest.main()
