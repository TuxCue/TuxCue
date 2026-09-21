"""PipeWire/PulseAudio routing and local GStreamer playback.

Clips are split BEFORE the microphone is mixed in. This prevents monitoring the
user's voice, system audio or Discord's return audio through the soundboard.
"""
from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst

from .library import atomic_json

Gst.init(None)
LOG = logging.getLogger(__name__)


class AudioError(RuntimeError):
    pass


def module_list():
    # Debian's pactl JSON omits module indexes. The tab-separated interface
    # includes them on both native PulseAudio and PipeWire's compatibility server.
    result = []
    for line in pactl("list", "short", "modules").splitlines():
        fields = line.split("\t")
        if len(fields) >= 3 and fields[0].isdigit():
            result.append({"index": int(fields[0]), "name": fields[1], "argument": fields[2]})
    return result


def pactl(*args, json_output=False):
    command = ["pactl"] + (["--format=json"] if json_output else []) + list(args)
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=4,
                                env={**os.environ, "LC_ALL": "C"})
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        raise AudioError("The audio service did not respond. Check that PipeWire or PulseAudio is running.") from e
    if result.returncode:
        raise AudioError("Audio service: " + (result.stderr.strip() or "command failed"))
    try:
        return json.loads(result.stdout) if json_output else result.stdout.strip()
    except json.JSONDecodeError as e:
        raise AudioError("pactl must support JSON output (PulseAudio tools version 15 or newer).") from e


class AudioEngine:
    def __init__(self, state_dir: Path, prefix="soundboard"):
        self.lock = threading.RLock()
        self.mix_name = prefix + "_mix"
        self.source_name = prefix + "_microphone"
        self.module_file = state_dir / "audio-session.json"
        self.modules = json.loads(self.module_file.read_text()) if self.module_file.exists() else []
        self.settings_file = state_dir / "audio-settings.json"
        self.settings = {"microphone": "", "output": "", "mic_enabled": True,
                         "send_volume": 0.7, "monitor_volume": 0.5, "mic_volume": 1.0}
        if self.settings_file.exists():
            self.settings.update(json.loads(self.settings_file.read_text()))
        self.session = uuid.uuid4().hex
        self.connected = False
        self.players = []
        self.last_error = None
        self._closed = threading.Event()
        self._devices = None
        self._devices_time = 0.0
        try:
            self._cleanup_modules()
        except AudioError as e:
            self.last_error = str(e)
        self.thread = threading.Thread(target=self._watch, name="audio-watch", daemon=True)
        self.thread.start()

    def devices(self, refresh=False):
        with self.lock:
            if self._devices and not refresh and time.monotonic() - self._devices_time < 2:
                return self._devices
            info = pactl("info", json_output=True)
            sources = pactl("list", "sources", json_output=True)
            sinks = pactl("list", "sinks", json_output=True)
            def item(d, default):
                return {"name": d["name"], "description": d["description"],
                        "default": d["name"] == default, "muted": d.get("mute", False)}
            inputs = [item(d, info["default_source_name"]) for d in sources
                      if not d["name"].endswith(".monitor") and d["name"] != self.source_name
                      and not d.get("monitor_of_sink_name") and not d.get("monitor_source")
                      and d.get("properties", {}).get("device.class") != "monitor"]
            outputs = [item(d, info["default_sink_name"]) for d in sinks if d["name"] != self.mix_name]
            self._devices = {"inputs": inputs, "outputs": outputs, "server": info["server_name"]}
            self._devices_time = time.monotonic()
            # Choose explicit initial devices. Never silently replace a missing saved device.
            for key, choices in (("microphone", inputs), ("output", outputs)):
                if not self.settings[key] and choices:
                    self.settings[key] = next((d["name"] for d in choices if d["default"]), choices[0]["name"])
            return self._devices

    def _load(self, module, *args):
        index = pactl("load-module", module, *args)
        # Keep the server's exact identity so reused module IDs can never unload a foreign module.
        self.modules.append({"index": int(index), "name": module, "argument": " ".join(args)})
        atomic_json(self.module_file, self.modules)

    def _cleanup_modules(self):
        if not self.modules:
            return
        current = {m["index"]: m for m in module_list()}
        failed = []
        for m in reversed(self.modules):
            live = current.get(m["index"])
            if live and live["name"] == m["name"] and live["argument"] == m["argument"]:
                try:
                    pactl("unload-module", str(m["index"]))
                except AudioError:
                    failed.append(m)
        self.modules = list(reversed(failed))
        atomic_json(self.module_file, self.modules)
        if failed:
            raise AudioError("Some soundboard audio devices could not be removed. Try disconnecting again.")

    def _validate_devices(self, settings):
        devices = self.devices(refresh=True)
        if settings["output"] not in {d["name"] for d in devices["outputs"]}:
            raise AudioError("The selected listening device is unavailable. Select a connected device.")
        if settings["mic_enabled"] and settings["microphone"] not in {d["name"] for d in devices["inputs"]}:
            raise AudioError("The selected microphone is unavailable. Select a connected microphone or turn voice off.")

    def configure(self, changes):
        with self.lock:
            candidate = {**self.settings, **changes}
            for key in ("send_volume", "monitor_volume", "mic_volume"):
                if not math.isfinite(candidate[key]) or not 0 <= candidate[key] <= 1:
                    raise AudioError("Volume must be between 0% and 100%.")
            route_changed = any(candidate[k] != self.settings[k] for k in ("microphone", "output", "mic_enabled"))
            was_connected = self.connected
            if was_connected:
                self._validate_devices(candidate)
            if route_changed:
                self.stop()
                if was_connected:
                    self.disconnect()
            self.settings = candidate
            atomic_json(self.settings_file, self.settings)
            if was_connected and route_changed:
                self.connect()
            else:
                self._apply_volumes()

    def connect(self):
        with self.lock:
            if self.connected:
                return
            self.stop()
            self._validate_devices(self.settings)
            self._cleanup_modules()
            # A second process or another application may own these names. Never take them over.
            if any(d["name"] == self.mix_name for d in pactl("list", "sinks", json_output=True)) or any(
                    d["name"] == self.source_name for d in pactl("list", "sources", json_output=True)):
                raise AudioError("Another soundboard owns the virtual audio device. Close that instance first.")
            try:
                self._load("module-null-sink", f"sink_name={self.mix_name}", "rate=48000", "channels=2",
                           f'''sink_properties="device.description='TuxCue Mix' soundboard.session={self.session} node.virtual=true priority.session=0"''')
                self._load("module-remap-source", f"master={self.mix_name}.monitor", f"source_name={self.source_name}",
                           "channels=2", "channel_map=front-left,front-right", "remix=yes",
                           f'''source_properties="device.description='TuxCue Microphone' soundboard.session={self.session} priority.session=0"''')
                if self.settings["mic_enabled"]:
                    self._load("module-loopback", f"source={self.settings['microphone']}", f"sink={self.mix_name}",
                               "latency_msec=20", "source_dont_move=true", "sink_dont_move=true",
                               f'''sink_input_properties="application.name='TuxCue Voice' soundboard.session={self.session}"''')
                self.connected = True
                self._apply_volumes()
                self.last_error = None
            except Exception:
                self.connected = False
                self._cleanup_modules()
                raise
            self._devices_time = 0

    def _apply_volumes(self):
        for playing in self.players:
            sink = playing['pipeline'].get_property("audio-sink")
            for name, key in (("sendvol", "send_volume"), ("monitorvol", "monitor_volume")):
                element = sink.get_by_name(name)
                if element:
                    element.set_property("volume", self.settings[key] * playing['volume'])
        if self.connected and self.settings["mic_enabled"]:
            owners = {m["index"] for m in self.modules if m["name"] == "module-loopback"}
            deadline = time.monotonic() + .6
            while True:
                streams = [s for s in pactl("list", "sink-inputs", json_output=True)
                           if s.get("owner_module") in owners or
                           s.get("properties", {}).get("soundboard.session") == self.session]
                if streams:
                    for stream in streams:
                        pactl("set-sink-input-volume", str(stream["index"]), f"{round(self.settings['mic_volume'] * 100)}%")
                    break
                if time.monotonic() >= deadline:
                    raise AudioError("The microphone stream did not appear. Try reconnecting.")
                time.sleep(.02)

    def disconnect(self):
        with self.lock:
            self.stop()
            self.connected = False
            self._cleanup_modules()
            self._devices_time = 0

    def play(self, path: Path, sound_id: str, mode="broadcast", volume=1.0, overlap=False, tile_id=None):
        with self.lock:
            if not math.isfinite(volume) or not 0 <= volume <= 1:
                raise AudioError('Tile volume must be between 0% and 100%.')
            if mode not in ("broadcast", "preview"):
                raise AudioError("Unknown playback mode.")
            if mode == "broadcast" and not self.connected:
                raise AudioError("Connect the virtual microphone before sending a sound.")
            devices = self.devices(refresh=True)
            if self.settings["output"] not in {d["name"] for d in devices["outputs"]}:
                raise AudioError("The listening device is unavailable. Select a connected device.")
            if not overlap:
                self.stop()
            elif len(self.players) >= 16:
                raise AudioError('Up to 16 clips can overlap. Stop some clips before playing more.')
            # User/device values are set as properties, never inserted in a pipeline expression.
            branches = "tee name=t t. ! queue ! volume name=monitorvol ! pulsesink name=monitor sync=true"
            if mode == "broadcast":
                branches += " t. ! queue ! volume name=sendvol ! pulsesink name=send sync=true"
            sink = Gst.parse_bin_from_description("audioconvert ! audioresample ! " + branches, True)
            for name, target in (("monitor", self.settings["output"]), ("send", self.mix_name)):
                element = sink.get_by_name(name)
                if element:
                    element.set_property("device", target)
                    element.set_property("client-name", "TuxCue")
                    props = Gst.Structure.new_empty("props")
                    props.set_value("application.name", "TuxCue")
                    props.set_value("node.dont-fallback", True)
                    props.set_value("node.dont-reconnect", True)
                    element.set_property("stream-properties", props)
                    element.set_property("buffer-time", 60000)
                    element.set_property("latency-time", 10000)
            player = Gst.ElementFactory.make("playbin")
            player.set_property("uri", path.resolve().as_uri())
            player.set_property("flags", 2)  # audio only; never open a video window
            player.set_property("audio-sink", sink)
            record = {'pipeline': player, 'sound_id': sound_id, 'mode': mode, 'volume': volume,
                      'tile_id': tile_id, 'instance_id': uuid.uuid4().hex}
            self.players.append(record)
            self._apply_volumes()
            self.last_error = None
            if player.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
                self._finish(record)
                raise AudioError("Playback could not start. Check the selected output device.")

    def _finish(self, record):
        record['pipeline'].set_state(Gst.State.NULL)
        self.players.remove(record)

    def stop(self, sound_id=None):
        with self.lock:
            for record in list(self.players):
                if sound_id is None or record['sound_id'] == sound_id:
                    self._finish(record)

    def status(self):
        with self.lock:
            current = self.players[-1] if self.players else None
            position, duration = 0.0, 0.0
            if current:
                ok, value = current['pipeline'].query_position(Gst.Format.TIME)
                position = value / Gst.SECOND if ok else 0
                ok, value = current['pipeline'].query_duration(Gst.Format.TIME)
                duration = value / Gst.SECOND if ok else 0
            return {"connected": self.connected, "virtual_microphone": "TuxCue Microphone",
                    "virtual_source_name": self.source_name, "settings": dict(self.settings),
                    "playing_id": current['sound_id'] if current else None,
                    "mode": current['mode'] if current else None,
                    "position": position, "duration": duration, "error": self.last_error,
                    "playing": [{k:v for k,v in r.items() if k != 'pipeline'} for r in self.players]}

    def _watch(self):
        next_health = 0.0
        while not self._closed.wait(0.05):
            with self.lock:
                try:
                    for record in list(self.players):
                        message = record['pipeline'].get_bus().pop_filtered(Gst.MessageType.ERROR | Gst.MessageType.EOS)
                        if message:
                            if message.type == Gst.MessageType.ERROR:
                                err, detail = message.parse_error()
                                LOG.warning("Playback error: %s (%s)", err, detail)
                                self.last_error = "Playback stopped: " + err.message
                            self._finish(record)
                    if (self.connected or self.players) and time.monotonic() > next_health:
                        next_health = time.monotonic() + 2
                        devices = self.devices(refresh=True)
                        if self.settings["output"] not in {d["name"] for d in devices["outputs"]}:
                            raise AudioError("Listening device disconnected. Select a device and reconnect.")
                        if self.connected:
                            if self.settings["mic_enabled"] and self.settings["microphone"] not in {d["name"] for d in devices["inputs"]}:
                                raise AudioError("Microphone disconnected. Select a device and reconnect.")
                            active = module_list()
                            if not all(any(m["index"] == own["index"] and m["argument"] == own["argument"]
                                           for m in active) for own in self.modules):
                                raise AudioError("Audio routing was interrupted. Reconnect the virtual microphone.")
                except AudioError as e:
                    self.last_error = str(e)
                    self.stop()
                    self.connected = False
                    try:
                        self._cleanup_modules()
                    except AudioError:
                        pass
                except Exception:
                    LOG.exception("Unexpected audio watcher error")
                    self.last_error = "Audio monitoring failed. Restart the soundboard."
                    self.stop()

    def close(self):
        self._closed.set()
        self.thread.join(timeout=6)
        try:
            self.disconnect()
        except AudioError:
            LOG.exception("Cleanup deferred until next launch")
