import {useState,type ReactNode} from 'react';
import {Search,Trash2} from 'lucide-react';
import {Button,Modal} from './ui';
import {post} from '../api';
import type {Project} from '../types';
import './ContentLibrary.css';

const active=['queued','running','waiting_remote','waiting_provider'];
export function ContentLibrary({projects,renderProject,onDeleted}:{projects:Project[];renderProject:(p:Project)=>ReactNode;onDeleted:(ids:string[],pending:boolean)=>void}){
  const [search,setSearch]=useState('');
  const [filter,setFilter]=useState('all');
  const [selected,setSelected]=useState<Set<string>>(new Set());
  const [confirm,setConfirm]=useState<Project[]>([]);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const filtered=projects.filter(p=>p.title.toLocaleLowerCase('tr').includes(search.toLocaleLowerCase('tr'))&&(filter==='all'||p.run?.status===filter));
  const chosen=projects.filter(p=>selected.has(p.id));
  const eligible=filtered.filter(p=>!active.includes(p.run?.status||''));
  const allChecked=eligible.length>0&&eligible.every(p=>selected.has(p.id));
  function toggle(id:string){setSelected(prior=>{const next=new Set(prior);if(next.has(id))next.delete(id);else if(next.size<100)next.add(id);return next;});}
  function selectVisible(){setSelected(prior=>{const next=new Set(prior);for(const p of eligible){if(allChecked)next.delete(p.id);else if(next.size<100)next.add(p.id);}return next;});}
  async function remove(){
    setBusy(true);setError('');
    try{
      const result=await post<{deleted_ids:string[];storage_cleanup_pending:boolean}>('/projects/delete',{project_ids:confirm.map(p=>p.id)});
      setSelected(prior=>new Set([...prior].filter(id=>!result.deleted_ids.includes(id))));
      setConfirm([]);onDeleted(result.deleted_ids,result.storage_cleanup_pending);
    }catch(exc){setError((exc as Error).message);}finally{setBusy(false);}
  }
  return <>
    <div className="library-controls"><label className="search"><Search size={18}/><input aria-label="İçerik ara" placeholder="İçeriklerde ara…" value={search} onChange={e=>setSearch(e.target.value)}/></label><select aria-label="Durum filtresi" value={filter} onChange={e=>setFilter(e.target.value)}><option value="all">Tüm durumlar</option><option value="running">Üretiliyor</option><option value="awaiting_approval">Onay bekliyor</option><option value="failed">Başarısız</option><option value="cancelled">Durduruldu</option></select></div>
    <div className="library-selection"><label className="checkbox"><input type="checkbox" aria-label="Gösterilen silinebilir içerikleri seç" checked={allChecked} disabled={!eligible.length||busy} onChange={selectVisible}/>Gösterilenleri seç</label><span aria-live="polite">{chosen.length} içerik seçildi</span><Button variant="danger" disabled={!chosen.length||busy} onClick={()=>{setError('');setConfirm(chosen);}}><Trash2 size={16}/>Seçilenleri sil</Button></div>
    <p className="muted small">Çalışan üretimleri silmeden önce durdur. Bir defada en fazla 100 içerik seçebilirsin.</p>
    <div className="managed-library-list">{filtered.map(p=>{const blocked=active.includes(p.run?.status||'');return <div key={p.id} className={'managed-library-row'+(selected.has(p.id)?' is-selected':'')}><input type="checkbox" aria-label={p.title+' içeriğini seç'} checked={selected.has(p.id)} disabled={blocked||busy||(!selected.has(p.id)&&chosen.length>=100)} onChange={()=>toggle(p.id)}/><div className="managed-library-content">{renderProject(p)}</div><button className="icon-button library-delete" aria-label={p.title+' içeriğini sil'} title={blocked?'Önce üretimi durdur':p.title+' içeriğini sil'} disabled={blocked||busy} onClick={()=>{setError('');setConfirm([p]);}}><Trash2 size={17}/></button></div>;})}{!filtered.length&&<p className="muted">Bu görünümde henüz içerik yok.</p>}</div>
    <Modal open={confirm.length>0} onClose={()=>{if(!busy){setConfirm([]);setError('');}}} title={confirm.length===1?'İçeriği kalıcı olarak sil?':confirm.length+' içeriği kalıcı olarak sil?'} description="Seçilen içeriklerin tüm sürümleri, videoları, sesleri ve görselleri bu uygulamadan silinir. Bu işlem geri alınamaz. YouTube’daki yayınlar silinmez.">
      <ul className="deletion-titles">{confirm.map(p=><li key={p.id}>{p.title}</li>)}</ul>
      {error&&<p role="alert" className="error-box">{error}</p>}
      <div className="deletion-actions"><Button variant="secondary" disabled={busy} onClick={()=>setConfirm([])}>Vazgeç</Button><Button variant="danger" disabled={busy} onClick={remove}><Trash2 size={16}/>{busy?'Siliniyor…':'Kalıcı olarak sil'}</Button></div>
    </Modal>
  </>;
}
