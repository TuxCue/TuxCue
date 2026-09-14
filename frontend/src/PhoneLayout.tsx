import React, {useEffect, useRef, useState} from 'react';
import {X} from 'lucide-react';

export type PhoneGridLayout = {rows: number; columns: number; compact: boolean};
type Orientation = 'portrait' | 'landscape';
type Layouts = Record<Orientation, PhoneGridLayout>;
const storageKey = 'tuxcue.phone-layout.v1';
const defaults: Layouts = {
  portrait: {rows: 3, columns: 2, compact: false},
  landscape: {rows: 2, columns: 6, compact: true},
};
function readLayouts(): Layouts {
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || '{}');
    const valid = (orientation: Orientation): PhoneGridLayout => {
      const value = saved?.[orientation];
      return {
        rows: Number.isInteger(value?.rows) && value.rows >= 1 && value.rows <= 8 ? value.rows : defaults[orientation].rows,
        columns: Number.isInteger(value?.columns) && value.columns >= 1 && value.columns <= 12 ? value.columns : defaults[orientation].columns,
        compact: typeof value?.compact === 'boolean' ? value.compact : defaults[orientation].compact,
      };
    };
    return {portrait: valid('portrait'), landscape: valid('landscape')};
  } catch { return defaults; }
}

export function usePhoneLayout() {
  const [orientation, setOrientation] = useState<Orientation>(() => window.matchMedia('(orientation: landscape)').matches ? 'landscape' : 'portrait');
  const [layouts, setLayouts] = useState(readLayouts);
  const [saved, setSaved] = useState(true);
  useEffect(() => {
    const media = window.matchMedia('(orientation: landscape)');
    const change = () => setOrientation(media.matches ? 'landscape' : 'portrait');
    media.addEventListener('change', change);
    return () => media.removeEventListener('change', change);
  }, []);
  useEffect(() => {
    try { localStorage.setItem(storageKey, JSON.stringify(layouts)); setSaved(true); }
    catch { setSaved(false); }
  }, [layouts]);
  const update = (value: Partial<PhoneGridLayout>) => setLayouts(previous => ({...previous, [orientation]: {...previous[orientation], ...value}}));
  return {orientation, layout: layouts[orientation], update, saved, reset: () => update(defaults[orientation])};
}

export function PhoneLayoutDialog({orientation, layout, update, reset, saved, close}: ReturnType<typeof usePhoneLayout> & {close: () => void}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { dialog.current?.showModal(); }, []);
  return <dialog ref={dialog} className="phone-layout-dialog" aria-labelledby="phone-layout-title" onCancel={close} onClose={close}>
    <div className="phone-layout-heading"><h2 id="phone-layout-title">Phone layout</h2><button className="phone-icon-button" aria-label="Close layout" onClick={close}><X size={22}/></button></div>
    <p className="phone-layout-orientation">{orientation === 'landscape' ? 'Landscape' : 'Portrait'} settings</p>
    <p>Rotate your phone to adjust the other layout. Each orientation remembers its own choices.</p>
    <div className="phone-layout-counts">
      <label>Rows<select value={layout.rows} onChange={event => update({rows: Number(event.target.value)})}>{Array.from({length: 8}, (_, index) => <option key={index + 1}>{index + 1}</option>)}</select></label>
      <label>Columns<select value={layout.columns} onChange={event => update({columns: Number(event.target.value)})}>{Array.from({length: 12}, (_, index) => <option key={index + 1}>{index + 1}</option>)}</select></label>
    </div>
    <p><strong>{layout.rows * layout.columns} sounds per page.</strong> Buttons stay square. Very dense layouts may need scrolling to keep buttons tappable.</p>
    <label className="phone-compact-option"><input type="checkbox" checked={layout.compact} onChange={event => update({compact: event.target.checked})}/><span>Compact view<small>Hide set, search and preview controls to give the sounds more room.</small></span></label>
    <p className="phone-layout-note">{saved ? 'Saved in this browser. Your PC soundboard stays the same.' : 'Browser storage is unavailable. These choices will last until you close or reload this page.'}</p>
    <div className="phone-layout-actions"><button className="phone-secondary" onClick={reset}>Reset {orientation}</button><button className="phone-primary" onClick={close}>Done</button></div>
  </dialog>;
}

export function useSquareGrid(rows: number, columns: number, ready: boolean) {
  const viewport = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState(100);
  useEffect(() => {
    const element = viewport.current;
    if (!element || !ready) return;
    const measure = () => {
      const gap = 6;
      const width = (element.clientWidth - gap * (columns - 1)) / columns;
      const height = (element.clientHeight - gap * (rows - 1)) / rows;
      // Keep dense user-selected layouts tappable, with scrolling inside the board if needed.
      setSize(Math.max(44, Math.floor(Math.min(width, height))));
    };
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    measure();
    return () => observer.disconnect();
  }, [rows, columns, ready]);
  return {viewport, size};
}
