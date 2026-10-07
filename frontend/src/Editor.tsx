import {useEffect,useRef,useState} from 'react';
import {Headphones,Save,Scissors,Square,Undo2,ZoomIn} from 'lucide-react';
import {Modal} from './Modal';
import {api,time} from './api';
import type {Sound} from './types';
import {frameCount,removeFrames} from './audioEdits';
import type {AudioSegment} from './audioEdits';

export function Editor({sound,onClose,onSaved}:{sound:Sound;onClose:()=>void;onSaved:(sound:Sound)=>Promise<void>}) {
  const [name,setName]=useState(sound.name+' clip');
  const [segments,setSegments]=useState<AudioSegment[]|null>(null),[history,setHistory]=useState<AudioSegment[][]>([]);
  const [sampleRate,setSampleRate]=useState(48000),[originalFrames,setOriginalFrames]=useState(0),[waveLoading,setWaveLoading]=useState(true);
  const duration=segments?frameCount(segments)/sampleRate:sound.duration;
  const [operation,setOperation]=useState<'keep'|'remove'>('keep');
  const [start,setStart]=useState(0),[end,setEnd]=useState(sound.duration);
  const [gain,setGain]=useState(0),[fadeIn,setFadeIn]=useState(0),[fadeOut,setFadeOut]=useState(0);
  const [zoom,setZoom]=useState(1),[viewStart,setViewStart]=useState(0),[peaks,setPeaks]=useState<number[]>([]);
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[previewing,setPreviewing]=useState(false);
  const wave=useRef<HTMLDivElement>(null);
  const selectionLength=Math.max(0,end-start);
  const resultLength=operation==='keep'?selectionLength:duration;
  const cutStart=Math.round(start*sampleRate),cutEnd=Math.round(end*sampleRate);
  const canCut=!!segments&&cutStart>=0&&cutEnd<=frameCount(segments)&&cutEnd-cutStart>=sampleRate*.01&&frameCount(segments)-(cutEnd-cutStart)>=sampleRate*.01;
  const unavailable=busy||waveLoading||!segments;
  const hasCuts=!!segments&&(segments.length!==1||segments[0].start_frame!==0||segments[0].end_frame!==originalFrames);
  const viewLength=duration/zoom;
  const position=Math.min(viewStart,Math.max(0,duration-viewLength));
  useEffect(()=>{let cancel=false;setWaveLoading(true);api(`/sounds/${sound.id}/editing-waveform`,{segments,count:600,start:position,end:Math.min(duration,position+viewLength)}).then(r=>{if(cancel)return;setPeaks(r.peaks);if(!segments){setSampleRate(r.sample_rate);setOriginalFrames(r.frames);setSegments([{start_frame:0,end_frame:r.frames}]);setEnd(r.duration);}}).catch(e=>{if(!cancel)setError(e.message)}).finally(()=>{if(!cancel)setWaveLoading(false)});return()=>{cancel=true};},[sound.id,segments,position,viewLength,duration]);
  useEffect(()=>{if(!previewing)return;const timer=setTimeout(()=>setPreviewing(false),resultLength*1000+500);return()=>clearTimeout(timer);},[previewing,resultLength]);
  const selection={segments,start:operation==='remove'?0:start,end:operation==='remove'?duration:end,operation:'keep',gain_db:gain,fade_in:fadeIn,fade_out:fadeOut};
  const left=Math.max(0,Math.min(100,(start-position)/viewLength*100));
  const right=Math.max(0,Math.min(100,(end-position)/viewLength*100));
  function move(which:'start'|'end',clientX:number) {
    const rect=wave.current?.getBoundingClientRect();if(!rect)return;
    const at=position+Math.max(0,Math.min(1,(clientX-rect.left)/rect.width))*viewLength;
    if(which==='start')setStart(Math.max(0,Math.min(end-.01,at)));else setEnd(Math.min(duration,Math.max(start+.01,at)));
    setPreviewing(false);
  }
  function showWorking(next:AudioSegment[]) {
    setSegments(next);setStart(0);setEnd(frameCount(next)/sampleRate);setZoom(1);setViewStart(0);setPreviewing(false);setError('');
  }
  async function removePart() {
    if(!segments||!canCut)return;
    setBusy(true);setError('');
    try {
      const next=removeFrames(segments,cutStart,cutEnd);
      if(next.length>128)throw new Error('The clip has reached 128 sections. Save it before making more cuts.');
      await api('/stop');setHistory(previous=>[...previous.slice(-99),segments]);setOperation('remove');showWorking(next);
    } catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  async function restoreCuts(reset=false) {
    if(!segments)return;
    const next=reset?[{start_frame:0,end_frame:originalFrames}]:history.at(-1);
    if(!next)return;
    setBusy(true);setError('');
    try{await api('/stop');setHistory(previous=>reset?[]:previous.slice(0,-1));showWorking(next);}catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  async function preview() {setBusy(true);setError('');try{const r=await api(`/sounds/${sound.id}/preview-selection`,selection);setPreviewing(r.started);}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  async function save() {setBusy(true);setError('');try{const r=await api(`/sounds/${sound.id}/trim`,{...selection,name});await onSaved(r);}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
  async function close() {await api('/stop').catch(()=>{});onClose();}
  return <Modal title="Edit audio" wide busy={busy} onClose={()=>void close()}><div className="editor-source"><strong>{sound.name}</strong><span>{time(duration,true)} · {hasCuts?'working clip · original kept':'original kept'}</span></div>
    {error&&<p className="form-error" role="alert">{error}</p>}
    <label className="field editor-operation">Selection action<select value={operation} disabled={unavailable} aria-describedby="selection-help" onChange={e=>{setOperation(e.target.value as 'keep'|'remove');setPreviewing(false);setError('')}}><option value="keep">Keep selected section</option><option value="remove">Remove selected section</option></select></label>
    <p id="selection-help" className="small-note">{operation==='remove'?'Select a section and press Remove part to cut it from the working clip. You can keep editing before saving.':'Save the highlighted section as a new clip, or press Remove part to cut it and keep editing.'}</p>
    {operation==='remove'&&!canCut&&<p className="small-note" role="status">Choose a section of at least 0.01 seconds, leaving at least 0.01 seconds of audio.</p>}
    <div className="editor-cut-actions"><button className="secondary" disabled={unavailable||!canCut} onClick={()=>void removePart()}><Scissors size={16}/>Remove part</button><button className="secondary" disabled={unavailable||!history.length} onClick={()=>void restoreCuts()}><Undo2 size={16}/>Undo cut</button><button className="secondary" disabled={unavailable||!hasCuts} onClick={()=>void restoreCuts(true)}>Reset cuts</button><span role="status">{waveLoading?'Updating waveform…':hasCuts?'Cuts are unsaved until you save a new clip.':''}</span></div>
    <div className="editor-toolbar"><span>Drag the handles to choose a section</span><label><ZoomIn size={16}/><select disabled={unavailable} aria-label="Waveform zoom" value={zoom} onChange={e=>{setZoom(+e.target.value);setViewStart(Math.max(0,Math.min(start,duration-duration/+e.target.value)))}}>{[1,2,4,8,16,32].map(n=><option key={n} value={n}>{n}×</option>)}</select></label></div>
    <div aria-busy={waveLoading} className={`editor-wave${operation==='remove'?' removing':''}`} ref={wave}><svg viewBox="0 0 600 140" preserveAspectRatio="none" role="img" aria-label="Audio waveform"><line x1="0" y1="70" x2="600" y2="70" stroke="#586764"/>{peaks.map((p,i)=><rect key={i} x={i*600/peaks.length} y={70-Math.max(1,p*64)} width={Math.max(.5,600/peaks.length-.3)} height={Math.max(2,p*128)} fill="#92aa9d"/>)}</svg><div className="selection-region" style={{left:`${left}%`,width:`${Math.max(0,right-left)}%`}}/>{(['start','end'] as const).map(which=>{const value=which==='start'?start:end;const x=(value-position)/viewLength*100;return x>=0&&x<=100&&<button type="button" disabled={unavailable} key={which} className={`trim-handle ${which}`} style={{left:`${x}%`}} aria-label={`Selection ${which} handle`} onPointerDown={e=>{e.currentTarget.setPointerCapture(e.pointerId)}} onPointerMove={e=>{if(e.currentTarget.hasPointerCapture(e.pointerId))move(which,e.clientX)}} onKeyDown={e=>{if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();const n=value+(e.key==='ArrowLeft'?-1:1)*(e.shiftKey ? 0.1 : 0.01);if(which==='start')setStart(Math.max(0,Math.min(end-.01,n)));else setEnd(Math.min(duration,Math.max(start+.01,n)));}}}><span/></button>})}</div>
    <div className="wave-ruler"><span>{time(position,true)}</span><span>{time(position+viewLength,true)}</span></div>
    {zoom>1&&<label className="field waveform-scroll">Waveform position<input aria-label="Waveform position" disabled={unavailable} type="range" min={0} max={Math.max(0,duration-viewLength)} step="0.001" value={position} onChange={e=>setViewStart(+e.target.value)}/></label>}
    <div className="fields three"><label className="field">Start (seconds)<input disabled={unavailable} type="number" min="0" max={end} step="0.001" value={+start.toFixed(6)} onChange={e=>setStart(+e.target.value)}/></label><label className="field">End (seconds)<input disabled={unavailable} type="number" min={start} max={duration} step="0.001" value={+end.toFixed(6)} onChange={e=>setEnd(+e.target.value)}/></label><div className="field">{operation==='remove'?'Section to remove':'Selection length'}<output className="selection-length">{time(selectionLength,true)}</output>{operation==='remove'&&<span className="result-length">Working clip: {time(duration,true)}</span>}</div></div>
    <div className="fields three"><label className="field">Gain (dB)<input disabled={unavailable} type="number" min="-24" max="12" step="1" value={gain} onChange={e=>setGain(+e.target.value)}/></label><label className="field">Fade in (seconds)<input disabled={unavailable} type="number" min="0" max={resultLength} step="0.01" value={fadeIn} onChange={e=>setFadeIn(+e.target.value)}/></label><label className="field">Fade out (seconds)<input disabled={unavailable} type="number" min="0" max={resultLength} step="0.01" value={fadeOut} onChange={e=>setFadeOut(+e.target.value)}/></label></div>
    {operation==='remove'&&<p className="small-note">Gain and fades apply to the joined clip, with fades at its beginning and end.</p>}
    <div className="selection-preview"><button className="secondary" disabled={unavailable||resultLength<.01} onClick={()=>void preview()}><Headphones size={16}/>{busy?'Processing…':operation==='remove'?'Preview working clip':'Preview selection'}</button><button className="secondary" onClick={()=>{setPreviewing(false);void api('/stop').catch(e=>setError(e.message))}}><Square size={15}/>Stop</button><span>{previewing?'Playing in your headphones only':'Previews stay in your headphones'}</span></div>
    <label className="field">New clip name<input value={name} maxLength={120} onChange={e=>setName(e.target.value)}/></label><div className="modal-footer"><button className="secondary" disabled={busy} onClick={()=>void close()}>Cancel</button><button className="primary" disabled={unavailable||resultLength<.01||!name.trim()} onClick={()=>void save()}><Save size={16}/>Save as new clip</button></div>
  </Modal>;
}
