import React,{useEffect,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {AudioLines,Play,Square,Headphones,Radio,RefreshCw,LogOut,Search,Smartphone,LayoutGrid,ChevronLeft,ChevronRight} from 'lucide-react';
import './remote.css';
import {PhoneLayoutDialog,usePhoneLayout,useSquareGrid} from './PhoneLayout';

type Tile={id:string;name:string;label:string;color:string;duration:number;position:number;shortcut:string};
type Board={connected:boolean;error:string|null;sets:{id:string;name:string}[];profile:{id:string;name:string;playback_mode:string;tiles:Tile[]};playing:{tile_id:string|null}[]};
class PhoneError extends Error {constructor(message:string,public status=0){super(message)}}
async function request(path:string,body?:unknown){const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),5000);try{const response=await fetch('/remote/api'+path,{method:body===undefined?'GET':'POST',credentials:'same-origin',headers:body===undefined?{}:{'Content-Type':'application/json','X-TuxCue-Remote':'1'},body:body===undefined?undefined:JSON.stringify(body),signal:controller.signal});const data=await response.json();if(!response.ok)throw new PhoneError(typeof data.detail==='string'?data.detail:'That action could not be completed.',response.status);return data}catch(e){if(e instanceof PhoneError)throw e;throw new PhoneError('Connection lost. Check your Wi-Fi and that TuxCue is running on the PC.')}finally{clearTimeout(timeout)}}
const initialPair=new URLSearchParams(window.location.hash.slice(1)).get('pair')??'';
if(window.location.hash)window.history.replaceState(null,'',window.location.pathname);

function Phone(){
  const [board,setBoard]=useState<Board|null>(null),[paired,setPaired]=useState<boolean|null>(null),[online,setOnline]=useState(false);
  const [code,setCode]=useState(initialPair),[name,setName]=useState(/iPhone|iPad/.test(navigator.userAgent)?'iPhone / iPad':/Android/.test(navigator.userAgent)?'Android phone':'Phone');
  const [error,setError]=useState(''),[busy,setBusy]=useState(false),[preview,setPreview]=useState(false),[search,setSearch]=useState('');
  const sending=useRef(false),autoPair=useRef(false);
  const phoneLayout=usePhoneLayout();
  const {layout,orientation}=phoneLayout;
  const [layoutOpen,setLayoutOpen]=useState(false),[page,setPage]=useState(0);
  const layoutButton=useRef<HTMLButtonElement>(null);
  const {viewport,size}=useSquareGrid(layout.rows,layout.columns,!!paired&&!!board);
  const filteredTiles=board?.profile.tiles.filter(t=>(t.label||t.name).toLocaleLowerCase().includes(search.toLocaleLowerCase()))??[];
  const perPage=layout.rows*layout.columns;
  const pages=Math.max(1,Math.ceil(filteredTiles.length/perPage));
  const activePage=Math.min(page,pages-1);
  const pageTiles=filteredTiles.slice(activePage*perPage,(activePage+1)*perPage);
  useEffect(()=>{setPage(0)},[board?.profile.id,search,layout.rows,layout.columns,orientation]);
  useEffect(()=>{viewport.current?.scrollTo(0,0)},[activePage,orientation,layout.rows,layout.columns]);
  useEffect(()=>{if(!layoutOpen)layoutButton.current?.focus()},[layoutOpen]);
  const closeLayout=()=>setLayoutOpen(false);
  const refresh=async()=>{try{const data:Board=await request('/state');setBoard(data);setPaired(true);setOnline(true);setError(previous=>previous.startsWith('Connection lost.')?'':previous)}catch(e){const problem=e as PhoneError;setOnline(false);if(problem.status===401){setPaired(false);setBoard(null)}else setError(problem.message)}};
  const pair=async()=>{if(sending.current)return;sending.current=true;setBusy(true);setError('');try{await request('/pair',{code,name:name.trim()||'Phone'});setCode('');await refresh()}catch(e){setPaired(false);setError((e as Error).message)}finally{sending.current=false;setBusy(false)}};
  useEffect(()=>{let active=true;let timer:ReturnType<typeof setTimeout>;const tick=async()=>{if(!active)return;if(!sending.current)await refresh();if(active)timer=setTimeout(tick,document.hidden?2500:650)};if(initialPair&&!autoPair.current){autoPair.current=true;void pair().then(()=>{if(active)void tick()})}else void tick();const wake=()=>{if(!document.hidden)void refresh()};document.addEventListener('visibilitychange',wake);return()=>{active=false;clearTimeout(timer);document.removeEventListener('visibilitychange',wake)}},[]);
  useEffect(()=>{setSearch('')},[board?.profile.id]);
  async function act(path:string,body:unknown){if(sending.current)return;sending.current=true;setBusy(true);setError('');try{await request(path,body);await refresh()}catch(e){const problem=e as PhoneError;setError(problem.message);if(problem.status===401){setPaired(false);setBoard(null)}if(!problem.status)setOnline(false)}finally{sending.current=false;setBusy(false)}}
  async function stop(){setError('');try{await request('/stop',{});await refresh()}catch(e){setError((e as Error).message)}}
  async function leave(){if(!window.confirm('Disconnect this phone from TuxCue?'))return;await act('/leave',{});setBoard(null);setPaired(false)}
  const showPair=paired===false||!!initialPair&&paired===null;
  return <main className={`phone-app ${paired&&board?'phone-board':''} ${layout.compact?'phone-compact':''}`}><header className="phone-header"><div className="phone-brand"><img src="/tuxcue-logo.png" alt=""/><div><h1>TuxCue</h1><span>PHONE CONTROL</span></div></div>{paired&&<div className="phone-header-actions"><button ref={layoutButton} className="phone-secondary phone-layout-button" onClick={()=>setLayoutOpen(true)} aria-haspopup="dialog"><LayoutGrid size={17}/>Layout</button><button className="phone-stop" onClick={()=>void stop()} disabled={!online}><Square size={16} fill="currentColor"/>Stop all</button></div>}</header>
    {error&&<div className="phone-error" role="alert"><span>{error}</span><button aria-label="Dismiss error" onClick={()=>setError('')}>×</button></div>}
    {showPair?<section className="phone-pair"><div className="phone-pair-icon"><Smartphone size={30}/></div><h2>Pair with your PC</h2><p>In TuxCue on your PC, open <strong>Settings → Remote control</strong>, enable it and choose <strong>Pair a phone</strong>.</p><form onSubmit={e=>{e.preventDefault();void pair()}}><label>Your phone’s name<input value={name} maxLength={40} onChange={e=>setName(e.target.value)} autoComplete="off"/></label><label>Pairing code<input aria-label="Pairing code" value={code} placeholder="1234 5678" inputMode="numeric" autoComplete="one-time-code" maxLength={100} onChange={e=>setCode(e.target.value)}/></label><button className="phone-primary" disabled={busy||!code.trim()}>{busy?'Pairing…':'Connect phone'}</button></form><p className="phone-muted">Your phone and PC must be on the same network. Sounds play on the PC.</p></section>:!paired||!board?<section className="phone-empty"><AudioLines size={35}/><h2>Connecting to your PC…</h2><button className="phone-secondary" onClick={()=>void refresh()}><RefreshCw size={16}/>Retry</button></section>:<>
      <div className={`phone-status ${online?'':'offline'}`} role="status"><span className="status-dot"/>{online?'Connected to your PC':'PC disconnected · reconnecting…'}</div>
      <section className="phone-controls" hidden={layout.compact}><label className="phone-set">Sound set<select aria-label="Sound set" value={board.profile.id} disabled={!online||busy} onChange={e=>void act('/set',{set_id:e.target.value})}>{board.sets.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select></label><div className="phone-routing">{board.connected&&!preview?<Radio size={17}/>:<Headphones size={17}/>}<span>{board.connected&&!preview?'PC + Discord input':'PC playback only'}</span>{board.connected&&<label><input type="checkbox" checked={preview} onChange={e=>setPreview(e.target.checked)}/>Preview only</label>}</div>{!board.connected&&<p className="phone-muted">To send sounds to Discord, connect the virtual microphone in TuxCue on your PC.</p>}<label className="phone-search"><Search size={18}/><input aria-label="Find a sound" placeholder="Find a sound…" value={search} onChange={e=>setSearch(e.target.value)}/></label></section>
      {board.error&&<p className="phone-error" role="alert">{board.error}</p>}
      {layout.compact&&<p className="phone-compact-routing">{preview?'Preview only · ':''}{board.connected&&!preview?'PC + Discord input':'PC playback only'}{search&&<> · Filter: {search} <button onClick={()=>setSearch('')}>Clear</button></>}</p>}
      <div ref={viewport} className="phone-grid-viewport">
        {pageTiles.length>0&&<section className={`phone-grid ${size<100?'phone-grid-dense':''}`} aria-label="Soundboard" style={{'--phone-columns':layout.columns,'--phone-rows':layout.rows,'--phone-tile-size':`${size}px`} as React.CSSProperties}>{pageTiles.map(t=>{const playing=board.playing.some(p=>p.tile_id===t.id);return <button key={t.id} className={`phone-tile ${playing?'playing':''}`} style={{'--tile-color':t.color} as React.CSSProperties} disabled={!online||busy} aria-label={`Play ${t.label||t.name}`} title={t.label||t.name} onClick={()=>void act('/play',{set_id:board.profile.id,tile_id:t.id,mode:preview?'preview':'play'})}><span className="phone-tile-top"><span>{String(t.position).padStart(2,'0')}</span>{playing?<AudioLines size={18}/>:<Play size={15}/>}</span><strong>{t.label||t.name}</strong><span className="phone-tile-bottom"><span>{playing?'Playing':t.shortcut||'Tap to play'}</span><span>{Math.floor(t.duration/60)}:{String(Math.floor(t.duration%60)).padStart(2,'0')}</span></span></button>})}</section>}
        {!filteredTiles.length&&<p className="phone-empty">{search?'No matching sounds.':'Add sound tiles to this set on your PC.'}</p>}
      </div>
      <footer className="phone-board-footer"><nav className="phone-pagination" aria-label="Sound pages"><button className="phone-icon-button" aria-label="Previous sound page" disabled={activePage===0} onClick={()=>setPage(activePage-1)}><ChevronLeft size={22}/></button><span role="status">{activePage+1} / {pages}<small>{filteredTiles.length} {filteredTiles.length===1?'sound':'sounds'}</small></span><button className="phone-icon-button" aria-label="Next sound page" disabled={activePage+1>=pages} onClick={()=>setPage(activePage+1)}><ChevronRight size={22}/></button></nav><button className="phone-icon-button phone-leave" onClick={()=>void leave()} disabled={busy} aria-label="Disconnect phone" title="Disconnect phone"><LogOut size={18}/></button></footer>
      {layoutOpen&&<PhoneLayoutDialog {...phoneLayout} close={closeLayout}/>}

    </>}
    <div className="phone-legal"><a href="/license" target="_blank" rel="noopener noreferrer">GPL-3.0-or-later · No warranty</a></div>
  </main>;
}
createRoot(document.getElementById('root')!).render(<Phone/>);
