import type {KeyboardEvent} from 'react';
import {X} from 'lucide-react';

const names:Record<string,string>={Space:'Space',ArrowLeft:'Left',ArrowRight:'Right',ArrowUp:'Up',ArrowDown:'Down',Minus:'Minus',Equal:'Equal',Comma:'Comma',Period:'Period',Slash:'Slash',Backslash:'Backslash',Semicolon:'Semicolon',Quote:'Apostrophe',BracketLeft:'BracketLeft',BracketRight:'BracketRight',Backquote:'Backquote'};
export function ShortcutInput({label,value,onChange}:{label:string;value:string;onChange:(s:string)=>void}) {
  function capture(e:KeyboardEvent<HTMLInputElement>) {
    if(e.key==='Tab'&&!e.ctrlKey&&!e.altKey&&!e.metaKey) return;
    e.preventDefault();e.stopPropagation();
    if(['Control','Alt','Shift','Meta'].includes(e.key)) return;
    let key=names[e.code]??e.key;
    if(e.code.startsWith('Digit')) key=e.code.slice(5);
    if(key.length===1) key=key.toUpperCase();
    const mods=[e.ctrlKey?'Ctrl':'',e.altKey?'Alt':'',e.shiftKey?'Shift':'',e.metaKey?'Super':''].filter(Boolean);
    if(!mods.length&&!/^F\d+$/.test(key)) return;
    onChange([...mods,key].join('+'));
  }
  return <label className="field">{label}<span className="shortcut-input"><input value={value} placeholder="Click, then press a key combination" readOnly onKeyDown={capture} aria-label={label}/><button type="button" className="icon-button" aria-label={`Clear ${label.toLowerCase()}`} onClick={()=>onChange('')}><X size={16}/></button></span></label>;
}
