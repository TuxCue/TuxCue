export async function api(path:string,body?:unknown,method='POST') {
  const form=body instanceof FormData;
  const response=await fetch('/api'+path,{method,headers:method==='GET'?{}:{'X-Soundboard-Request':'1',...(form?{}:{'Content-Type':'application/json'})},body:method==='GET'?undefined:form?body:JSON.stringify(body??{})});
  const data=await response.json();
  if(!response.ok) throw new Error(typeof data.detail==='string'?data.detail:'That action could not be completed. Check the entered values.');
  return data;
}
export function time(seconds:number,precise=false) {
  const n=Math.max(0,seconds||0);
  return `${Math.floor(n/60)}:${String(Math.floor(n%60)).padStart(2,'0')}${precise?'.'+String(Math.floor((n%1)*1000)).padStart(3,'0'):''}`;
}
export async function downloadSet(id:string,name:string) {
  const response=await fetch(`/api/sets/${id}/export`);
  if(!response.ok) {const r=await response.json();throw new Error(r.detail??'Export failed.');}
  const url=URL.createObjectURL(await response.blob());
  const link=document.createElement('a');link.href=url;link.download=name.replace(/[^\p{L}\p{N} _-]/gu,'_')+'.soundboard.zip';link.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
