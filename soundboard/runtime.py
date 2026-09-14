"""Paths and native launch helpers shared by source and AppImage builds."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import urllib.request
from . import __version__


def setup_bundled_tools():
    if getattr(sys,'frozen',False):
        os.environ.setdefault('TUXCUE_ORIGINAL_PATH',os.environ.get('PATH','/usr/bin:/bin'))
        os.environ['PATH']=str(Path(sys._MEIPASS)/'bin')+os.pathsep+os.environ['TUXCUE_ORIGINAL_PATH']


# Captured before PyInstaller's GTK/GIO/GStreamer hooks modify the environment.
# The tray inherits this snapshot instead of treating the parent's bundled paths as host paths.
HOST_ENVIRONMENT_KEY = 'TUXCUE_HOST_ENVIRONMENT'
HOST_ENVIRONMENT_KEYS = (
    'PATH', 'LD_LIBRARY_PATH', 'XDG_DATA_DIRS', 'GI_TYPELIB_PATH',
    'GTK_DATA_PREFIX', 'GTK_EXE_PREFIX', 'GTK_PATH', 'GIO_MODULE_DIR',
    'GDK_PIXBUF_MODULE_FILE', 'PANGO_LIBDIR', 'PANGO_SYSCONFDIR',
    'GST_REGISTRY_FORK', 'GST_PLUGIN_PATH', 'GST_PLUGIN_SYSTEM_PATH', 'GST_REGISTRY',
    'GST_PLUGIN_PATH_1_0', 'GST_PLUGIN_SYSTEM_PATH_1_0', 'GST_REGISTRY_1_0',
    'PYTHONHOME', 'PYTHONPATH',
)


def _host_snapshot(env):
    try:
        snapshot = json.loads(env.get(HOST_ENVIRONMENT_KEY, ''))
        if (isinstance(snapshot, dict) and set(snapshot) == set(HOST_ENVIRONMENT_KEYS)
                and all(value is None or isinstance(value, str) for value in snapshot.values())):
            return snapshot
    except (TypeError, ValueError):
        pass
    return None


def capture_host_environment():
    if _host_snapshot(os.environ) is None:
        snapshot = {key: os.environ.get(key) for key in HOST_ENVIRONMENT_KEYS}
        # The bootloader changes the library path before even custom runtime hooks run.
        snapshot['LD_LIBRARY_PATH'] = os.environ.get('LD_LIBRARY_PATH_ORIG')
        os.environ[HOST_ENVIRONMENT_KEY] = json.dumps(snapshot)


def browser_environment():
    env = dict(os.environ)
    if not getattr(sys, 'frozen', False):
        return env
    snapshot = _host_snapshot(env)
    if snapshot is None:
        # Defensive fallback for an incomplete package, without leaking its GTK modules.
        original_data = env.get('XDG_DATA_DIRS', '/usr/local/share:/usr/share')
        bundle = str(Path(sys._MEIPASS))
        snapshot = {key: None for key in HOST_ENVIRONMENT_KEYS}
        snapshot.update(PATH=env.get('TUXCUE_ORIGINAL_PATH', '/usr/bin:/bin'),
                        LD_LIBRARY_PATH=env.get('LD_LIBRARY_PATH_ORIG'),
                        XDG_DATA_DIRS=os.pathsep.join(part for part in original_data.split(os.pathsep)
                                                     if part and not (part == bundle or part.startswith(bundle + os.sep))))
    for key, value in snapshot.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    for key in list(env):
        if key.startswith('_PYI_') or key in (HOST_ENVIRONMENT_KEY, 'TUXCUE_ORIGINAL_PATH',
                                              'LD_LIBRARY_PATH_ORIG', '_MEIPASS2'):
            env.pop(key, None)
    return env


def open_browser(url, on_result=None):
    """Launch the user's browser without blocking GTK, and report immediate failures."""
    env = browser_environment()
    def launch():
        error = None
        try:
            # Some launchers stay alive for as long as the browser. Never kill it on timeout.
            with tempfile.TemporaryFile(mode='w+t') as diagnostics:
                process = subprocess.Popen(['xdg-open', url], env=env, start_new_session=True,
                                           stdout=subprocess.DEVNULL, stderr=diagnostics)
                try:
                    code = process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    code = None
                if code not in (0, None):
                    diagnostics.seek(0)
                    detail = diagnostics.read(4000).strip()
                    error = f'Browser launcher exited with status {code}' + (f': {detail}' if detail else '.')
        except OSError as problem:
            error = str(problem)
        if error:
            print(f'TuxCue: {error}\nOpen {url} in your browser.', file=sys.stderr, flush=True)
        if on_result:
            on_result(error is None, error)
    worker = threading.Thread(target=launch, name='open-browser', daemon=True)
    worker.start()
    return worker


def self_check():
    from .audio import Gst
    plugins=['playbin','tee','queue','audioconvert','audioresample','volume','pulsesink','wavparse']
    missing=[name for name in plugins if not Gst.ElementFactory.find(name)]
    versions={}
    for name in ('ffmpeg','ffprobe','pactl'):
        result=subprocess.run([name,'-version' if name.startswith('ff') else '--version'],capture_output=True,text=True,timeout=10)
        if result.returncode:raise RuntimeError(f'{name} could not start: {result.stderr}')
        versions[name]=result.stdout.splitlines()[0]
    if missing:raise RuntimeError('Missing audio components: '+', '.join(missing))
    from qrcode import QRCode
    from qrcode.image.svg import SvgPathFillImage
    qr=QRCode();qr.add_data('TuxCue self-check');qr.make(fit=True)
    assert b'<svg' in qr.make_image(image_factory=SvgPathFillImage).to_string()
    import gi
    gi.require_version('Gtk','3.0');gi.require_version('AyatanaAppIndicator3','0.1')
    from gi.repository import Gtk, AyatanaAppIndicator3
    print(json.dumps({'tray_components':'ok','qr_codes':'ok','app':'TuxCue','version':__version__,'python':sys.version.split()[0],
                      'gstreamer':Gst.version_string(),'tools':versions,'audio_components':'ok'},indent=2))
