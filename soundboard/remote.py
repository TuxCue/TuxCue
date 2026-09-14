"""Opt-in LAN controller with a separate listener and revocable phone sessions."""
from __future__ import annotations

from collections import defaultdict, deque
import fcntl
import hashlib
import ipaddress
import json
from pathlib import Path
import secrets
import socket
import struct
import threading
import time

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
import qrcode
from qrcode.image.svg import SvgPathFillImage
import uvicorn

from .audio import AudioError
from .library import atomic_json

COOKIE = 'tuxcue_phone'
SESSION_SECONDS = 30 * 24 * 3600
PAIR_SECONDS = 300
LAN_NETWORKS = tuple(ipaddress.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '169.254.0.0/16', '127.0.0.0/8'))


def lan_address(value):
    try:
        address = ipaddress.ip_address(value)
        return any(address in network for network in LAN_NETWORKS)
    except ValueError:
        return False


def network_addresses():
    result = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        for _, name in socket.if_nameindex():
            try:
                packed = struct.pack('256s', name.encode()[:15])
                flags = struct.unpack_from('H', fcntl.ioctl(sock, 0x8913, packed), 16)[0]
                address = socket.inet_ntoa(fcntl.ioctl(sock, 0x8915, packed)[20:24])
                if flags & 1 and lan_address(address) and not address.startswith('127.'):
                    result.append({'address': address, 'interface': name})
            except OSError:
                continue
    # Physical Wi-Fi/Ethernet entries precede bridges and VPN interfaces.
    return sorted(result, key=lambda i: (not i['interface'].startswith(('en', 'eth', 'wl')), i['interface']))


class PairRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(default='Phone', min_length=1, max_length=40)


class TileRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    set_id: str = Field(min_length=1, max_length=64)
    tile_id: str = Field(min_length=1, max_length=64)
    mode: str = Field(default='play', pattern='^(play|preview)$')


class SetRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    set_id: str = Field(min_length=1, max_length=64)


class RemoteControl:
    def __init__(self, settings_file: Path, frontend: Path, snapshot, play, stop, switch):
        self.settings_file = settings_file
        self.lock = threading.RLock()
        self.lifecycle = threading.Lock()
        self.settings = {'enabled': False, 'port': 8766, 'devices': {}}
        if settings_file.exists():
            self.settings.update(json.loads(settings_file.read_text()))
        self.server = self.thread = self.sock = None
        self.error = None
        self.pairing = None
        self.failures = defaultdict(deque)
        self.app = self._app(frontend, snapshot, play, stop, switch)

    @property
    def running(self):
        return bool(self.server and self.server.started and self.thread and self.thread.is_alive() and not self.server.should_exit)

    def _save(self, settings):
        atomic_json(self.settings_file, settings)
        self.settings = settings

    def status(self):
        with self.lock:
            now = time.time()
            ticket = self.pairing if self.pairing and self.pairing['expires_at'] > now else None
            return {'enabled': self.settings['enabled'], 'running': self.running,
                    'port': self.settings['port'], 'error': self.error,
                    'addresses': network_addresses(), 'pairing': ticket,
                    'devices': [{'id': key, 'name': item['name'], 'paired_at': item['paired_at'], 'expires_at': item['expires_at']}
                                for key, item in self.settings['devices'].items() if item['expires_at'] > now]}

    def pair_ticket(self):
        with self.lock:
            if not self.running:
                raise ValueError('Enable Remote control before pairing a phone.')
            self.pairing = {'token': secrets.token_urlsafe(32), 'code': f'{secrets.randbelow(100_000_000):08d}',
                            'expires_at': time.time() + PAIR_SECONDS}
            return self.status()

    def qr(self, address):
        with self.lock:
            if address not in {i['address'] for i in network_addresses()}:
                raise ValueError('Choose one of this PC’s network addresses.')
            if not self.running or not self.pairing or self.pairing['expires_at'] <= time.time():
                raise ValueError('Create a new pairing code on the PC.')
            url = f"http://{address}:{self.settings['port']}/#pair={self.pairing['token']}"
            return qrcode.make(url, image_factory=SvgPathFillImage, border=4).to_string()

    def forget(self, device_id=None):
        with self.lock:
            devices = dict(self.settings['devices'])
            if device_id:
                devices.pop(device_id, None)
            else:
                devices = {}
                self.pairing = None
            self._save({**self.settings, 'devices': devices})
            return self.status()

    def _start(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('0.0.0.0', self.settings['port']))
            sock.listen(64)
            self.sock = sock
            self.server = uvicorn.Server(uvicorn.Config(self.app, access_log=False, log_level='warning',
                proxy_headers=False, loop='asyncio', http='h11', ws='none', lifespan='off', timeout_graceful_shutdown=2))
            self.thread = threading.Thread(target=lambda: self.server.run(sockets=[sock]), name='phone-control', daemon=True)
            self.thread.start()
            for _ in range(250):
                if self.running:
                    self.error = None
                    return
                if not self.thread.is_alive():
                    break
                time.sleep(.02)
            raise ValueError('The phone listener could not start. Try another port.')
        except OSError as error:
            self._stop()
            sock.close()
            raise ValueError(f"Could not open phone port {self.settings['port']}. Choose another unused port.") from error
        except Exception:
            self._stop()
            sock.close()
            raise

    def _stop(self):
        if self.server:
            self.server.should_exit = True
        if self.thread:
            self.thread.join(timeout=4)
        if self.sock:
            self.sock.close()
        self.server = self.thread = self.sock = None

    def restore(self):
        if self.settings['enabled']:
            with self.lifecycle:
                try:
                    self._start()
                except (OSError, ValueError) as error:
                    self.error = str(error)

    def configure(self, enabled, port):
        if not 1024 <= port <= 65535:
            raise ValueError('Choose a phone port between 1024 and 65535.')
        with self.lifecycle:
            old = dict(self.settings)
            if self.running and enabled and port != old['port']:
                raise ValueError('Disable Remote control before changing its port.')
            if enabled:
                with self.lock:
                    self.settings = {**old, 'enabled': True, 'port': port}
                try:
                    if not self.running:
                        self._start()
                    with self.lock:
                        self._save(self.settings)
                except Exception:
                    self._stop()
                    with self.lock:
                        self.settings = old
                    raise
            else:
                # Revoke access before waiting for the listener to close.
                with self.lock:
                    self._save({**old, 'enabled': False, 'port': port, 'devices': {}})
                    self.pairing = None
                self._stop()
                self.error = None
            return self.status()

    def close(self):
        with self.lifecycle:
            self._stop()

    def _session(self, token):
        if not token or len(token) > 100:
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        now = time.time()
        with self.lock:
            return next((key for key, value in self.settings['devices'].items()
                         if value['expires_at'] > now and secrets.compare_digest(value['hash'], digest)), None)

    def _pair(self, body, peer):
        with self.lock:
            now = time.time()
            if len(self.failures) > 512:
                self.failures.clear()
            for key in (peer, '*'):
                attempts = self.failures[key]
                while attempts and attempts[0] < now - 60:
                    attempts.popleft()
                if len(attempts) >= (5 if key == peer else 30):
                    return JSONResponse({'detail': 'Too many pairing attempts. Wait a minute and try again.'}, status_code=429)
            ticket = self.pairing
            code = body.code.replace(' ', '').replace('-', '')
            valid = ticket and ticket['expires_at'] > now and (secrets.compare_digest(body.code.encode(), ticket['token'].encode()) or secrets.compare_digest(code.encode(), ticket['code'].encode()))
            if not valid:
                self.failures[peer].append(now); self.failures['*'].append(now)
                return JSONResponse({'detail': 'That pairing code expired or is incorrect. Create a new code on the PC.'}, status_code=401)
            devices = {k: v for k, v in self.settings['devices'].items() if v['expires_at'] > now}
            if len(devices) >= 10:
                raise ValueError('Ten phones are already paired. Forget one in the PC’s Remote control settings.')
            token, key = secrets.token_urlsafe(32), secrets.token_hex(12)
            devices[key] = {'hash': hashlib.sha256(token.encode()).hexdigest(), 'name': body.name.strip() or 'Phone',
                            'paired_at': now, 'expires_at': now + SESSION_SECONDS}
            self._save({**self.settings, 'devices': devices})
            self.pairing = None  # A code can pair one phone only.
            response = JSONResponse({'ok': True})
            response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True, samesite='strict', path='/')
            return response

    def _app(self, frontend, snapshot, play, stop, switch):
        app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

        @app.middleware('http')
        async def protect(request, call_next):
            host, peer = request.url.hostname, request.client.host if request.client else ''
            if (host != 'localhost' and not lan_address(host or '')) or not lan_address(peer):
                return JSONResponse({'detail': 'Phone control is available on your local network only.'}, status_code=403)
            if not self.settings['enabled']:
                return JSONResponse({'detail': 'Remote control was disabled on the PC.'}, status_code=503)
            path = request.url.path
            if request.method not in ('GET', 'HEAD'):
                if (request.headers.get('x-tuxcue-remote') != '1'
                        or request.headers.get('origin') not in (None, f'{request.url.scheme}://{request.url.netloc}')):
                    return JSONResponse({'detail': 'Open the paired TuxCue controller to use these buttons.'}, status_code=403)
                length = request.headers.get('content-length', '')
                if not length.isdigit() or int(length) > 4096:
                    return JSONResponse({'detail': 'The controller request exceeds the size limit.'}, status_code=413)
            if path.startswith('/remote/api/') and path != '/remote/api/pair':
                device = self._session(request.cookies.get(COOKIE))
                if device is None:
                    return JSONResponse({'detail': 'Pair this phone using Remote control settings on your PC.'}, status_code=401)
                request.state.device = device
            response = await call_next(request)
            response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                'Referrer-Policy': 'no-referrer',
                'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"})
            return response

        @app.exception_handler(AudioError)
        @app.exception_handler(ValueError)
        async def expected_error(request, error):
            return JSONResponse({'detail': str(error)}, status_code=400)

        @app.post('/remote/api/pair')
        def pair(body: PairRequest, request: Request):
            return self._pair(body, request.client.host)

        @app.get('/remote/api/state')
        def state():
            return snapshot()

        @app.post('/remote/api/play')
        def play_tile(body: TileRequest):
            play(body.set_id, body.tile_id, body.mode)
            return {'ok': True}

        @app.post('/remote/api/stop')
        def stop_all():
            stop()
            return {'ok': True}

        @app.post('/remote/api/set')
        def set_profile(body: SetRequest):
            switch(body.set_id)
            return {'ok': True}

        @app.post('/remote/api/leave')
        def leave(request: Request):
            self.forget(request.state.device)
            response = JSONResponse({'ok': True})
            response.delete_cookie(COOKIE, path='/')
            return response

        if (frontend/'assets').is_dir():
            app.mount('/assets', StaticFiles(directory=frontend/'assets'), name='assets')

        @app.get('/tuxcue-logo.png')
        def logo():
            return FileResponse(frontend/'tuxcue-logo.png', media_type='image/png')

        @app.get('/license')
        def license_text():
            return FileResponse(frontend/'licenses/LICENSE', media_type='text/plain')

        @app.get('/')
        def index():
            if not (frontend/'remote.html').is_file():
                return JSONResponse({'detail': 'Build the phone interface before enabling Remote control.'}, status_code=503)
            return FileResponse(frontend/'remote.html')

        return app
