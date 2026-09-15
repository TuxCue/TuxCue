import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {AudioLines, Headphones, Mic, Play, Square, Upload, FolderOpen, Search, Cable, Radio, X, RefreshCw, AlertCircle, ChevronDown, Volume2, Plus, Settings2, Copy, Download, Scissors, Pencil, Trash2, RotateCcw, ChevronLeft, ChevronRight, Keyboard, LayoutGrid, Power, Smartphone, Library as LibraryIcon} from 'lucide-react';
import {registerTools} from './tools';
import {api,time,downloadSet} from './api';
import {Editor} from './Editor';
import {NameDialog,TileDialog,SetSettings} from './SetDialogs';
import {Modal} from './Modal';
import type {Sound,Tile,Device,Settings,State} from './types';
import './style.css';

type Dialog = {kind:'editor';sound:Sound}|{kind:'tile';index:number}|{kind:'rename';sound:Sound}|{kind:'new'|'duplicate'|'settings'|'remove-set'|'quit'|'remote'};

function Volume({label, value, icon, disabled, onChange}: {label: string; value: number; icon: React.ReactNode; disabled: boolean; onChange: (value: number)=>void}) {
  const [local, setLocal] = useState(value);
  const editing = useRef(false);
  useEffect(() => {if (!editing.current) setLocal(value)}, [value]);
  return <div className="volume"><div className="volume-label">{icon}<label htmlFor={label}>{label}</label><output>{Math.round(local * 100)}%</output></div><input id={label} aria-label={label} disabled={disabled} type="range" min="0" max="100" value={Math.round(local*100)} onPointerDown={()=>editing.current=true} onChange={e=>{setLocal(+e.target.value/100)}} onPointerUp={e=>{editing.current=false; onChange(+e.currentTarget.value/100)}} onPointerCancel={()=>editing.current=false} onKeyUp={e=>onChange(+e.currentTarget.value/100)} onBlur={e=>{editing.current=false; onChange(+e.currentTarget.value/100)}}/></div>;
}
function DeviceSelect({label, value, items, disabled, onChange}: {label: string; value: string; items: Device[]; disabled: boolean; onChange: (value: string)=>void}) {
  const missing = value && !items.some(d=>d.name === value);
  return <label className="device-label">{label}<span className="select-wrap"><select aria-label={label} value={value} disabled={disabled} onChange={e=>onChange(e.target.value)}>{!value && <option value="">Choose a device</option>}{missing && <option value={value}>Disconnected — choose a device</option>}{items.map(d=><option key={d.name} value={d.name}>{d.description}{d.muted ? ' (muted)' : ''}</option>)}</select><ChevronDown size={15}/></span></label>;
}

function App() {
  const [state,setState]=useState<State|null>(null);
  const [closed,setClosed]=useState(false);
  const [error,setError]=useState(''),[offline,setOffline]=useState(false),[busy,setBusy]=useState(false),[notice,setNotice]=useState('');
  const [search,setSearch]=useState(''),[selected,setSelected]=useState<string|null>(null),[peaks,setPeaks]=useState<number[]>([]);
  const [view,setView]=useState<'board'|'library'|'trash'>('board'),[page,setPage]=useState(0),[dialog,setDialog]=useState<Dialog|null>(null);
  const upload=useRef<HTMLInputElement>(null),bundleUpload=useRef<HTMLInputElement>(null),activeRequest=useRef(false);
  const refresh=async()=>{
    try {const value:State=await api('/state',undefined,'GET');setState(value);setOffline(false);return value;}
    catch {setOffline(true);}
  };
  useEffect(()=>{let cancelled=false;let timer:ReturnType<typeof setTimeout>;const tick=async()=>{if(cancelled)return;await refresh();if(!cancelled)timer=setTimeout(tick,450)};void tick();return()=>{cancelled=true;clearTimeout(timer)}},[]);
  useEffect(()=>registerTools(api,async()=>{await refresh()}),[]);
  const profile=state?.sets?.profiles[state.sets.active_id];
  const current=state?.sounds.find(s=>s.id===(selected??state.playing_id))??state?.sounds[0];
  useEffect(()=>{setPeaks([]);if(!current)return;let cancelled=false;api(`/sounds/${current.id}/waveform`,undefined,'GET').then(r=>{if(!cancelled)setPeaks(r.peaks)}).catch(()=>{});return()=>{cancelled=true}},[current?.id]);
  useEffect(()=>{setPage(0);setSearch('')},[profile?.id]);
  const act=async(path:string,body?:unknown)=>{
    if(activeRequest.current)return;
    activeRequest.current=true;setBusy(true);setError('');
    try {const result=await api(path,body);await refresh();return result;}
    catch(e){setError((e as Error).message);}
    finally {activeRequest.current=false;setBusy(false);}
  };
  const stop=async()=>{try{await api('/stop');await refresh()}catch(e){setError((e as Error).message)}};
  useEffect(()=>{const listener=(e:KeyboardEvent)=>{if(e.key==='Escape'&&!document.querySelector('dialog[open]')&&!['INPUT','SELECT','TEXTAREA'].includes((e.target as HTMLElement).tagName))void stop()};window.addEventListener('keydown',listener);return()=>window.removeEventListener('keydown',listener)},[]);
  const configure=(change:Partial<Settings>)=>void act('/settings',change);
  const play=(sound:Sound,preview=false,tile?:Tile)=>{setSelected(sound.id);void act('/play',{sound_id:sound.id,tile_id:tile?.id,mode:preview||!state?.connected?'preview':'broadcast'})};
  const importFiles=async(files:FileList|null)=>{
    if(!files)return;let count=0;
    for(const file of Array.from(files)){const form=new FormData();form.append('file',file);const result=await act('/import',form);if(result){count++;setSelected(result.id)}else break;}
    if(count)setNotice(`${count} sound${count===1?'':'s'} imported and added to this set.`);
    if(upload.current)upload.current.value='';
  };
  const afterSave=async()=>{await refresh()};
  if(closed)return <main className="loading"><img className="closed-logo" src="/tuxcue-logo.png" alt="TuxCue"/><h1>TuxCue is closed</h1><p>Launch TuxCue again to open your soundboard.</p></main>;
  if(!state||!profile)return <main className="loading"><AudioLines size={42}/><h1>TuxCue</h1><p>{offline?'TuxCue is unavailable. Launch the TuxCue AppImage to open your soundboard.':state&&!profile?'Restart the local service to load this update, then refresh this page.':'Connecting to your audio service…'}</p><button className="secondary" onClick={refresh}><RefreshCw size={16}/>Retry</button></main>;
  const sounds=new Map(state.sounds.map(s=>[s.id,s]));
  const visible=(view==='trash'?state.trash:state.sounds)
    .filter(s=>s.name.toLowerCase().includes(search.toLowerCase()))
    .sort((a,b)=>a.name.localeCompare(b.name,undefined,{sensitivity:'base',numeric:true}));
  const playing=state.playing_id===current?.id;
  const progress=playing?Math.min(1,state.position/(state.duration||current?.duration||1)):0;
  const disabled=busy||offline;
  const problem=error||(offline?'Connection lost. Reconnect to the local service to use Stop all.':'')||state.device_error||state.error;
  const capacity=profile.rows*profile.columns;
  const lastTile=profile.tiles.reduce((last,t,i)=>t?i+1:last,0);
  const pages=Math.max(1,Math.ceil(lastTile/capacity)),activePage=Math.min(page,pages-1);
  const conflicts=state.hotkeys.conflicts;
  const shortcutStatus=!state.sets.hotkeys_enabled?'Shortcuts disabled':state.hotkeys.error??(!state.hotkeys.available?'Global shortcuts need an X11 session':state.hotkeys.suspended?'Shortcuts paused while editing':conflicts.length?'Some shortcuts are unavailable':'Global shortcuts ready');
  const add=async(sound:Sound)=>{const r=await act(`/sets/${profile.id}/add`,{sound_id:sound.id});if(r){setPage(Math.floor(r.index/capacity));setNotice(`Added “${sound.name}” to ${profile.name}.`)}};
  const trash=async(sound:Sound)=>{if(await act(`/sounds/${sound.id}/trash`))setNotice(`“${sound.name}” moved to Trash. Restore it from the Trash tab.`)};
  return <div className="app-shell">
    <header className="topbar"><div className="brand"><img className="brand-logo" src="/tuxcue-logo.png" alt=""/><h1>TuxCue</h1><span className="build-tag">LOCAL · {state.version}</span></div><div className="header-actions"><button className="icon-button" title="Remote control" aria-label="Remote control" disabled={disabled} onClick={()=>setDialog({kind:'remote'})}><Smartphone size={20}/><span className="header-remote-label">Remote control</span></button><button className="stop-button" onClick={stop} disabled={offline}><Square size={15} fill="currentColor"/>Stop all <kbd>{state.sets.hotkeys_enabled&&state.sets.stop_shortcut?state.sets.stop_shortcut:'Esc'}</kbd></button><button className="icon-button" title="Quit TuxCue" aria-label="Quit TuxCue" disabled={disabled} onClick={()=>setDialog({kind:'quit'})}><Power size={19}/></button></div></header>
    {problem&&<div className="banner error" role="alert"><AlertCircle size={18}/><span>{problem}</span>{error&&<button aria-label="Dismiss error" onClick={()=>setError('')}><X size={16}/></button>}</div>}
    {notice&&<div className="banner notice" role="status"><span>{notice}</span><button aria-label="Dismiss message" onClick={()=>setNotice('')}><X size={16}/></button></div>}
    <main className="workspace"><section className="board">
      <div className="section-heading"><div><div className="eyebrow">YOUR SOUNDBOARD</div><label className="set-picker"><span className="sr-only">Active sound set</span><select value={profile.id} disabled={disabled} onChange={e=>void act(`/sets/${e.target.value}/switch`)}>{Object.values(state.sets.profiles).map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label></div><button className="primary" disabled={disabled||state.importing} onClick={()=>upload.current?.click()}><Upload size={16}/>{state.importing?'Importing…':'Import sounds'}</button></div>
      <input ref={upload} type="file" accept=".mp3,.wav,.flac,.ogg,.opus,.m4a,.aac,.aiff,.wma" multiple hidden onChange={e=>void importFiles(e.target.files)}/>
      <input ref={bundleUpload} type="file" accept=".zip" hidden onChange={async e=>{const file=e.target.files?.[0];if(file){const form=new FormData();form.append('file',file);if(await act('/sets/import',form)){setView('board');setNotice('Set imported, including its sounds and tile settings.')}}if(bundleUpload.current)bundleUpload.current.value=''}}/>
      <div className="set-toolbar"><button className="text-button" disabled={disabled} onClick={()=>setDialog({kind:'new'})}><Plus size={15}/>New set</button><button className="text-button" disabled={disabled} onClick={()=>setDialog({kind:'duplicate'})}><Copy size={15}/>Duplicate</button><button className="text-button" disabled={disabled} onClick={()=>void downloadSet(profile.id,profile.name).catch(e=>setError(e.message))}><Download size={15}/>Export set</button><button className="text-button" disabled={disabled} onClick={()=>bundleUpload.current?.click()}><Upload size={15}/>Import set</button><button className="text-button" disabled={disabled} onClick={()=>setDialog({kind:'settings'})}><Settings2 size={15}/>Settings</button></div>
      <div className="player-panel"><div className="player-title"><span className={`mode-pill ${state.connected?'live':''}`}>{state.connected?<Radio size={14}/>:<Headphones size={14}/>} {state.connected?'Headphones + Discord input':'Local preview'}</span><span className="duration">{playing?time(state.position):'0:00'} <span>/ {time(playing?state.duration:current?.duration??0)}</span></span></div>
        <h3>{current?.name??'Choose your first sound'}</h3><div className="waveform" aria-label={current?`Waveform of ${current.name}`:'No sound selected'}>{peaks.length?peaks.map((peak,i)=><span key={i} className={i/peaks.length<progress?'played':''} style={{height:`${Math.max(4,peak*100)}%`}}/>):<div className="wave-empty">Import a clip to get started</div>}</div>
        <div className="player-actions"><button className="primary" disabled={!current||disabled} onClick={()=>current&&play(current)}><Play size={16} fill="currentColor"/>{state.connected?'Play to both':'Preview sound'}</button>{state.connected&&<button className="secondary" disabled={!current||disabled} onClick={()=>current&&play(current,true)}><Headphones size={16}/>Preview only</button>}<button className="secondary" disabled={!current||disabled} onClick={()=>current&&setDialog({kind:'editor',sound:current})}><Scissors size={16}/>Edit audio</button><span className="play-status">{state.playing.length>1?`${state.playing.length} sounds playing`:state.playing_id?state.mode==='preview'?'Previewing in headphones':'Sending to virtual microphone':'Ready when you are'}</span></div>
      </div>
      <nav className="view-tabs" aria-label="Sound views">{([{id:'board',label:'Board',icon:<LayoutGrid size={16}/>},{id:'library',label:`Library · ${state.sounds.length}`,icon:<LibraryIcon size={16}/>},{id:'trash',label:`Trash · ${state.trash.length}`,icon:<Trash2 size={16}/>} ] as const).map(v=><button key={v.id} className={view===v.id?'active':''} aria-current={view===v.id?'page':undefined} onClick={()=>{setView(v.id);setSearch('')}}>{v.icon}{v.label}</button>)}</nav>
      {view==='board'?<>
        <div className="grid-summary"><span>{profile.rows} rows × {profile.columns} columns · {profile.playback_mode==='overlap'?'Sounds can overlap':'One sound at a time'}</span><span>Drag tiles to swap · pencil to configure</span></div>
        <div className="grid-scroll"><div className="board-grid" style={{gridTemplateColumns:`repeat(${profile.columns}, minmax(140px, 1fr))`}}>{Array.from({length:Math.min(capacity,1000-activePage*capacity)},(_,offset)=>{
          const index=activePage*capacity+offset,tile=profile.tiles[index],sound=tile?sounds.get(tile.sound_id):undefined;
          const isPlaying=!!tile&&state.playing.some(p=>p.tile_id===tile.id);
          return <div key={index} className={`board-cell ${tile?'filled':''} ${isPlaying?'playing':''} ${tile&&!sound?'unavailable':''}`} style={{'--tile-color':tile?.color??'#65736c'} as React.CSSProperties} draggable={!!tile&&!disabled} onDragStart={e=>{e.dataTransfer.setData('application/x-soundboard-tile',JSON.stringify({set:profile.id,index}));e.dataTransfer.effectAllowed='move'}} onDragOver={e=>{if(e.dataTransfer.types.includes('application/x-soundboard-tile')){e.preventDefault();e.dataTransfer.dropEffect='move'}}} onDrop={e=>{e.preventDefault();try{const data=JSON.parse(e.dataTransfer.getData('application/x-soundboard-tile'));if(data.set===profile.id&&data.index!==index)void act(`/sets/${profile.id}/move`,{source:data.index,target:index})}catch{}}}>
            {tile?<><button className="tile-trigger" disabled={disabled||!sound} onClick={()=>sound&&play(sound,false,tile)} aria-label={`${state.connected?'Play':'Preview'} ${tile.label||sound?.name||'Removed sound'}`}><span className="tile-top"><span className="tile-index">{String(index+1).padStart(2,'0')}</span>{isPlaying?<AudioLines size={17}/>:<Play size={15}/>}</span><span className="tile-name">{tile.label||sound?.name||'Sound in Trash'}</span><span className="tile-shortcut">{tile.shortcut||'No shortcut'}</span><span className="tile-duration">{sound?time(sound.duration):'Restore from Trash'}</span></button><button className="tile-edit icon-button" aria-label={`Configure tile ${index+1}`} disabled={disabled} onClick={()=>setDialog({kind:'tile',index})}><Pencil size={14}/></button></>:<button className="empty-tile" disabled={disabled} onClick={()=>setDialog({kind:'tile',index})}><Plus size={23}/><span>Add sound</span><small>{index+1}</small></button>}
          </div>;
        })}</div></div>
        <div className="pagination"><button className="secondary" aria-label="Previous board page" disabled={activePage===0} onClick={()=>setPage(activePage-1)}><ChevronLeft size={16}/></button><span>Page {activePage+1} of {pages}</span><button className="secondary" aria-label="Next board page" disabled={activePage+1===pages} onClick={()=>setPage(activePage+1)}><ChevronRight size={16}/></button><button className="text-button" disabled={disabled||!state.sounds.length||lastTile>=1000} onClick={()=>setDialog({kind:'tile',index:Math.min(999,lastTile)})}><Plus size={15}/>Add tile</button></div>
        <div className={`shortcut-status ${conflicts.length||state.hotkeys.error?'warning':''}`}><Keyboard size={16}/><span>{shortcutStatus}{conflicts.length>0&&<small>{conflicts.join(' · ')}</small>}</span></div>
      </>:<>
        <div className="library-tools"><label className="search"><Search size={17}/><input aria-label="Search sounds" placeholder="Find a sound…" value={search} onChange={e=>setSearch(e.target.value)}/>{search&&<button aria-label="Clear search" onClick={()=>setSearch('')}><X size={15}/></button>}</label><span className="library-hint">{view==='trash'?'Restore sounds with their tile assignments':'Shared by all your sound sets'}</span></div>
        <div className="sound-list">{visible.map(sound=><article className="library-row" key={sound.id}><div className="library-name"><strong>{sound.name}</strong><span>{time(sound.duration,true)} · {sound.filename}</span></div><div className="row-actions">{view==='trash'?<button className="secondary" disabled={disabled} onClick={()=>void act(`/sounds/${sound.id}/restore`)}><RotateCcw size={15}/>Restore</button>:<><button className="icon-button" title="Preview only" aria-label={`Preview ${sound.name}`} disabled={disabled} onClick={()=>play(sound,true)}><Headphones size={17}/></button><button className="icon-button" title="Add to active set" aria-label={`Add ${sound.name} to set`} disabled={disabled} onClick={()=>void add(sound)}><Plus size={17}/></button><button className="icon-button" title="Edit audio" aria-label={`Edit ${sound.name}`} disabled={disabled} onClick={()=>setDialog({kind:'editor',sound})}><Scissors size={17}/></button><button className="icon-button" title="Rename sound" aria-label={`Rename ${sound.name}`} disabled={disabled} onClick={()=>setDialog({kind:'rename',sound})}><Pencil size={17}/></button><button className="icon-button danger-text" title="Move to Trash" aria-label={`Move ${sound.name} to Trash`} disabled={disabled} onClick={()=>void trash(sound)}><Trash2 size={17}/></button></>}</div></article>)}</div>
        {!visible.length&&<div className="empty"><FolderOpen size={35}/><h3>{search?'No matching sounds':view==='trash'?'Trash is empty':'Bring your sound collection'}</h3><p>{search?'Try another name.':view==='trash'?'Removed sounds can be restored here.':'Import audio files to get started.'}</p></div>}
        {view==='library'&&!!state.sample_count&&<button className="sample-import" disabled={disabled||state.importing} onClick={async()=>{const r=await act('/samples/import');if(r){setNotice(`${r.imported} sample sounds available in this set.`);if(r.errors.length)setError(r.errors.map((e:{name:string;error:string})=>`${e.name}: ${e.error}`).join(' '))}}}><FolderOpen size={16}/>{state.importing?'Importing sample sounds…':`Load sample folder (${state.sample_count} sounds)`}</button>}
      </>}
    </section>
    <aside className="routing"><div className="routing-title"><Cable size={20}/><h2>Audio routing</h2></div><div className={`connection ${state.connected ? 'connected' : ''}`}><span className="status-dot"/><strong>{state.connected ? 'Virtual microphone connected' : 'Preview mode'}</strong></div>
      <div className="route-block"><div className="route-label"><Mic size={17}/><h3>Your voice</h3><button className={`toggle ${state.settings.mic_enabled ? 'on':''}`} role="switch" aria-checked={state.settings.mic_enabled} aria-label="Include microphone" disabled={disabled} onClick={()=>configure({mic_enabled:!state.settings.mic_enabled})}><span/></button></div><DeviceSelect label="Microphone" value={state.settings.microphone} items={state.devices.inputs} disabled={disabled} onChange={microphone=>configure({microphone})}/><Volume disabled={disabled} label="Voice level" value={state.settings.mic_volume} icon={<Mic size={15}/>} onChange={mic_volume=>configure({mic_volume})}/></div>
      <div className="route-block"><div className="route-label"><Headphones size={17}/><h3>You hear</h3></div><DeviceSelect label="Headphones / speakers" value={state.settings.output} items={state.devices.outputs} disabled={disabled} onChange={output=>configure({output})}/><Volume disabled={disabled} label="Local clip volume" value={state.settings.monitor_volume} icon={<Volume2 size={15}/>} onChange={monitor_volume=>configure({monitor_volume})}/><p className="small-note">Only sound clips are monitored here.</p></div>
      <div className="route-block"><div className="route-label"><Radio size={17}/><h3>Friends hear</h3></div><div className="virtual-device"><AudioLines size={20}/><div><strong>TuxCue Microphone</strong><span>{state.settings.mic_enabled ? 'Your voice + sound clips' : 'Sound clips only'}</span></div></div><Volume disabled={disabled} label="Sent clip volume" value={state.settings.send_volume} icon={<Volume2 size={15}/>} onChange={send_volume=>configure({send_volume})}/></div>
      <button className={state.connected ? 'secondary connect-button' : 'primary connect-button'} disabled={disabled || !!state.device_error} onClick={()=>void act(state.connected ? '/disconnect' : '/connect')}><Cable size={17}/>{busy ? 'Applying…' : state.connected ? 'Disconnect microphone' : 'Connect virtual microphone'}</button>
      <div className="discord-help"><strong>In Discord</strong><p>Choose <b>TuxCue Microphone</b> under Settings → Voice &amp; Video → Input Device.</p><p>If clips are cut off, try turning off noise suppression. With push-to-talk, hold your talk key while playing.</p></div>
      <div className="engine-info"><span>Audio service</span><span>{state.devices.server}</span><button onClick={refresh} aria-label="Refresh audio status"><RefreshCw size={14}/></button></div>
    </aside></main>
    <footer><span>Saved on this PC · pair your phone in Remote control</span><span><a href="/license" target="_blank" rel="noopener noreferrer">GPL-3.0-or-later · No warranty</a> · <a href="/notices" target="_blank" rel="noopener noreferrer">Third-party notices</a></span></footer>
    {dialog?.kind==='quit'&&<Modal title="Quit TuxCue?" onClose={()=>setDialog(null)} busy={busy}><p className="form-hint">This stops clips, releases global shortcuts, and disconnects the virtual microphone. Your sounds and sets are saved.</p><div className="modal-footer"><button className="secondary" disabled={busy} onClick={()=>setDialog(null)}>Cancel</button><button className="primary" disabled={busy} onClick={async()=>{setBusy(true);try{await api('/shutdown');setDialog(null);setClosed(true)}catch(e){setError((e as Error).message);setDialog(null)}finally{setBusy(false)}}}><Power size={16}/>Quit TuxCue</button></div></Modal>}
    {dialog?.kind==='editor' &&<Editor sound={dialog.sound} onClose={()=>setDialog(null)} onSaved={async sound=>{const latest=await refresh();setSelected(sound.id);setDialog(null);setView('board');const p=latest?.sets.profiles[latest.sets.active_id];if(p){const i=p.tiles.findIndex(t=>t?.sound_id===sound.id);setPage(Math.floor(Math.max(0,i)/(p.rows*p.columns)))}setNotice(`Saved “${sound.name}” as a new clip and added it to this set.`)}}/>}
    {dialog?.kind==='tile'&&<TileDialog profile={profile} index={dialog.index} sounds={state.sounds} onClose={()=>setDialog(null)} onSaved={async()=>{await refresh();setPage(Math.floor(dialog.index/capacity))}} onEdit={sound=>setDialog({kind:'editor',sound})}/>}
    {(dialog?.kind==='settings'||dialog?.kind==='remote')&&<SetSettings initialTab={dialog.kind==='remote'?'remote':'set'} profile={profile} state={state} onClose={()=>setDialog(null)} onSaved={afterSave} onRemove={()=>setDialog({kind:'remove-set'})}/>}
    {(dialog?.kind==='new'||dialog?.kind==='duplicate')&&<NameDialog title={dialog.kind==='new'?'Create sound set':'Duplicate sound set'} initial={dialog.kind==='duplicate'?profile.name+' copy':''} onClose={()=>setDialog(null)} onSave={async name=>{await api('/sets',{name,duplicate_id:dialog.kind==='duplicate'?profile.id:undefined});await refresh();setView('board')}}/>}
    {dialog?.kind==='rename'&&<NameDialog title="Rename sound" initial={dialog.sound.name} onClose={()=>setDialog(null)} onSave={async name=>{await api(`/sounds/${dialog.sound.id}/rename`,{name});await refresh()}}/>}
    {dialog?.kind==='remove-set'&&<Modal title="Remove sound set?" onClose={()=>setDialog(null)} busy={busy}><p className="form-hint">Remove “{profile.name}” and its tile layout? Its sounds will stay in your library.</p><div className="modal-footer"><button className="secondary" disabled={busy} onClick={()=>setDialog(null)}>Cancel</button><button className="secondary danger-text" disabled={disabled} onClick={async()=>{if(await act(`/sets/${profile.id}/remove`))setDialog(null)}}><Trash2 size={16}/>Remove set</button></div>{error&&<p className="form-error" role="alert">{error}</p>}</Modal>}
  </div>;
}
createRoot(document.getElementById('root')!).render(<App/>);
