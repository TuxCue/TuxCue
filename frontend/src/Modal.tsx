import {useEffect,useRef,useId} from 'react';
import type {ReactNode} from 'react';
import {X} from 'lucide-react';
import {api} from './api';

let activeModals=0;
let suspension=Promise.resolve();
function updateSuspension() {
  const seconds=activeModals>0?30:0;
  suspension=suspension.then(()=>api('/shortcuts/suspend',{seconds})).then(()=>{}).catch(()=>{});
}

export function Modal({title,onClose,children,wide=false,busy=false}:{title:string;onClose:()=>void;children:ReactNode;wide?:boolean;busy?:boolean}) {
  const ref=useRef<HTMLDialogElement>(null);const titleId=useId();
  useEffect(()=>{
    const previous=document.activeElement as HTMLElement|null;
    const dialog=ref.current;dialog?.showModal();
    activeModals++;updateSuspension();const timer=setInterval(updateSuspension,10000);
    return()=>{clearInterval(timer);dialog?.close();previous?.focus();activeModals--;updateSuspension();};
  },[]);
  return <dialog ref={ref} className={`modal ${wide?'wide':''}`} aria-labelledby={titleId} onCancel={e=>{e.preventDefault();if(!busy) onClose();}}><div className="modal-heading"><h2 id={titleId}>{title}</h2><button className="icon-button" aria-label="Close dialog" disabled={busy} onClick={onClose}><X size={20}/></button></div>{children}</dialog>;
}
