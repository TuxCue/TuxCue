export async function api(path:string,body?:unknown,method='POST') {
  const form=body instanceof FormData;
  const response=await fetch('/api'+path,{method,headers:method==='GET'?{}:{'X-Soundboard-Request':'1',...(form?{}:{'Content-Type':'application/json'})},body:method==='GET'?undefined:form?body:JSON.stringify(body??{})});
  const data=await response.json();
  if(!response.ok) throw new Error(typeof data.detail==='string'?data.detail:'That action could not be completed. Check the entered values.');
  return data;
}
export function time(seconds:number,precise=false) {
  const n=Math.max(0,seconds||0);
  // Round once so binary floating-point boundaries don't display 4.6 as 4.599.
  const milliseconds=Math.round(n*1000);
  const whole=precise?Math.floor(milliseconds/1000):Math.floor(n);
  return `${Math.floor(whole/60)}:${String(whole%60).padStart(2,'0')}${precise?'.'+String(milliseconds%1000).padStart(3,'0'):''}`;
}
export async function downloadSet(id:string,name:string) {
  const response=await fetch(`/api/sets/${id}/export`);
  if(!response.ok) {const r=await response.json();throw new Error(r.detail??'Export failed.');}
  const url=URL.createObjectURL(await response.blob());
  const link=document.createElement('a');link.href=url;link.download=name.replace(/[^\p{L}\p{N} _-]/gu,'_')+'.soundboard.zip';link.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
