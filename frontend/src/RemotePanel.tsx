import {useEffect,useRef,useState} from 'react';
import {Smartphone,QrCode,Copy,RefreshCw,Trash2} from 'lucide-react';
import {api} from './api';

type RemoteStatus={enabled:boolean;running:boolean;port:number;error:string|null;addresses:{address:string;interface:string}[];pairing:{token:string;code:string;expires_at:number}|null;devices:{id:string;name:string;expires_at:number}[]};
export function RemotePanel({busy,onBusy}:{busy:boolean;onBusy:(busy:boolean)=>void}) {
  const [state,setState]=useState<RemoteStatus|null>(null),[port,setPort]=useState(8766),[address,setAddress]=useState('');
  const pairCard=useRef<HTMLDivElement>(null);
  useEffect(()=>{if(state?.pairing)pairCard.current?.scrollIntoView({block:'nearest'})},[state?.pairing?.expires_at]);
  const [error,setError]=useState(''),[notice,setNotice]=useState('');
  async function refresh(){const next:RemoteStatus=await api('/remote',undefined,'GET');setState(next);setAddress(previous=>next.addresses.some(a=>a.address===previous)?previous:next.addresses[0]?.address??'')}
  useEffect(()=>{if(state)setPort(state.port)},[state?.port]);
  useEffect(()=>{let active=true;let timer:ReturnType<typeof setTimeout>;const tick=async()=>{try{if(active)await refresh()}catch(e){if(active)setError((e as Error).message)}if(active)timer=setTimeout(tick,1500)};void tick();return()=>{active=false;clearTimeout(timer)}},[]);
  async function act(path:string,body?:unknown){onBusy(true);setError('');setNotice('');try{setState(await api(path,body));await refresh()}catch(e){setError((e as Error).message)}finally{onBusy(false)}}
  if(!state)return <p className="form-hint" role="status">{error||'Loading phone controls…'}</p>;
  const ticket=state.pairing&&state.pairing.expires_at>Date.now()/1000?state.pairing:null;
  const url=address?`http://${address}:${state.port}/`:'';
  async function copy(){try{await navigator.clipboard.writeText(url);setNotice('Address copied.')}catch{setNotice('Select and copy the phone address below.')}}
  return <section className="remote-settings"><p className="form-hint">Use your phone as a soundboard. Sounds play on this PC through your current audio routing.</p>
    {(error||state.error)&&<p className="form-error" role="alert">{error||state.error}</p>}
    <div className="remote-switch-row"><div><strong>Remote control</strong><span>{state.running?'Ready for phones on your network':'Phone access is off'}</span></div><button type="button" role="switch" aria-checked={state.running} aria-label="Enable Remote control" className={`toggle ${state.running?'on':''}`} disabled={busy} onClick={()=>void act('/remote/settings',{enabled:!state.running,port})}><span/></button></div>
    {!state.running&&<><label className="field">Phone port<input type="number" min={1024} max={65535} value={port} disabled={busy} onChange={e=>setPort(+e.target.value)}/></label><p className="form-hint">The default port is 8766. Remote control is optional and remembers paired phones for 30 days.</p></>}
    {state.running&&<>
      <p className="form-hint">Connect your phone to the same network as this PC. Use a trusted home network; the controller uses local HTTP.</p>
      {state.addresses.length>1&&<label className="field">PC network address<select value={address} disabled={busy} onChange={e=>setAddress(e.target.value)}>{state.addresses.map(a=><option key={a.address} value={a.address}>{a.address} · {a.interface}</option>)}</select></label>}
      {!url?<p className="form-error">No local IPv4 address was found. Connect the PC to Wi-Fi or Ethernet, then try again.</p>:<>
        <div className="phone-address"><span>Open this address on your phone</span><div><input aria-label="Phone address" readOnly value={url} onFocus={e=>e.target.select()}/><button className="icon-button" title="Copy phone address" aria-label="Copy phone address" onClick={()=>void copy()}><Copy size={18}/></button></div></div>
        <button className="primary" disabled={busy} onClick={()=>void act('/remote/pairing')}><QrCode size={17}/>{ticket?'Create new pairing code':'Pair a phone'}</button>
        {ticket&&<div className="pair-card" ref={pairCard}><img className="pair-qr" src={`/api/remote/qr?address=${encodeURIComponent(address)}&v=${ticket.expires_at}`} alt="Scan with your phone camera to pair with TuxCue"/><div><strong>Scan with your phone camera</strong><p>Or open the address above and enter this code:</p><code className="pair-code">{ticket.code.slice(0,4)} {ticket.code.slice(4)}</code><p>Valid for {Math.max(1,Math.ceil((ticket.expires_at-Date.now()/1000)/60))} minutes and one phone.</p></div></div>}
      </>}
      <div className="paired-heading"><h3>Paired phones</h3><span>{state.devices.length} / 10</span></div>
      {!state.devices.length&&<p className="form-hint">No phones paired yet.</p>}
      {state.devices.map(device=><div className="paired-device" key={device.id}><Smartphone size={19}/><span>{device.name}</span><button className="icon-button danger-text" aria-label={`Forget ${device.name}`} title="Forget phone" disabled={busy} onClick={()=>void act(`/remote/forget/${device.id}`)}><Trash2 size={17}/></button></div>)}
      {state.devices.length>0&&<button className="text-button" disabled={busy} onClick={()=>void act('/remote/forget')}><RefreshCw size={15}/>Forget all phones</button>}
      <p className="form-hint">Turning Remote control off disconnects and forgets paired phones. If your phone cannot open the address, check that both devices share a network, guest Wi-Fi isolation is off, and the PC firewall allows TCP port {state.port} from your local network.</p>
    </>}
    {notice&&<p className="storage-success" role="status">{notice}</p>}
  </section>;
}
