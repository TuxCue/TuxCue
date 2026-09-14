import {useState} from 'react';
import {FolderOpen,ChevronUp,Folder,ArrowRight,RotateCcw} from 'lucide-react';
import {api} from './api';
import type {State} from './types';

type Folders={folder:string;parent:string|null;folders:string[]};
export function StoragePanel({state,busy,onBusy,onSaved}:{state:State;busy:boolean;onBusy:(value:boolean)=>void;onSaved:()=>Promise<void>}) {
  const storage=state.storage;
  const [path,setPath]=useState(storage?.folder??''),[browser,setBrowser]=useState<Folders|null>(null);
  const [error,setError]=useState(''),[message,setMessage]=useState(''),[showHidden,setShowHidden]=useState(false);
  const [loading,setLoading]=useState(false);
  async function browse(value:string) {setLoading(true);setError('');try{setBrowser(await api(`/storage/folders?path=${encodeURIComponent(value)}`,undefined,'GET'))}catch(e){setError((e as Error).message)}finally{setLoading(false)}}
  async function move() {onBusy(true);setError('');setMessage('');try{const result=await api('/storage',{folder:path});setPath(result.folder);setBrowser(null);await onSaved();setMessage(result.changed?`Collection moved. Your previous copy remains at ${result.backup_folder}.`:'This folder is already in use.')}catch(e){setError((e as Error).message)}finally{onBusy(false)}}
  if(!storage)return <p className="form-hint">Restart TuxCue to load the storage settings.</p>;
  return <section className="storage-panel"><p className="form-hint">Keep your sounds, edited clips, saved sets and preferences together. The program itself stays where you installed it.</p>
    <div className="storage-current"><span>Current collection folder</span><strong>{storage.folder}</strong></div>
    {!storage.can_change&&<p className="form-error">This launch uses a temporary data-folder override. Start TuxCue normally to change its saved folder.</p>}
    {error&&<p className="form-error" role="alert">{error}</p>}{message&&<p className="storage-success" role="status">{message}</p>}
    <label className="field">Collection folder<input value={path} disabled={busy||!storage.can_change} spellCheck={false} onChange={e=>{setPath(e.target.value);setMessage('')}} placeholder={storage.default_folder}/></label>
    <div className="storage-actions"><button className="secondary" disabled={busy||loading||!storage.can_change} onClick={()=>void browse(storage.folder)}><FolderOpen size={16}/>{loading?'Loading…':'Browse folders'}</button><button className="text-button" disabled={busy||!storage.can_change} onClick={()=>{setPath(storage.default_folder);setBrowser(null)}}><RotateCcw size={15}/>Use default</button></div>
    {browser&&<div className="folder-browser"><div className="folder-location"><button className="icon-button" disabled={busy||loading||!browser.parent} aria-label="Parent folder" onClick={()=>browser.parent&&void browse(browser.parent)}><ChevronUp size={18}/></button><strong>{browser.folder}</strong></div><label className="check-field"><input type="checkbox" checked={showHidden} onChange={e=>setShowHidden(e.target.checked)}/>Show hidden folders</label><div className="folder-list">{browser.folders.filter(name=>showHidden||!name.startsWith('.')).map(name=><button key={name} disabled={busy||loading} onClick={()=>void browse(`${browser.folder.replace(/\/$/,'')}/${name}`)}><Folder size={16}/><span>{name}</span><ArrowRight size={14}/></button>)}{!browser.folders.length&&<p className="form-hint">No subfolders.</p>}</div><button className="secondary" disabled={busy||loading} onClick={()=>{setPath(browser.folder);setBrowser(null)}}>Choose this folder</button></div>}
    <p className="form-hint">Default: <strong>{storage.default_folder}</strong>. Choose a new or empty folder. You can type a new folder name into the path above; TuxCue will create it.</p>
    <p className="form-hint">TuxCue verifies the copied files before switching locations. The old folder remains as a backup. Existing microphone audio continues during the move.</p>
    <div className="modal-footer"><button className="primary" disabled={busy||loading||!storage.can_change||!path.trim()||path.trim()===storage.folder} onClick={()=>void move()}><FolderOpen size={16}/>{busy?'Copying and verifying…':'Move collection here'}</button></div>
  </section>;
}
