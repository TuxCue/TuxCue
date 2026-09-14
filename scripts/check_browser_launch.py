#!/usr/bin/env python3
"""Exercise the frozen browser-launch path with a recording xdg-open executable."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

project = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project))
from soundboard.runtime import HOST_ENVIRONMENT_KEYS

parser = argparse.ArgumentParser()
parser.add_argument('--appimage', type=Path, default=os.environ.get('TUXCUE_APPIMAGE'))
parser.add_argument('--expect-leak', action='store_true', help='Reproduce the failure in an older AppImage')
args = parser.parse_args()
if args.appimage is None:
    parser.error('Set TUXCUE_APPIMAGE or pass --appimage with the candidate path.')
with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
url = f'http://127.0.0.1:{port}'
with tempfile.TemporaryDirectory(prefix='browser-launch-') as folder:
    root = Path(folder)
    launchers = root/'bin'; launchers.mkdir()
    capture = root/'capture.json'
    launcher = launchers/'xdg-open'
    launcher.write_text('''#!/usr/bin/python3
import json,os,sys
from pathlib import Path
keys = ''' + repr(HOST_ENVIRONMENT_KEYS) + '''
data = {'argv':sys.argv[1:], 'environment':{key:os.environ.get(key) for key in keys}}
file = Path(os.environ['TUXCUE_BROWSER_CAPTURE'])
temporary = file.with_suffix('.tmp')
temporary.write_text(json.dumps(data)); temporary.replace(file)
if any(value and ('appimage_extracted_' in value or '/_internal' in value) for value in data['environment'].values()):
    print('Browser rejected bundled library paths', file=sys.stderr)
    sys.exit(3)
''')
    launcher.chmod(0o755)
    env = dict(os.environ, PATH=str(launchers)+os.pathsep+os.environ.get('PATH','/usr/bin:/bin'),
               TUXCUE_BROWSER_CAPTURE=str(capture))
    expected = {key:env.get(key) for key in HOST_ENVIRONMENT_KEYS}
    log = root/'service.log'
    with log.open('w') as output:
        proc = subprocess.Popen([str(args.appimage.resolve()), '--appimage-extract-and-run',
                                 '--no-tray', '--open-browser', '--port', str(port),
                                 '--data-dir', str(root/'collection'), '--audio-prefix', 'tuxcue_browser_qa'],
                                env=env, stdout=output, stderr=subprocess.STDOUT)
        try:
            for _ in range(200):
                if capture.exists(): break
                if proc.poll() is not None: raise AssertionError(log.read_text())
                time.sleep(.05)
            else: raise AssertionError('No browser launch was recorded: '+log.read_text())
            data = json.loads(capture.read_text())
            assert data['argv'] == [url], data['argv']
            contaminated = [key for key,value in data['environment'].items()
                            if value and ('appimage_extracted_' in value or '/_internal' in value)]
            if args.expect_leak:
                assert contaminated, 'The old build did not reproduce the environment leak'
                result = {'reproduced': 'Bundled paths passed to the desktop browser launcher', 'keys': contaminated}
            else:
                assert not contaminated, contaminated
                assert data['environment'] == expected, {key:(expected[key],data['environment'][key])
                                                        for key in expected if expected[key] != data['environment'][key]}
                result = {'passed': ['Frozen startup calls xdg-open with the correct local URL',
                                     'Host environment restored before GTK/GIO/GStreamer hooks',
                                     'No bundled library paths passed to the browser'], 'appimage':args.appimage.name}
            print(json.dumps(result, indent=2))
        finally:
            if proc.poll() is None:
                try:
                    request = urllib.request.Request(url+'/api/shutdown', b'{}', headers={
                        'Content-Type':'application/json','X-Soundboard-Request':'1'})
                    urllib.request.urlopen(request,timeout=3).close()
                except OSError:
                    proc.terminate()
                try: proc.wait(timeout=5)
                except subprocess.TimeoutExpired: proc.kill(); proc.wait()
