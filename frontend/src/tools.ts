// Optional browser tools use the same local API as the visible controls.
type Tool = {name: string; title: string; description: string; inputSchema: object; annotations: {readOnlyHint: boolean; untrustedContentHint: boolean}; execute: (input: unknown)=>Promise<unknown>};
type ToolDocument = Document & {modelContext?: {registerTool: (tool: Tool, options: {signal: AbortSignal})=>void|Promise<void>}};

export function registerTools(api: (path: string, body?: unknown, method?: string)=>Promise<any>, refresh: ()=>Promise<void>) {
  const context = (document as ToolDocument).modelContext;
  if(!context?.registerTool) return;
  const lifecycle=new AbortController();
  const emptyInput=(input: unknown)=>{if(!input || typeof input!=='object' || Array.isArray(input) || Object.keys(input).length) throw new Error('Expected an empty object.')};
  const tools: Tool[]=[
    {name:'list_sounds',title:'List soundboard sounds',description:'List imported sounds and report whether the PC virtual microphone is connected.',inputSchema:{type:'object',properties:{},additionalProperties:false},annotations:{readOnlyHint:true,untrustedContentHint:true},async execute(input){emptyInput(input); const s=await api('/state',undefined,'GET'); return {connected:s.connected,sounds:s.sounds.map(({id,name,duration}:{id:string;name:string;duration:number})=>({id,name,duration}))}}},
    {name:'play_sound',title:'Play a sound on the PC',description:'Start an imported clip on the PC. Preview plays in the selected headphones only; broadcast sends it to the headphones and connected virtual microphone.',inputSchema:{type:'object',properties:{sound_id:{type:'string'},mode:{type:'string',enum:['preview','broadcast']}},required:['sound_id','mode'],additionalProperties:false},annotations:{readOnlyHint:false,untrustedContentHint:false},async execute(input){const v=input as {sound_id?:unknown;mode?:unknown}; if(!v || typeof v.sound_id!=='string' || !['preview','broadcast'].includes(String(v.mode)) || Object.keys(v).some(k=>!['sound_id','mode'].includes(k))) throw new Error('Provide a sound ID and preview or broadcast mode.'); await api('/play',v); await refresh(); return {started:true,sound_id:v.sound_id,mode:v.mode}}},
    {name:'stop_sounds',title:'Stop soundboard clips',description:'Stop the current clip on the PC. The microphone connection remains active.',inputSchema:{type:'object',properties:{},additionalProperties:false},annotations:{readOnlyHint:false,untrustedContentHint:false},async execute(input){emptyInput(input); await api('/stop'); await refresh(); return {stopped:true}}}
  ];
  for(const tool of tools) {try {void Promise.resolve(context.registerTool(tool,{signal:lifecycle.signal})).catch(()=>{});} catch {/* Optional browser capability. */}}
  return ()=>lifecycle.abort();
}
