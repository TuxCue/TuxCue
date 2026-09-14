#!/usr/bin/env python3
"""Integration checks against the running audio server, using synthetic devices.

No physical microphone or speakers are used. Temporary recordings contain only
generated tones. Run from the project root.
"""
from array import array
import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time
import uuid
import wave

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from soundboard.audio import AudioEngine, Gst, pactl, module_list
from soundboard.library import Library


def amplitude(raw, frequency):
    values = array("h", raw[:len(raw)//4*4])
    if sys.byteorder != "little":
        values.byteswap()
    # One channel, downsampled to 12 kHz; exclude initial capture startup.
    mono = [v/32768 for v in values[0::8]][3000:15000]
    if not mono:
        return 0.0
    real = sum(v*math.cos(2*math.pi*frequency*i/12000) for i,v in enumerate(mono))
    imag = sum(v*math.sin(2*math.pi*frequency*i/12000) for i,v in enumerate(mono))
    return 2*math.hypot(real,imag)/len(mono)


def peak(raw):
    values = array("h", raw[:len(raw)//2*2])
    if sys.byteorder != "little":
        values.byteswap()
    return max((abs(v) for v in values), default=0)/32768


def main():
    prefix = "soundboard_test_" + uuid.uuid4().hex[:8]
    external = []
    player = None
    engine = None
    api_client = None
    storage = None
    results = []
    initial_defaults = pactl("info", json_output=True)
    with tempfile.TemporaryDirectory(prefix="soundboard-check-") as temp_name:
        temp = Path(temp_name)
        def load(module, *args):
            index = pactl("load-module", module, *args)
            external.append(index)
        def capture(action, seconds=1.8, stop_after=True):
            processes, files = [], []
            try:
                for index, source in enumerate((prefix+"_phones.monitor", engine.source_name)):
                    f = (temp / f"capture-{index}.raw").open("w+b")
                    files.append(f)
                    processes.append(subprocess.Popen(["parec", "--device", source, "--raw", "--format=s16le",
                                                       "--rate=48000", "--channels=2", "--latency-msec=20"],
                                                      stdout=f, stderr=subprocess.PIPE))
                time.sleep(.2)
                action()
                time.sleep(seconds)
                for p in processes:
                    p.terminate()
                    _, err = p.communicate(timeout=3)
                    if p.returncode not in (0,-15):
                        raise AssertionError("Capture failed: " + err.decode())
                if stop_after:
                    engine.stop()
                raw=[]
                for f in files:
                    f.seek(0);raw.append(f.read())
                return raw
            finally:
                for p in processes:
                    if p.poll() is None:
                        p.kill();p.wait()
                for f in files:
                    f.close()
        try:
            load("module-null-sink", f"sink_name={prefix}_mic_feed", "rate=48000", "channels=2",
                 "sink_properties=device.description=Soundboard-Test-Mic-Feed priority.session=0")
            load("module-remap-source", f"master={prefix}_mic_feed.monitor", f"source_name={prefix}_mic",
                 "source_properties=device.description=Soundboard-Test-Mic priority.session=0")
            load("module-null-sink", f"sink_name={prefix}_phones", "rate=48000", "channels=2",
                 "sink_properties=device.description=Soundboard-Test-Phones priority.session=0")
            engine=AudioEngine(temp/"engine", prefix=prefix)
            engine.configure({"microphone":prefix+"_mic", "output":prefix+"_phones", "mic_enabled":True,
                              "mic_volume":1.0,"monitor_volume":.5,"send_volume":.7})
            engine.connect()
            player = Gst.parse_launch("audiotestsrc is-live=true freq=440 volume=0.12 ! audioconvert ! pulsesink name=feed")
            player.get_by_name("feed").set_property("device",prefix+"_mic_feed")
            player.set_state(Gst.State.PLAYING)
            time.sleep(.4)
            tone=temp/"tone.wav"
            with wave.open(str(tone),"wb") as f:
                f.setparams((2,2,48000,0,"NONE","not compressed"))
                f.writeframes(b''.join(struct.pack('<hh',*( [int(32767*.12*math.sin(2*math.pi*880*i/48000))]*2)) for i in range(48000*3)))
            monitor, sent=capture(lambda:engine.play(tone,"tone"))
            a = {"monitor_voice":amplitude(monitor,440),"monitor_clip":amplitude(monitor,880),
                 "sent_voice":amplitude(sent,440),"sent_clip":amplitude(sent,880)}
            print("Broadcast signal:",json.dumps(a),flush=True)
            assert a["monitor_clip"]>.015 and a["sent_clip"]>.015, "Clip did not reach both outputs"
            assert a["sent_voice"]>.02, "Microphone was not mixed in"
            assert a["monitor_voice"]<.002, "Microphone leaked into local monitoring"
            results.append("Clip reaches both outputs; voice reaches only the virtual microphone")
            monitor,sent=capture(lambda:engine.play(tone,"tone",mode="preview"))
            assert amplitude(monitor,880)>.015 and amplitude(sent,880)<.002, "Preview leaked into Discord feed"
            assert amplitude(sent,440)>.02, "Preview interrupted microphone"
            results.append("Local preview keeps clips out of the Discord feed and preserves voice")
            from fastapi.testclient import TestClient
            from soundboard.server import create_app, NoHotkeys
            from soundboard.storage import Storage
            storage=Storage(temp/"engine",temp/"config/storage.json",temp/"TuxCue")
            api_client=TestClient(create_app(temp,storage.directory,audio_factory=lambda _:engine,hotkeys_factory=NoHotkeys,storage=storage),base_url="http://127.0.0.1:8765")
            api_client.__enter__()
            response=api_client.post('/api/storage',json={'folder':str(temp/'moved collection')},headers={'X-Soundboard-Request':'1'})
            assert response.status_code==200,response.text
            assert engine.status()['connected'],"Moving files disconnected the virtual microphone"
            monitor,sent=capture(lambda:engine.play(tone,'tone'))
            assert amplitude(sent,440)>.02 and amplitude(sent,880)>.015 and amplitude(monitor,440)<.002
            assert engine.module_file==temp/'moved collection/audio-session.json'
            results.append("Live storage migration preserves microphone routing and subsequent clip playback")
            engine.configure({"mic_volume":0})
            monitor,sent=capture(lambda:engine.play(tone,"tone"))
            print("Muted voice amplitude:",amplitude(sent,440),flush=True)
            assert amplitude(sent,440)<.002, "Voice volume control did not mute microphone"
            results.append("Independent voice volume reaches zero")
            # Two simultaneous tones verify independent per-tile levels and cleanup.
            second = temp/"second.wav"
            with wave.open(str(second),"wb") as f:
                f.setparams((2,2,48000,0,"NONE","not compressed"))
                f.writeframes(b''.join(struct.pack('<hh',*([int(32767*.12*math.sin(2*math.pi*1320*i/48000))]*2)) for i in range(48000*3)))
            def overlap():
                engine.play(tone,"first",volume=.5,tile_id="tile-a")
                engine.play(second,"second",volume=1,overlap=True,tile_id="tile-b")
                assert len(engine.status()["playing"])==2, "Overlap replaced an active clip"
            monitor,sent=capture(overlap)
            a880,a1320=amplitude(sent,880),amplitude(sent,1320)
            assert a880>.01 and a1320>.03 and .35<a880/a1320<.65, "Per-tile volume or overlap mixing failed"
            assert engine.status()["playing"]==[], "Stop all left an overlapping clip active"
            results.append("Overlapping clips mix at independent tile volumes; Stop all clears every clip")
            def preview_overlap():
                engine.play(tone,"first",mode="preview",volume=.5)
                engine.play(second,"second",mode="preview",overlap=True)
            monitor,sent=capture(preview_overlap)
            assert amplitude(monitor,880)>.01 and amplitude(monitor,1320)>.02
            assert amplitude(sent,880)<.002 and amplitude(sent,1320)<.002, "Overlapping previews leaked into Discord feed"
            results.append("Overlapping local previews remain isolated from the virtual microphone")
            engine.play(tone,"first");engine.play(second,"second",overlap=True)
            engine.stop("first")
            assert [p["sound_id"] for p in engine.status()["playing"]]==["second"]
            engine.stop()
            results.append("Removing one sound stops only that sound's playing instances")
            engine.configure({"mic_enabled":False})
            encoded=temp/'generated.mp3'
            subprocess.run(['ffmpeg','-v','error','-i',str(tone),str(encoded)],check=True)
            monitor,sent=capture(lambda:engine.play(encoded,'generated-mp3'),seconds=3.5,stop_after=False)
            assert peak(monitor)>.002 and peak(sent)>.002, "Generated MP3 did not reach both outputs"
            assert engine.status()["playing_id"] is None, "Finished clip was not cleared"
            results.append("Generated MP3 decodes, plays to both outputs and completes")
            engine.play(tone,"tone");time.sleep(.15);engine.stop()
            assert engine.status()["playing_id"] is None
            results.append("Stop clears playback immediately")
            # Remove selected synthetic output to exercise real hot-unplug handling.
            pactl("unload-module",external.pop())
            deadline=time.monotonic()+4
            while engine.status()["connected"] and time.monotonic()<deadline:
                time.sleep(.1)
            assert not engine.status()["connected"], "Missing output did not disconnect routing"
            assert engine.status()["error"], "Missing output was not explained"
            results.append("Output removal disconnects safely and reports an error")
            load("module-null-sink", f"sink_name={prefix}_phones", "rate=48000", "channels=2",
                 "sink_properties=device.description=Soundboard-Test-Phones priority.session=0")
            engine.connect()
            assert engine.status()["connected"]
            results.append("Reconnect succeeds after the output returns")
            engine.disconnect()
            assert not any(f"sink_name={engine.mix_name} " in m["argument"] or f"source_name={engine.source_name} " in m["argument"] for m in module_list())
            results.append("Disconnect removes owned virtual devices")
        finally:
            if player:
                player.set_state(Gst.State.NULL)
            if api_client:
                api_client.__exit__(None,None,None)
            elif engine:
                engine.close()
            if storage:
                storage.close()
            for index in reversed(external):
                pactl("unload-module",index)
    final_defaults=pactl("info",json_output=True)
    assert all(initial_defaults[k]==final_defaults[k] for k in ("default_source_name","default_sink_name")), "System defaults changed"
    results.append("System default input and output are preserved")
    print(json.dumps({"passed":results},indent=2))


if __name__=="__main__":
    main()
