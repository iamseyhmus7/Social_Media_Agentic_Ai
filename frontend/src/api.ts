let csrf = '';
export function setCSRF(value:string) {csrf=value;}
export async function api<T=any>(path:string, options:RequestInit={}):Promise<T>{
  let response:Response;
  try { response=await fetch('/api/v1'+path,{...options,headers:{...(options.body instanceof FormData?{}:{'Content-Type':'application/json'}),'X-CSRF-Token':csrf,...options.headers},credentials:'same-origin'}); }
  catch {throw new Error('API’ye ulaşılamıyor. Backend sunucusunun çalıştığını kontrol et.');}
  const data=await response.json().catch(()=>({detail:'Sunucudan geçerli yanıt alınamadı.'}));
  if(!response.ok) throw new Error(typeof data.detail==='string'?data.detail:'Alanları kontrol edip yeniden dene.');
  return data;
}
export const post=<T=any>(path:string,body:unknown={})=>api<T>(path,{method:'POST',body:JSON.stringify(body)});
