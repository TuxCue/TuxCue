import argparse
import re
from pathlib import Path
import subprocess
import sys
import threading
import time

import uvicorn
from .server import create_app
from .storage import Storage
from .runtime import setup_bundled_tools, open_browser, self_check
from .tray import start_tray, run_tray
from .audio import AudioEngine
from . import __version__
from .upgrade import StartupLock, LaunchError, prepare_launch


def main():
    setup_bundled_tools()
    parser = argparse.ArgumentParser(description='Run TuxCue, a local Linux soundboard')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--data-dir', type=Path, help='Temporary storage override; disables changing the saved folder in Settings')
    parser.add_argument('--no-browser', action='store_true', help='Do not open a browser automatically')
    parser.add_argument('--open-browser', action='store_true', help='Open the interface when the service is ready')
    parser.add_argument('--no-tray', action='store_true', help='Run without a system-tray icon')
    parser.add_argument('--self-check', action='store_true', help='Check packaged components without starting the app')
    parser.add_argument('--tray-worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--parent-pid', type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument('--audio-prefix', default='soundboard', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('Choose a port between 1 and 65535.')
    if not re.fullmatch(r'[a-zA-Z0-9_]{1,64}', args.audio_prefix):
        parser.error('Invalid audio namespace.')
    if args.tray_worker:
        return run_tray(args.port, args.parent_pid)
    if args.self_check:
        self_check(); return 0
    url = f'http://127.0.0.1:{args.port}'
    show_browser = not args.no_browser and (args.open_browser or getattr(sys, 'frozen', False))
    project = Path(__file__).resolve().parent.parent
    tray = [None]
    first_start = True
    guard = StartupLock(args.port)
    try:
        guard.acquire()
        plan = prepare_launch(args.port, __version__, project, args.data_dir)
        if plan.reuse:
            if show_browser:
                # The short-lived launcher must let its browser worker start before exiting.
                open_browser(url).join(timeout=9)
            return 0
        reconnect = plan.reconnect
        while True:
            try:
                storage = Storage.open(project, override=args.data_dir)
            except (ValueError, OSError) as error:
                print(f'TuxCue: {error}', file=sys.stderr)
                return 1
            restart = {'requested': False, 'reconnect': False}
            ready_stop = threading.Event()
            ready_thread = None
            try:
                print(f'TuxCue: {url}\nCollection: {storage.directory}', flush=True)
                app = create_app(project, storage.directory, storage=storage,
                                 audio_factory=lambda directory: AudioEngine(directory, prefix=args.audio_prefix))
                server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=args.port,
                    access_log=False, proxy_headers=False, loop='asyncio', http='h11', ws='none'))
                app.state.shutdown = lambda: setattr(server, 'should_exit', True)
                def restart_app():
                    restart['requested'] = True
                    restart['reconnect'] = app.state.audio.status()['connected']
                    server.should_exit = True
                app.state.restart = restart_app
                def show_when_ready():
                    for _ in range(300):
                        if ready_stop.is_set() or server.should_exit:
                            return
                        if server.started:
                            if reconnect:
                                try:
                                    app.state.audio.connect()
                                except Exception as error:
                                    app.state.audio.last_error = str(error)
                            if not args.no_tray and (tray[0] is None or tray[0].poll() is not None):
                                tray[0] = start_tray(args.port)
                            if first_start and show_browser:
                                open_browser(url)
                            guard.release()
                            return
                        time.sleep(.05)
                ready_thread = threading.Thread(target=show_when_ready, name='desktop-startup', daemon=True)
                ready_thread.start()
                server.run()
            finally:
                ready_stop.set()
                if ready_thread:
                    ready_thread.join(timeout=10)
                storage.close()
            if not restart['requested']:
                break
            reconnect = restart['reconnect']
            first_start = False
    except (LaunchError, ValueError, OSError) as error:
        print(f'TuxCue: {error}', file=sys.stderr, flush=True)
        return 1
    finally:
        guard.release()
        if tray[0] is not None and tray[0].poll() is None:
            tray[0].terminate()
            try:
                tray[0].wait(timeout=3)
            except subprocess.TimeoutExpired:
                tray[0].kill(); tray[0].wait()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
