export type Sound = {id:string;name:string;filename:string;duration:number;trashed?:boolean};
export type Tile = {id:string;sound_id:string;label:string;color:string;volume:number;shortcut:string};
export type Profile = {id:string;name:string;rows:number;columns:number;playback_mode:'replace'|'overlap';tiles:(Tile|null)[]};
export type Device = {name:string;description:string;default:boolean;muted:boolean};
export type Settings = {microphone:string;output:string;mic_enabled:boolean;send_volume:number;monitor_volume:number;mic_volume:number};
export type State = {storage?:{folder:string;default_folder:string;can_change:boolean};connected:boolean;settings:Settings;devices:{inputs:Device[];outputs:Device[];server:string};sounds:Sound[];trash:Sound[];playing_id:string|null;playing:{sound_id:string;tile_id:string|null;mode:string;instance_id:string}[];position:number;duration:number;mode:string|null;error:string|null;device_error:string|null;importing:boolean;version:string;sets:{active_id:string;profiles:Record<string,Profile>;hotkeys_enabled:boolean;stop_shortcut:string};hotkeys:{available:boolean;enabled:boolean;error:string|null;conflicts:string[];suspended:boolean}};
