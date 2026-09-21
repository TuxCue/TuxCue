"""Loopback-only API and the compiled browser interface."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import tempfile
import threading
import uuid
from typing import Literal

from fastapi import FastAPI, Request, UploadFile, Query, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .audio import AudioEngine, AudioError
from .library import Library, MAX_BYTES
from .boards import Boards
from .hotkeys import Hotkeys
from .bundles import export_set, import_set, MAX_UNPACKED
from .storage import browse_folders
from .remote import RemoteControl
from . import __version__


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class SettingsChange(StrictModel):
    microphone: str | None = None
    output: str | None = None
    mic_enabled: bool | None = None
    send_volume: float | None = Field(default=None, ge=0, le=1)
    monitor_volume: float | None = Field(default=None, ge=0, le=1)
    mic_volume: float | None = Field(default=None, ge=0, le=1)


class PlayRequest(StrictModel):
    sound_id: str
    tile_id: str | None = None
    mode: Literal['broadcast', 'preview'] = 'broadcast'


class Name(StrictModel):
    name: str = Field(min_length=1, max_length=120)


class Selection(StrictModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    gain_db: float = Field(default=0, ge=-24, le=12)
    fade_in: float = Field(default=0, ge=0)
    fade_out: float = Field(default=0, ge=0)


class SaveSelection(Selection):
    name: str = Field(min_length=1, max_length=120)


class NewSet(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    duplicate_id: str | None = None


class SetChange(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    rows: int | None = Field(default=None, ge=1, le=12)
    columns: int | None = Field(default=None, ge=1, le=12)
    playback_mode: Literal['replace','overlap'] | None = None
    hotkeys_enabled: bool | None = None
    stop_shortcut: str | None = None


class TileChange(StrictModel):
    sound_id: str | None = None
    label: str | None = Field(default=None, max_length=120)
    color: str | None = None
    volume: float | None = Field(default=None, ge=0, le=1)
    shortcut: str | None = None


class SoundId(StrictModel):
    sound_id: str


class Move(StrictModel):
    source: int = Field(ge=0,lt=1000)
    target: int = Field(ge=0,lt=1000)


class TileIndexes(StrictModel):
    indexes: list[int] = Field(min_length=1, max_length=1000)


class GlobalSettings(StrictModel):
    hotkeys_enabled: bool | None = None
    stop_shortcut: str | None = None


class Suspend(StrictModel):
    seconds: float = Field(default=30,ge=0,le=60)


class StorageChange(StrictModel):
    folder: str = Field(min_length=1, max_length=4096)


class ShutdownRequest(StrictModel):
    expected_instance_id: str | None = None


class RemoteSettings(StrictModel):
    enabled: bool
    port: int = Field(default=8766, ge=1024, le=65535)


class NoHotkeys:
    def __init__(self, callback): pass
    def state(self): return {'available':False,'enabled':False,'error':None,'conflicts':[],'suspended':False}
    def configure(self,*args,**kwargs): pass
    def suspend(self,*args): pass
    def close(self): pass


def create_app(project: Path, state_dir: Path | None = None, audio_factory=AudioEngine, hotkeys_factory=Hotkeys, storage=None):
    state_dir = state_dir or project / '.state'
    state_dir.mkdir(parents=True, exist_ok=True)
    # Early development collections could recover original files from this folder.
    library = Library(state_dir / 'library', legacy_originals=project / 'sound-files')
    boards = Boards(state_dir/'sets.json',library)
    importing = threading.Lock()
    mutations = threading.RLock()
    actions = threading.RLock()
    play_epoch = [0]
    preview_path = state_dir/'editor-preview.wav'

    def play(engine, sound_id, mode, tile_id=None):
        volume, overlap = 1.0, False
        if tile_id:
            profile = boards.active()
            chosen = next((t for t in profile['tiles'] if t and t['id']==tile_id),None)
            if chosen is None or chosen['sound_id']!=sound_id:
                raise ValueError('That tile is no longer in the active set.')
            volume = chosen['volume']
            overlap = profile['playback_mode']=='overlap'
        with actions:
            play_epoch[0] += 1
            engine.play(library.path(sound_id),sound_id,mode,volume=volume,overlap=overlap,tile_id=tile_id)

    def stop(engine):
        with actions:
            play_epoch[0] += 1
            engine.stop()

    @asynccontextmanager
    async def lifespan(app):
        engine = audio_factory(state_dir)
        app.state.audio = engine
        def triggered(action):
            try:
                if action=='__stop__':
                    stop(engine)
                else:
                    profile=boards.active()
                    t=next((t for t in profile['tiles'] if t and t['id']==action),None)
                    if t:
                        play(engine,t['sound_id'],'broadcast' if engine.status()['connected'] else 'preview',t['id'])
            except (AudioError,ValueError) as e:
                engine.last_error=str(e)
        hotkeys=hotkeys_factory(triggered)
        app.state.hotkeys=hotkeys
        def sync_hotkeys():
            data=boards.snapshot()
            active=data['profiles'][data['active_id']]
            ids={s['id'] for s in library.list()}
            mapping={t['id']:t['shortcut'] for t in active['tiles'] if t and t['sound_id'] in ids and t['shortcut']}
            if data['stop_shortcut']:
                mapping['__stop__']=data['stop_shortcut']
            hotkeys.configure(mapping,enabled=data['hotkeys_enabled'])
        boards.on_change=sync_hotkeys
        app.state.sync_hotkeys=sync_hotkeys
        sync_hotkeys()
        def phone_state():
            with mutations, actions:
                data=boards.snapshot()
                profile=data['profiles'][data['active_id']]
                sounds={s['id']:s for s in library.list()}
                status=engine.status()
                return {'app':'TuxCue','version':__version__,'connected':status['connected'],
                        'error':status.get('error'), 'playing':status.get('playing',[]),
                        'sets':[{'id':p['id'],'name':p['name']} for p in data['profiles'].values()],
                        'profile':{**profile,'tiles':[{**t,'name':sounds[t['sound_id']]['name'],
                            'duration':sounds[t['sound_id']]['duration'],'position':i+1}
                            for i,t in enumerate(profile['tiles']) if t and t['sound_id'] in sounds]}}
        def phone_play(set_id,tile_id,mode):
            with mutations, actions:
                profile=boards.active()
                if profile['id']!=set_id:
                    raise ValueError('The active set changed on the PC. Refresh the controller and try again.')
                tile=next((t for t in profile['tiles'] if t and t['id']==tile_id),None)
                if tile is None:
                    raise ValueError('That tile is no longer in the active set.')
                play(engine,tile['sound_id'],'preview' if mode=='preview' or not engine.status()['connected'] else 'broadcast',tile_id)
        def phone_switch(set_id):
            with mutations:
                boards.profile(boards.snapshot(),set_id)
                stop(engine)
                boards.switch(set_id)
        remote=RemoteControl(state_dir/'remote-settings.json',project/'frontend/dist',phone_state,
                             phone_play,lambda:stop(engine),phone_switch)
        app.state.remote=remote
        remote.restore()
        try:
            yield
        finally:
            remote.close()
            boards.on_change=None
            hotkeys.close()
            engine.close()

    app=FastAPI(title='TuxCue',version=__version__,lifespan=lifespan,docs_url=None,redoc_url=None)
    app.state.library=library
    app.state.boards=boards
    app.state.shutdown=None
    app.state.restart=None
    app.state.instance_id=uuid.uuid4().hex

    @app.middleware('http')
    async def local_only(request: Request, call_next):
        if request.url.hostname not in {'localhost','127.0.0.1','::1'}:
            return JSONResponse({'detail':'This soundboard accepts localhost connections only.'},status_code=403)
        if request.method not in {'GET','HEAD'}:
            origin=request.headers.get('origin')
            if request.headers.get('x-soundboard-request')!='1' or (origin and origin!=f'{request.url.scheme}://{request.url.netloc}'):
                return JSONResponse({'detail':'Open the soundboard on this PC to use these controls.'},status_code=403)
        length=request.headers.get('content-length')
        limit=MAX_UNPACKED+3*1024*1024 if request.url.path=='/api/sets/import' else MAX_BYTES+1024*1024
        if length and (not length.isdigit() or int(length)>limit):
            return JSONResponse({'detail':'The upload exceeds the size limit (100 MB per audio file, 515 MB per set bundle).'},status_code=413)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control']='no-store'
        return response

    @app.exception_handler(AudioError)
    @app.exception_handler(ValueError)
    async def expected_error(request,error):
        return JSONResponse({'detail':str(error)},status_code=400)

    @app.get('/api/state')
    def state(request: Request):
        engine=request.app.state.audio
        try:
            devices=engine.devices();device_error=None
        except AudioError as e:
            devices,device_error={'inputs':[],'outputs':[],'server':'Unavailable'},str(e)
        return {**engine.status(),'devices':devices,'device_error':device_error,'sounds':library.list(),
                'trash':library.list(trashed=True),'sets':boards.snapshot(),'hotkeys':request.app.state.hotkeys.state(),
                'importing':importing.locked(),'version':__version__,
                'app':'TuxCue','instance_id':request.app.state.instance_id,'storage':storage.info() if storage else {'folder':str(state_dir),'default_folder':str(Path.home()/'TuxCue'),'can_change':False}}

    @app.get('/api/storage/folders')
    def folders(path: str | None = None):
        return browse_folders(path)

    @app.get('/api/remote')
    def remote_status(request: Request):
        return request.app.state.remote.status()

    @app.post('/api/remote/settings')
    def remote_settings(body: RemoteSettings,request: Request):
        return request.app.state.remote.configure(body.enabled,body.port)

    @app.post('/api/remote/pairing')
    def remote_pairing(request: Request):
        return request.app.state.remote.pair_ticket()

    @app.get('/api/remote/qr')
    def remote_qr(address: str,request: Request):
        return Response(request.app.state.remote.qr(address),media_type='image/svg+xml')

    @app.post('/api/remote/forget')
    def remote_forget(request: Request):
        return request.app.state.remote.forget()

    @app.post('/api/remote/forget/{device_id}')
    def remote_forget_device(device_id: str,request: Request):
        return request.app.state.remote.forget(device_id)

    @app.post('/api/storage')
    def move_storage(body: StorageChange,request: Request):
        nonlocal state_dir, preview_path
        if storage is None:
            raise ValueError('Start TuxCue normally to change the collection folder.')
        engine=request.app.state.audio
        # Keep the existing audio streams alive; block writes while copying metadata.
        remote=request.app.state.remote
        with mutations, actions, engine.lock, library.lock, boards.lock, remote.lock:
            play_epoch[0]+=1
            result=storage.relocate(body.folder)
            state_dir=storage.directory
            preview_path=state_dir/'editor-preview.wav'
            library.directory=state_dir/'library'
            library.index=library.directory/'library.json'
            boards.path=state_dir/'sets.json'
            engine.settings_file=state_dir/'audio-settings.json'
            engine.module_file=state_dir/'audio-session.json'
            remote.settings_file=state_dir/'remote-settings.json'
            return result

    @app.post('/api/settings')
    def settings(change: SettingsChange,request: Request):
        request.app.state.audio.configure(change.model_dump(exclude_none=True));return {'ok':True}

    @app.post('/api/connect')
    def connect(request: Request):
        request.app.state.audio.connect();return {'ok':True}

    @app.post('/api/disconnect')
    def disconnect(request: Request):
        stop(request.app.state.audio)
        request.app.state.audio.disconnect();return {'ok':True}

    @app.post('/api/play')
    def play_route(body: PlayRequest,request: Request):
        play(request.app.state.audio,body.sound_id,body.mode,body.tile_id);return {'ok':True}

    @app.post('/api/stop')
    def stop_route(request: Request):
        stop(request.app.state.audio);return {'ok':True}

    @app.post('/api/shutdown')
    def shutdown(request: Request, body: ShutdownRequest | None = None):
        with mutations:
            if body and body.expected_instance_id and body.expected_instance_id != app.state.instance_id:
                return JSONResponse({'detail':'This is a different TuxCue instance.'}, status_code=409)
            callback=request.app.state.shutdown
            if callback is None: raise AudioError('Stop this service from its terminal.')
            result={'ok':True, 'connected':request.app.state.audio.status()['connected'], 'storage_folder':str(state_dir)}
            callback()
            return result

    @app.post('/api/restart')
    def restart(request: Request):
        callback=request.app.state.restart
        if callback is None: raise AudioError('Restart this service from its terminal.')
        callback();return {'ok':True}

    @app.get('/api/sounds/{sound_id}/waveform')
    def waveform(sound_id: str, count: int=Query(default=96,ge=16,le=2048),start: float=Query(default=0,ge=0),end: float|None=None):
        return {'peaks':library.waveform(sound_id,count,start,end)}

    @app.post('/api/sounds/{sound_id}/rename')
    def rename_sound(sound_id: str,body: Name):
        with mutations: return library.rename(sound_id,body.name)

    @app.post('/api/sounds/{sound_id}/trash')
    def trash_sound(sound_id: str,request: Request):
        with mutations, actions:
            play_epoch[0] += 1
            request.app.state.audio.stop(sound_id)
            result=library.trash(sound_id)
            request.app.state.sync_hotkeys()
            return result

    @app.post('/api/sounds/{sound_id}/restore')
    def restore_sound(sound_id: str,request: Request):
        with mutations:
            result=library.trash(sound_id,restore=True)
            request.app.state.sync_hotkeys()
            return result

    @app.post('/api/sounds/{sound_id}/trim')
    def save_clip(sound_id: str,body: SaveSelection):
        with mutations:
            values=body.model_dump();name=values.pop('name')
            item=library.save_selection(sound_id,name,**values)
            boards.add(item['id'])
            return item

    @app.post('/api/sounds/{sound_id}/preview-selection')
    def preview_selection(sound_id: str,body: Selection,request: Request):
        with actions:
            play_epoch[0]+=1;epoch=play_epoch[0]
        with tempfile.TemporaryDirectory(dir=state_dir) as temp:
            path=Path(temp)/'preview.wav'
            library.render_selection(sound_id,path,**body.model_dump())
            with actions:
                if play_epoch[0]!=epoch: return {'started':False}
                request.app.state.audio.stop()
                path.replace(preview_path)
                request.app.state.audio.play(preview_path,sound_id,'preview')
        return {'started':True}

    def upload_to(file,directory,limit=MAX_BYTES):
        path=directory/('upload'+Path(file.filename or 'audio').suffix.lower())
        total=0
        with path.open('wb') as output:
            while chunk:=file.file.read(1024*1024):
                total+=len(chunk)
                if total>limit: raise ValueError('This upload exceeds the file size limit.')
                output.write(chunk)
        return path

    @app.post('/api/import')
    def import_audio(file: UploadFile):
        if not importing.acquire(blocking=False): raise ValueError('Wait for the current import to finish.')
        try:
            with tempfile.TemporaryDirectory(dir=state_dir) as temp,mutations:
                item=library.import_file(upload_to(file,Path(temp)),file.filename or 'audio')
                if not any(t and t['sound_id']==item['id'] for t in boards.active()['tiles']): boards.add(item['id'])
                return item
        finally:
            file.file.close();importing.release()

    @app.post('/api/sets')
    def new_set(body: NewSet):
        with mutations: return boards.create(body.name,body.duplicate_id)

    @app.post('/api/sets/{profile_id}/switch')
    def switch_set(profile_id: str,request: Request):
        with mutations:
            stop(request.app.state.audio);boards.switch(profile_id);return {'ok':True}

    @app.post('/api/sets/{profile_id}/settings')
    def set_settings(profile_id: str,body: SetChange):
        with mutations: boards.update(profile_id,body.model_dump(exclude_none=True));return {'ok':True}

    @app.post('/api/sets/{profile_id}/remove')
    def remove_set(profile_id: str,request: Request):
        with mutations:
            stop(request.app.state.audio);boards.remove(profile_id);return {'ok':True}

    @app.post('/api/sets/{profile_id}/tiles/remove')
    def remove_tiles(profile_id: str,body: TileIndexes):
        with mutations: return boards.remove_tiles(profile_id,body.indexes)

    @app.post('/api/sets/{profile_id}/tiles/{index}')
    def tile_settings(profile_id: str,index: int,body: TileChange):
        with mutations:
            change=body.model_dump(exclude_none=True)
            if 'sound_id' in body.model_fields_set and body.sound_id is None: change['sound_id']=None
            return boards.set_tile(profile_id,index,change)

    @app.post('/api/sets/{profile_id}/add')
    def add_sound(profile_id: str,body: SoundId):
        with mutations: return boards.add(body.sound_id,profile_id)

    @app.post('/api/sets/{profile_id}/move')
    def move_sound(profile_id: str,body: Move):
        with mutations: boards.reorder(profile_id,body.source,body.target);return {'ok':True}

    @app.post('/api/shortcuts/settings')
    def shortcut_settings(body: GlobalSettings):
        with mutations: boards.global_settings(body.model_dump(exclude_none=True));return {'ok':True}

    @app.post('/api/shortcuts/suspend')
    def suspend_shortcuts(body: Suspend,request: Request):
        request.app.state.hotkeys.suspend(body.seconds);return {'ok':True}

    @app.get('/api/sets/{profile_id}/export')
    def export_profile(profile_id: str,background_tasks: BackgroundTasks):
        output=state_dir/(uuid.uuid4().hex+'.soundboard.zip')
        try:
            with mutations: export_set(boards,library,profile_id,output)
        except Exception:
            output.unlink(missing_ok=True);raise
        background_tasks.add_task(output.unlink,missing_ok=True)
        return FileResponse(output,filename='soundboard-set.zip',media_type='application/zip',background=background_tasks)

    @app.post('/api/sets/import')
    def import_profile(file: UploadFile):
        if not importing.acquire(blocking=False): raise ValueError('Wait for the current import to finish.')
        try:
            with tempfile.TemporaryDirectory(dir=state_dir) as temp,mutations:
                return import_set(boards,library,upload_to(file,Path(temp),MAX_UNPACKED+3*1024*1024))
        finally: file.file.close();importing.release()

    frontend=project/'frontend'/'dist'
    if (frontend/'assets').is_dir(): app.mount('/assets',StaticFiles(directory=frontend/'assets'),name='assets')

    @app.get('/tuxcue-logo.png')
    def logo():
        return FileResponse(frontend/'tuxcue-logo.png', media_type='image/png')

    @app.get('/license')
    def license_text():
        return FileResponse(project/'LICENSE', media_type='text/plain')

    @app.get('/notices')
    def third_party_notices():
        return FileResponse(project/'THIRD_PARTY_NOTICES.md', media_type='text/plain')

    # Packaged notices are read-only, separate from the user's collection.
    if (project/'licenses').is_dir():
        app.mount('/licenses', StaticFiles(directory=project/'licenses'), name='licenses')

    @app.get('/')
    def index():
        if not (frontend/'index.html').exists():
            return JSONResponse({'detail':'Build the browser interface first. See README.md.'},status_code=503)
        return FileResponse(frontend/'index.html',headers={'Cache-Control':'no-cache'})

    return app
