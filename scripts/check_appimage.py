#!/usr/bin/env python3
"""Exercise the actual AppImage with temporary storage and synthetic audio devices."""
from pathlib import Path
import json
import math
import os
import socket
import struct
import subprocess
import sys
import tempfile
import time
import uuid
import wave
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import httpx
from soundboard.audio import Gst,pactl,module_list
from soundboard.library import atomic_json
from soundboard.tray import send_action
from check_audio import amplitude


def main():
    project=Path(__file__).resolve().parent.parent
    appimage=Path(os.environ['TUXCUE_APPIMAGE'])
    def unused_port():
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));return sock.getsockname()[1]
    local_port,remote_port=unused_port(),unused_port()
    prefix='tuxcue_package_test_'+uuid.uuid4().hex[:8]
    defaults=pactl('info',json_output=True)
    modules=[];proc=None;feed=None;log=None
    with tempfile.TemporaryDirectory(prefix='tuxcue-package-',) as dirname:
        temp=Path(dirname)
        state=temp/'collection';state.mkdir()
        config=temp/'config/tuxcue/storage.json'
        atomic_json(config,{'folder':str(state)})
        env={**os.environ,'XDG_CONFIG_HOME':str(temp/'config')}
        client=httpx.Client(base_url=f'http://127.0.0.1:{local_port}',headers={'X-Soundboard-Request':'1'},timeout=20)
        phone=httpx.Client(base_url=f'http://127.0.0.1:{remote_port}',headers={'X-TuxCue-Remote':'1'},timeout=20)
        def phone_post(path,body=None):
            r=phone.post('/remote/api'+path,json=body or {});r.raise_for_status();return r.json()
        def load(module,*args):modules.append(pactl('load-module',module,*args))
        def post(path,**kwargs):
            r=client.post('/api'+path,**kwargs);r.raise_for_status();return r.json()
        def status():
            r=client.get('/api/state');r.raise_for_status();return r.json()
        def launch():
            nonlocal proc,log
            log=(temp/'service.log').open('ab')
            proc=subprocess.Popen([str(appimage),'--appimage-extract-and-run','--no-browser','--no-tray','--port',str(local_port),'--audio-prefix',prefix+'_app'],env=env,stdout=log,stderr=subprocess.STDOUT)
            for _ in range(200):
                if proc.poll() is not None:raise AssertionError((temp/'service.log').read_text())
                try:return status()
                except httpx.RequestError:time.sleep(.05)
            raise AssertionError('AppImage did not become ready')
        def shutdown():
            send_action(local_port,'shutdown');proc.wait(timeout=10)
            assert proc.returncode==0,(temp/'service.log').read_text()
            log.close()
        def capture(action):
            files=[];processes=[]
            try:
                for i,source in enumerate((prefix+'_phones.monitor',prefix+'_app_microphone')):
                    f=(temp/f'capture-{i}.raw').open('w+b');files.append(f)
                    processes.append(subprocess.Popen(['parec','--device',source,'--raw','--format=s16le','--rate=48000','--channels=2','--latency-msec=20'],stdout=f,stderr=subprocess.PIPE))
                time.sleep(.2);action();time.sleep(1.8)
                for p in processes:p.terminate();p.communicate(timeout=3)
                phone_post('/stop')
                result=[]
                for f in files:f.seek(0);result.append(f.read())
                return result
            finally:
                for p in processes:
                    if p.poll() is None:p.kill();p.wait()
                for f in files:f.close()
        try:
            load('module-null-sink',f'sink_name={prefix}_feed','rate=48000','channels=2','sink_properties=device.description=TuxCue-Package-Test-Feed priority.session=0')
            load('module-remap-source',f'master={prefix}_feed.monitor',f'source_name={prefix}_mic','source_properties=device.description=TuxCue-Package-Test-Mic priority.session=0')
            load('module-null-sink',f'sink_name={prefix}_phones','rate=48000','channels=2','sink_properties=device.description=TuxCue-Package-Test-Phones priority.session=0')
            initial=launch()
            assert initial['app']=='TuxCue' and initial['version']=='0.4.7'
            assert initial['sounds']==[],'Personal sounds were included in the package'
            assert client.get('/').status_code==200
            legal=client.get('/license');assert legal.status_code==200 and 'GNU GENERAL PUBLIC LICENSE' in legal.text
            notices=client.get('/notices');assert notices.status_code==200 and 'Third-party components' in notices.text
            inventory=client.get('/licenses/components.json');assert inventory.status_code==200 and inventory.json()['debian']
            logo=client.get('/tuxcue-logo.png');assert logo.status_code==200 and logo.content.startswith(b'\x89PNG')
            assert initial['hotkeys']['available'],initial['hotkeys']
            post('/shortcuts/settings',json={'hotkeys_enabled':False})
            tone=temp/'tone.wav'
            with wave.open(str(tone),'wb') as f:
                f.setparams((2,2,48000,0,'NONE','not compressed'))
                f.writeframes(b''.join(struct.pack('<hh',*([int(32767*.12*math.sin(2*math.pi*880*i/48000))]*2)) for i in range(48000*3)))
            with tone.open('rb') as f:sound=post('/import',files={'file':('tone.wav',f,'audio/wav')})
            assert (state/'library/tone.wav').read_bytes()==tone.read_bytes()
            assert not (state/'library'/sound['id']).exists()
            post('/settings',json={'microphone':prefix+'_mic','output':prefix+'_phones','mic_enabled':True,'mic_volume':1,'monitor_volume':.5,'send_volume':.7})
            post('/connect')
            post('/remote/settings',json={'enabled':True,'port':remote_port})
            legal=phone.get('/license');assert legal.status_code==200 and 'GNU GENERAL PUBLIC LICENSE' in legal.text
            assert phone.get('/remote/api/state').status_code==401
            ticket=post('/remote/pairing')['pairing']
            phone_post('/pair',{'code':ticket['token'],'name':'Package test phone'})
            remote_state=phone.get('/remote/api/state').json()
            profile_id=remote_state['profile']['id'];tile_id=remote_state['profile']['tiles'][0]['id']
            play_body={'set_id':profile_id,'tile_id':tile_id,'mode':'play'}
            assert phone.get('/api/storage/folders').status_code==404
            assert any(s['description']=='TuxCue Microphone' for s in pactl('list','sources',json_output=True))
            feed=Gst.parse_launch('audiotestsrc is-live=true freq=440 volume=0.12 ! audioconvert ! pulsesink name=feed')
            feed.get_by_name('feed').set_property('device',prefix+'_feed');feed.set_state(Gst.State.PLAYING);time.sleep(.4)
            monitor,sent=capture(lambda:phone_post('/play',play_body))
            assert amplitude(monitor,880)>.015 and amplitude(sent,880)>.015 and amplitude(sent,440)>.02 and amplitude(monitor,440)<.002
            monitor,sent=capture(lambda:phone_post('/play',{**play_body,'mode':'preview'}))
            assert amplitude(monitor,880)>.015 and amplitude(sent,880)<.002 and amplitude(sent,440)>.02
            clip=post(f"/sounds/{sound['id']}/trim",json={'name':'Packaged edit','start':.2,'end':1.2,'gain_db':12,'fade_in':.05,'fade_out':.05})
            assert clip['duration']==1
            moved=post('/storage',json={'folder':str(temp/'moved collection')})
            assert moved['changed'] and status()['connected']
            assert (temp/'moved collection/library/Packaged edit.wav').exists()
            monitor,sent=capture(lambda:phone_post('/play',play_body))
            assert amplitude(sent,880)>.015 and amplitude(sent,440)>.02
            old_instance=status()['instance_id']
            send_action(local_port,'restart')
            for _ in range(200):
                try:
                    restarted_live=status()
                    if restarted_live['instance_id']!=old_instance and restarted_live['connected']:break
                except httpx.RequestError:pass
                time.sleep(.05)
            else:raise AssertionError('Restart did not restore the microphone')
            assert phone.get('/remote/api/state').status_code==200,'Restart lost phone pairing'
            monitor,sent=capture(lambda:phone_post('/play',play_body))
            assert amplitude(sent,880)>.015 and amplitude(sent,440)>.02
            device=client.get('/api/remote').json()['devices'][0]['id']
            post('/remote/forget/'+device)
            assert phone.get('/remote/api/state').status_code==401
            post('/remote/settings',json={'enabled':False,'port':remote_port})
            shutdown()
            assert not any(f'sink_name={prefix}_app_mix ' in m['argument'] or f'source_name={prefix}_app_microphone ' in m['argument'] for m in module_list())
            restarted=launch()
            assert restarted['storage']['folder']==str(temp/'moved collection')
            assert len(restarted['sounds'])==2 and not restarted['connected']
            shutdown()
            print(json.dumps({'passed':['AppImage startup and bundled browser assets/logo','No personal sounds in the package','Desktop and phone license texts and bundled dependency inventory','Packaged X11 service loads','Original filenames and bytes in a flat library','Import, broadcast and microphone mixing','Headphone-only preview isolation','Boosted trimmed clip with fades','Live collection move preserves audio routing','Restart uses the moved collection','Graceful shutdown cleans virtual devices','Phone pairing, authorization and revocation','Phone broadcast, preview and Stop all','Restart restores microphone routing and paired phones'],'appimage':str(appimage)},indent=2))
        except Exception:
            if (temp/'service.log').exists():print((temp/'service.log').read_text(),file=sys.stderr)
            raise
        finally:
            if proc and proc.poll() is None:
                try:post('/shutdown');proc.wait(timeout=8)
                except Exception:proc.terminate();proc.wait(timeout=5)
            if feed:feed.set_state(Gst.State.NULL)
            if log and not log.closed:log.close()
            phone.close();client.close()
            for index in reversed(modules):pactl('unload-module',index)
    after=pactl('info',json_output=True)
    assert all(defaults[k]==after[k] for k in ('default_source_name','default_sink_name'))

if __name__=='__main__':main()
