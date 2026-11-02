import {useState} from 'react';
import {useQueryClient} from '@tanstack/react-query';
import {api} from '../api';
import {Button} from './ui';
export function BrandLogo({hasLogo,notify}:{hasLogo:boolean;notify:(message:string)=>void}){
const [file,setFile]=useState<File|null>(null);const [busy,setBusy]=useState(false);const cache=useQueryClient();
return <div className="brand-logo"><h3>Marka logosu</h3><p className="muted small">Şeffaf PNG önerilir. En fazla 5 MB. Sonraki üretimlerde kapağa ve videoya eklenir.</p>{hasLogo&&<img src={'/api/v1/brand/logo?t='+Date.now()} alt="Kayıtlı marka logosu"/>}<label>Logo dosyası<input type="file" accept="image/png,image/jpeg,image/webp" onChange={e=>setFile(e.target.files?.[0]||null)}/></label><Button variant="secondary" disabled={!file||busy} onClick={async()=>{setBusy(true);try{const data=new FormData();data.set('file',file!);await api('/brand/logo',{method:'POST',body:data});await cache.invalidateQueries({queryKey:['brand']});notify('Marka logosu kaydedildi.');setFile(null);}catch(error){notify((error as Error).message);}finally{setBusy(false);}}}>Logoyu kaydet</Button></div>;
}
