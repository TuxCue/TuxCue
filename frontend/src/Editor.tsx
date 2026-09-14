import {useEffect,useRef,useState} from 'react';
import {Headphones,Save,Square,ZoomIn} from 'lucide-react';
import {Modal} from './Modal';
import {api,time} from './api';
import type {Sound} from './types';

export function Editor({sound,onClose,onSaved}:{sound:Sound;onClose:()=>void;onSaved:(sound:Sound)=>Promise<void>}) {
  const [name,setName]=useState(sound.name+' clip');
  const [start,setStart]=useState(0),[end,setEnd]=useState(sound.duration);
  const [gain,setGain]=useState(0),[fadeIn,setFadeIn]=useState(0),[fadeOut,setFadeOut]=useState(0);
  const [zoom,setZoom]=useState(1),[viewStart,setViewStart]=useState(0),[peaks,setPeaks]=useState<number[]>([]);
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[previewing,setPreviewing]=useState(false);
  const wave=useRef<HTMLDivElement>(null);
  const viewLength=sound.duration/zoom;
  const position=Math.min(viewStart,Math.max(0,sound.duration-viewLength));
  useEffect(()=>{let cancel=false;api(`/sounds/${sound.id}/waveform?count=600&start=${position}&end=${Math.min(sound.duration,position+viewLength)}`,undefined,'GET').then(r=>{if(!cancel)setPeaks(r.peaks)}).catch(e=>{if(!cancel)setError(e.message)});return()=>{cancel=true};},[sound.id,position,viewLength]);
  useEffect(()=>{if(!previewing)return;const timer=setTimeout(()=>setPreviewing(false),Math.max(0,end-start)*1000+500);return()=>clearTimeout(timer);},[previewing,start,end]);
  const selection={start,end,gain_db:gain,fade_in:fadeIn,fade_out:fadeOut};
  const left=Math.max(0,Math.min(100,(start-position)/viewLength*100));
  const right=Math.max(0,Math.min(100,(end-position)/viewLength*100));
  function move(which:'start'|'end',clientX:number) {
    const rect=wave.current?.getBoundingClientRect();if(!rect)return;
    const at=position+Math.max(0,Math.min(1,(clientX-rect.left)/rect.width))*viewLength;
    if(which==='start')setStart(Math.max(0,Math.min(end-.01,at)));else setEnd(Math.min(sound.duration,Math.max(start+.01,at)));
    setPreviewing(false);
  }
  async function preview() {setBusy(true);setError('');try{const r=await api(`/sounds/${sound.id}/preview-selection`,selection);setPreviewing(r.started);}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  async function save() {setBusy(true);setError('');try{const r=await api(`/sounds/${sound.id}/trim`,{...selection,name});await onSaved(r);}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  async function close() {await api('/stop').catch(()=>{});onClose();}
  return <Modal title="Edit audio" wide busy={busy} onClose={()=>void close()}><div className="editor-source"><strong>{sound.name}</strong><span>{time(sound.duration,true)} · original kept</span></div>
    {error&&<p className="form-error" role="alert">{error}</p>}
    <div className="editor-toolbar"><span>Drag the handles to choose a section</span><label><ZoomIn size={16}/><select aria-label="Waveform zoom" value={zoom} onChange={e=>{setZoom(+e.target.value);setViewStart(Math.max(0,Math.min(start,sound.duration-sound.duration/+e.target.value)))}}>{[1,2,4,8,16,32].map(n=><option key={n} value={n}>{n}×</option>)}</select></label></div>
    <div className="editor-wave" ref={wave}><svg viewBox="0 0 600 140" preserveAspectRatio="none" role="img" aria-label="Audio waveform"><line x1="0" y1="70" x2="600" y2="70" stroke="#586764"/>{peaks.map((p,i)=><rect key={i} x={i*600/peaks.length} y={70-Math.max(1,p*64)} width={Math.max(.5,600/peaks.length-.3)} height={Math.max(2,p*128)} fill="#92aa9d"/>)}</svg><div className="selection-region" style={{left:`${left}%`,width:`${Math.max(0,right-left)}%`}}/>{(['start','end'] as const).map(which=>{const value=which==='start'?start:end;const x=(value-position)/viewLength*100;return x>=0&&x<=100&&<button type="button" key={which} className={`trim-handle ${which}`} style={{left:`${x}%`}} aria-label={`Selection ${which} handle`} onPointerDown={e=>{e.currentTarget.setPointerCapture(e.pointerId)}} onPointerMove={e=>{if(e.currentTarget.hasPointerCapture(e.pointerId))move(which,e.clientX)}} onKeyDown={e=>{if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();const n=value+(e.key==='ArrowLeft'?-1:1)*(e.shiftKey ? 0.1 : 0.01);if(which==='start')setStart(Math.max(0,Math.min(end-.01,n)));else setEnd(Math.min(sound.duration,Math.max(start+.01,n)));}}}><span/></button>})}</div>
    <div className="wave-ruler"><span>{time(position,true)}</span><span>{time(position+viewLength,true)}</span></div>
    {zoom>1&&<label className="field waveform-scroll">Waveform position<input aria-label="Waveform position" type="range" min={0} max={Math.max(0,sound.duration-viewLength)} step="0.001" value={position} onChange={e=>setViewStart(+e.target.value)}/></label>}
    <div className="fields three"><label className="field">Start (seconds)<input type="number" min="0" max={end} step="0.001" value={+start.toFixed(6)} onChange={e=>setStart(+e.target.value)}/></label><label className="field">End (seconds)<input type="number" min={start} max={sound.duration} step="0.001" value={+end.toFixed(6)} onChange={e=>setEnd(+e.target.value)}/></label><div className="field">Selection length<output className="selection-length">{time(Math.max(0,end-start),true)}</output></div></div>
    <div className="fields three"><label className="field">Gain (dB)<input type="number" min="-24" max="12" step="1" value={gain} onChange={e=>setGain(+e.target.value)}/></label><label className="field">Fade in (seconds)<input type="number" min="0" max={Math.max(0,end-start)} step="0.01" value={fadeIn} onChange={e=>setFadeIn(+e.target.value)}/></label><label className="field">Fade out (seconds)<input type="number" min="0" max={Math.max(0,end-start)} step="0.01" value={fadeOut} onChange={e=>setFadeOut(+e.target.value)}/></label></div>
    <div className="selection-preview"><button className="secondary" disabled={busy} onClick={()=>void preview()}><Headphones size={16}/>{busy?'Processing…':'Preview selection'}</button><button className="secondary" onClick={()=>{setPreviewing(false);void api('/stop').catch(e=>setError(e.message))}}><Square size={15}/>Stop</button><span>{previewing?'Playing in your headphones only':'Selection previews stay in your headphones'}</span></div>
    <label className="field">New clip name<input value={name} maxLength={120} onChange={e=>setName(e.target.value)}/></label><div className="modal-footer"><button className="secondary" disabled={busy} onClick={()=>void close()}>Cancel</button><button className="primary" disabled={busy||!name.trim()} onClick={()=>void save()}><Save size={16}/>Save as new clip</button></div>
  </Modal>;
}
