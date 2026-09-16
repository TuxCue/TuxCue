#!/usr/bin/env python3
"""Verify real old/new AppImage handover using an isolated collection and audio devices."""
from pathlib import Path
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
import wave
import httpx

project=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(project))
from soundboard.audio import pactl, module_list
from soundboard.library import atomic_json


def free_port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]


def main():
    port,remote_port=free_port(),free_port()
    prefix='tuxcue_upgrade_'+uuid.uuid4().hex[:8]
    defaults=pactl('info',json_output=True)
    modules=[];processes=[];logs=[];passed=[]
    with tempfile.TemporaryDirectory(prefix='upgrade-',) as folder:
        root=Path(folder);collection=root/'collection';collection.mkdir()
        atomic_json(root/'config/tuxcue/storage.json',{'folder':str(collection)})
        env={**os.environ,'XDG_CONFIG_HOME':str(root/'config')}
        client=httpx.Client(base_url=f'http://127.0.0.1:{port}',headers={'X-Soundboard-Request':'1'},timeout=10,trust_env=False)
        phone=httpx.Client(base_url=f'http://127.0.0.1:{remote_port}',headers={'X-TuxCue-Remote':'1'},timeout=10,trust_env=False)
        def post(path,data=None,**kwargs):
            r=client.post('/api'+path,json=data,**kwargs);r.raise_for_status();return r.json()
        def state():
            r=client.get('/api/state');r.raise_for_status();return r.json()
        def launch(version,extra_env=None,browser=False):
            log=(root/f'process-{len(processes)}.log').open('w');logs.append(log)
            p=subprocess.Popen([os.environ['TUXCUE_OLD_APPIMAGE' if version == '0.4.2' else 'TUXCUE_APPIMAGE'],'--appimage-extract-and-run',
                                '--open-browser' if browser else '--no-browser','--no-tray','--port',str(port),
                                '--audio-prefix',prefix+'_app'],env=extra_env or env,stdout=log,stderr=subprocess.STDOUT)
            processes.append(p);return p
        def ready(version,connected=None):
            deadline=time.monotonic()+35
            while time.monotonic()<deadline:
                try:
                    result=state()
                    if result['version']==version and (connected is None or result['connected']==connected):return result
                except httpx.HTTPError:pass
                time.sleep(.1)
            raise AssertionError('Expected app did not become ready')
        def shutdown(process):
            post('/shutdown',{});process.wait(timeout=10);assert process.returncode==0
        try:
            for module,args in [
                ('module-null-sink',[f'sink_name={prefix}_feed','sink_properties=device.description=TuxCue-Upgrade-Test-Feed priority.session=0']),
                ('module-remap-source',[f'master={prefix}_feed.monitor',f'source_name={prefix}_mic','source_properties=device.description=TuxCue-Upgrade-Test-Mic priority.session=0']),
                ('module-null-sink',[f'sink_name={prefix}_phones','sink_properties=device.description=TuxCue-Upgrade-Test-Phones priority.session=0'])]:
                modules.append(pactl('load-module',module,*args))
            old=launch('0.4.2');ready('0.4.2')
            post('/shortcuts/settings',{'hotkeys_enabled':False})
            wav=io.BytesIO()
            with wave.open(wav,'wb') as f:f.setparams((1,2,48000,0,'NONE',''));f.writeframes(b'\0\x04'*4800)
            sound=post('/import',files={'file':('Upgrade test.wav',wav.getvalue(),'audio/wav')})
            post('/settings',{'microphone':prefix+'_mic','output':prefix+'_phones'})
            post('/connect',{})
            post('/remote/settings',{'enabled':True,'port':remote_port})
            ticket=post('/remote/pairing',{})['pairing']
            response=phone.post('/remote/api/pair',json={'code':ticket['code'],'name':'Upgrade test phone'});response.raise_for_status()
            before=state();original=(collection/'library/Upgrade test.wav').read_bytes()
            old_audio={m['argument'] for m in module_list() if prefix+'_app' in m['argument']}
            assert old_audio
            new=launch('0.4.6');after=ready('0.4.6',connected=True)
            old.wait(timeout=10);assert old.returncode==0
            assert new.poll() is None
            assert after['instance_id']!=before['instance_id']
            for key in ('sounds','sets','settings','storage'):assert before[key]==after[key],key
            assert (collection/'library/Upgrade test.wav').read_bytes()==original
            assert phone.get('/remote/api/state').status_code==200
            new_audio={m['argument'] for m in module_list() if prefix+'_app' in m['argument']}
            # PipeWire may reuse numeric module IDs; ownership is identified by session tags.
            assert new_audio and old_audio.isdisjoint(new_audio),(old_audio,new_audio)
            assert not after['playing'] and not after['error']
            passed.extend(['0.4.6 cleanly replaces a running 0.4.2 AppImage','Collection, set, original audio and settings survive',
                           'Connected virtual microphone restored after old owned devices are released','Paired phone reconnects without pairing again'])
            duplicate=launch('0.4.6');duplicate.wait(timeout=10);assert duplicate.returncode==0
            assert state()['instance_id']==after['instance_id'];passed.append('Same-version --no-browser launch reuses the running app')
            stub=root/'bin';stub.mkdir();opener=stub/'xdg-open'
            opener.write_text('#!/bin/sh\nprintf "%s" "$1" > "$TUXCUE_TEST_BROWSER_URL"\n');opener.chmod(0o755)
            duplicate=launch('0.4.6',{**env,'PATH':str(stub)+os.pathsep+env['PATH'],'TUXCUE_TEST_BROWSER_URL':str(root/'opened-url')},browser=True)
            duplicate.wait(timeout=10);assert duplicate.returncode==0
            assert (root/'opened-url').read_text()==f'http://127.0.0.1:{port}'
            assert state()['instance_id']==after['instance_id'];passed.append('Same-version browser launch opens the existing instance before exiting')
            shutdown(new)
            racers=[launch('0.4.6') for _ in range(3)]
            fresh=ready('0.4.6',connected=False)
            deadline=time.monotonic()+12
            while time.monotonic()<deadline and sum(p.poll() is None for p in racers)>1:time.sleep(.1)
            running=[p for p in racers if p.poll() is None]
            assert len(running)==1 and all(p.poll() in (0,None) for p in racers)
            assert fresh['sounds']==before['sounds']
            passed.append('Three simultaneous launches result in one running app and two successful reuses')
            shutdown(running[0])
            assert not any(prefix+'_app' in m['argument'] for m in module_list())
            passed.append('Final quit removes the test app audio devices')
            print(json.dumps({'passed':passed},indent=2))
        except Exception:
            for log in logs:log.flush();print(Path(log.name).read_text(),file=sys.stderr)
            raise
        finally:
            for proc in processes:
                if proc.poll() is None:
                    try:post('/shutdown',{});proc.wait(timeout=5)
                    except Exception:proc.terminate();proc.wait(timeout=5)
            for log in logs:log.close()
            for module in reversed(modules):pactl('unload-module',module)
            client.close();phone.close()
    after=pactl('info',json_output=True)
    assert all(defaults[key]==after[key] for key in ('default_source_name','default_sink_name'))

if __name__=='__main__':main()
