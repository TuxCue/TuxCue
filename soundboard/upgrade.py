"""Coordinate local launchers and gracefully hand over from older releases."""
from dataclasses import dataclass
import errno
import fcntl
import json
import os
from pathlib import Path
import re
import socket
import time
import urllib.error
import urllib.request

from .storage import active_folder, folder_path, MOVED_MARKER


class LaunchError(RuntimeError):
    pass


class StartupLock:
    """A per-user/port Linux abstract socket; released automatically on process exit."""
    def __init__(self, port):
        self.address = f'\0tuxcue-startup-{os.getuid()}-{port}'
        self.socket = None

    def acquire(self, timeout=35):
        deadline = time.monotonic() + timeout
        while True:
            handle = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                handle.bind(self.address)
                self.socket = handle
                return self
            except OSError as error:
                handle.close()
                if error.errno != errno.EADDRINUSE:
                    raise LaunchError(f'Could not coordinate TuxCue startup: {error}') from error
                if time.monotonic() >= deadline:
                    raise LaunchError('Another TuxCue launch is still in progress. Wait a moment and try again.')
                time.sleep(.1)

    def release(self):
        if self.socket is not None:
            self.socket.close()
            self.socket = None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def local_request(port, path, body=None):
    # Never send the shutdown request through a proxy or follow it to another service.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(f'http://127.0.0.1:{port}{path}',
        data=None if body is None else json.dumps(body).encode(),
        headers={} if body is None else {'Content-Type':'application/json','X-Soundboard-Request':'1'})
    with opener.open(request, timeout=3) as response:
        payload = response.read(16 * 1024 * 1024 + 1)
        if len(payload) > 16 * 1024 * 1024:
            raise LaunchError('The service on this port returned an unexpectedly large response.')
        return json.loads(payload)


def probe(port):
    try:
        state = local_request(port, '/api/state')
    except urllib.error.URLError as error:
        if isinstance(error.reason, OSError) and error.reason.errno == errno.ECONNREFUSED:
            return None
        raise LaunchError(f'Cannot identify the service on port {port}. It has been left running.') from error
    except (OSError, ValueError) as error:
        raise LaunchError(f'Cannot identify the service on port {port}. It has been left running.') from error
    if not isinstance(state, dict) or state.get('app') != 'TuxCue':
        raise LaunchError(f'Port {port} belongs to another service. Choose a different --port.')
    return state


def release_version(value):
    # Unknown/development version formats are never grounds for stopping an existing app.
    if not isinstance(value, str) or not re.fullmatch(r'\d+\.\d+\.\d+', value):
        return None
    return tuple(int(part) for part in value.split('.'))


def selected_collection(project, override=None):
    if override is not None:
        return folder_path(override)
    config = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config')/'tuxcue/storage.json'
    if config.exists():
        return active_folder(folder_path(json.loads(config.read_text())['folder']))
    legacy = Path(project)/'.state'
    if (legacy/MOVED_MARKER).exists():
        return active_folder(legacy)
    if (legacy/'library/library.json').exists() or (legacy/'sets.json').exists():
        return legacy.resolve()
    return (Path.home()/'TuxCue').resolve()


def collection_released(directory):
    # Opening the existing lock does not create or modify collection metadata.
    try:
        fd = os.open(directory/'app.lock', os.O_RDWR | os.O_NOFOLLOW)
    except FileNotFoundError:
        return directory.is_dir()
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        fcntl.flock(fd, fcntl.LOCK_UN)
        return True
    finally:
        os.close(fd)


def wait_for_shutdown(port, directory, timeout=30):
    deadline = time.monotonic() + timeout
    while True:
        with socket.socket() as sock:
            sock.settimeout(.2)
            port_free = sock.connect_ex(('127.0.0.1', port)) == errno.ECONNREFUSED
        if port_free and collection_released(directory):
            return
        if time.monotonic() >= deadline:
            raise LaunchError('The previous TuxCue is still shutting down. Let it finish, then launch the new version again. No process was force-stopped.')
        time.sleep(.1)


@dataclass
class LaunchPlan:
    reuse: bool = False
    reconnect: bool = False
    replaced_folder: Path | None = None


def prepare_launch(port, version, project, override=None):
    state = probe(port)
    if state is None:
        return LaunchPlan()
    expected = selected_collection(project, override)
    running_folder = state.get('storage', {}).get('folder')
    if not running_folder or folder_path(running_folder) != expected:
        raise LaunchError(f'A different TuxCue collection is already using port {port}. Use a different --port for this collection.')
    if override is None and state.get('storage', {}).get('can_change') is False:
        raise LaunchError('This TuxCue was launched with a temporary collection override. Close it first or use the same --data-dir.')
    current, incoming = release_version(state.get('version')), release_version(version)
    if current is None or incoming is None or incoming <= current:
        print(f"TuxCue {state.get('version', 'unknown')} is already running; opening that instance.", flush=True)
        return LaunchPlan(reuse=True)
    print(f"Updating running TuxCue {state['version']} to {version}. Waiting for a clean shutdown…", flush=True)
    # Check identity again immediately before the legacy-compatible shutdown request.
    fresh = probe(port)
    if fresh is None:
        wait_for_shutdown(port, expected)
        return LaunchPlan(reconnect=bool(state.get('connected')), replaced_folder=expected)
    if (fresh.get('instance_id'), fresh.get('version'), fresh.get('storage')) != (state.get('instance_id'), state.get('version'), state.get('storage')):
        raise LaunchError('The running TuxCue changed during startup. Please launch the new version again.')
    body = {'expected_instance_id': fresh['instance_id']} if fresh.get('instance_id') else {}
    try:
        result = local_request(port, '/api/shutdown', body)
    except (OSError, ValueError) as error:
        raise LaunchError('The previous TuxCue did not confirm shutdown. It has not been force-stopped; try again once it has closed.') from error
    if not isinstance(result, dict) or result.get('ok') is not True:
        raise LaunchError('The previous TuxCue refused shutdown. Close it normally before retrying.')
    # New releases return the state captured at shutdown; old AppImages return only ok.
    reconnect = bool(result.get('connected', fresh.get('connected', False)))
    actual_folder = folder_path(result.get('storage_folder', running_folder))
    if actual_folder != expected:
        raise LaunchError('The collection moved during shutdown. Launch again to use its saved location.')
    wait_for_shutdown(port, actual_folder)
    if selected_collection(project, override) != expected:
        raise LaunchError('The saved collection changed during shutdown. Launch again to use its new location.')
    return LaunchPlan(reconnect=reconnect, replaced_folder=actual_folder)
