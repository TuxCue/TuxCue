import errno
import fcntl
import json
import os
from pathlib import Path
import socket
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from soundboard import upgrade
from soundboard.server import create_app, NoHotkeys
from fastapi.testclient import TestClient


class Audio:
    def __init__(self, directory): pass
    def close(self): pass
    def devices(self): return {'inputs': [], 'outputs': [], 'server': 'test'}
    def status(self): return {'connected': True}


class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state = {'app':'TuxCue','version':'0.4.2','instance_id':'old', 'connected':True,
                      'storage':{'folder':str(self.root),'can_change':True}}
    def tearDown(self): self.temp.cleanup()

    def test_version_order_same_newer_and_unknown_do_not_shutdown(self):
        self.assertGreater(upgrade.release_version('0.4.10'),upgrade.release_version('0.4.9'))
        for version in ('0.4.3','0.4.10','1.0.0','development',None):
            with self.subTest(version=version), patch.object(upgrade,'probe',return_value={**self.state,'version':version}), patch.object(upgrade,'local_request') as request:
                result=upgrade.prepare_launch(8765,'0.4.3',self.root,self.root)
                self.assertTrue(result.reuse)
                request.assert_not_called()

    def test_replacement_requests_clean_shutdown_and_remembers_microphone(self):
        for reply in ({'ok':True},{'ok':True,'connected':False,'storage_folder':str(self.root)}):
            with self.subTest(reply=reply), patch.object(upgrade,'probe',return_value=self.state), patch.object(upgrade,'local_request',return_value=reply) as request, patch.object(upgrade,'wait_for_shutdown') as wait:
                result=upgrade.prepare_launch(8765,'0.4.3',self.root,self.root)
                self.assertFalse(result.reuse)
                self.assertEqual(result.reconnect,reply.get('connected',True))
                request.assert_called_once_with(8765,'/api/shutdown',{'expected_instance_id':'old'})
                wait.assert_called_once_with(8765,self.root)

    def test_foreign_collection_changed_instance_and_rejected_shutdown(self):
        with patch.object(upgrade,'probe',return_value=self.state), patch.object(upgrade,'local_request') as request:
            with self.assertRaises(upgrade.LaunchError): upgrade.prepare_launch(8765,'0.4.3',self.root,self.root/'other')
            request.assert_not_called()
        with patch.object(upgrade,'probe',side_effect=[self.state,{**self.state,'instance_id':'different'}]), patch.object(upgrade,'local_request') as request:
            with self.assertRaises(upgrade.LaunchError): upgrade.prepare_launch(8765,'0.4.3',self.root,self.root)
            request.assert_not_called()
        with patch.object(upgrade,'probe',return_value=self.state), patch.object(upgrade,'local_request',return_value={'ok':False}), patch.object(upgrade,'wait_for_shutdown') as wait:
            with self.assertRaises(upgrade.LaunchError): upgrade.prepare_launch(8765,'0.4.3',self.root,self.root)
            wait.assert_not_called()

    def test_probe_only_treats_connection_refused_as_no_running_app(self):
        with patch.object(upgrade,'local_request',side_effect=urllib.error.URLError(ConnectionRefusedError(errno.ECONNREFUSED,'refused'))):
            self.assertIsNone(upgrade.probe(8765))
        for response in ({'app':'another service'},[],None):
            with patch.object(upgrade,'local_request',return_value=response):
                with self.assertRaises(upgrade.LaunchError): upgrade.probe(8765)
        with patch.object(upgrade,'local_request',side_effect=urllib.error.URLError(TimeoutError())):
            with self.assertRaises(upgrade.LaunchError): upgrade.probe(8765)

    def test_waits_for_both_socket_and_collection_lock_without_forcing_exit(self):
        handle=(self.root/'app.lock').open('a+')
        self.addCleanup(handle.close)
        fcntl.flock(handle,fcntl.LOCK_EX)
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
            listener.listen()
            self.assertFalse(upgrade.collection_released(self.root))
            with self.assertRaises(upgrade.LaunchError): upgrade.wait_for_shutdown(port,self.root,timeout=0)
        with self.assertRaises(upgrade.LaunchError): upgrade.wait_for_shutdown(port,self.root,timeout=0)
        handle.close()
        upgrade.wait_for_shutdown(port,self.root,timeout=0)

    def test_launchers_are_serialized_and_lock_can_be_reused(self):
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        first,second=upgrade.StartupLock(port),upgrade.StartupLock(port)
        try:
            first.acquire(timeout=0)
            with self.assertRaises(upgrade.LaunchError): second.acquire(timeout=0)
            first.release()
            second.acquire(timeout=0)
        finally:
            first.release();second.release()

    def test_shutdown_expectation_and_state_are_atomic_and_legacy_compatible(self):
        app=create_app(self.root,audio_factory=Audio,hotkeys_factory=NoHotkeys)
        called=[];app.state.shutdown=lambda:called.append(True)
        with TestClient(app,base_url='http://127.0.0.1:8765') as client:
            headers={'X-Soundboard-Request':'1'}
            self.assertEqual(client.post('/api/shutdown',json={}).status_code,403)
            response=client.post('/api/shutdown',headers=headers,json={'expected_instance_id':'stale'})
            self.assertEqual(response.status_code,409);self.assertEqual(called,[])
            response=client.post('/api/shutdown',headers=headers,json={'expected_instance_id':app.state.instance_id})
            self.assertEqual(response.json(),{'ok':True,'connected':True,'storage_folder':str(self.root/'.state')})
            self.assertEqual(called,[True])
            self.assertEqual(client.post('/api/shutdown',headers=headers,json={}).status_code,200)


if __name__=='__main__':unittest.main()
