import {useState} from 'react';
import {useQuery,useQueryClient} from '@tanstack/react-query';
import {api,post} from '../api';
import {Button} from './ui';
import type {Run} from '../types';
import {clarificationTarget,feedbackStatusText,type Feedback} from '../feedback-state';

export function FeedbackPanel({projectId,run}:{projectId:string;run:Run}){
 const cache=useQueryClient();const [prompt,setPrompt]=useState('');const [answer,setAnswer]=useState('');
 const [busy,setBusy]=useState(false);const [error,setError]=useState('');
 const [requestId,setRequestId]=useState(()=>crypto.randomUUID());
 const query=useQuery({queryKey:['feedback',projectId],queryFn:()=>api<Feedback[]>('/projects/'+projectId+'/feedback'),refetchInterval:3000});
 const current=query.data?.find(f=>f.source_run_id===run.id&&['queued','waiting_provider','needs_clarification','waiting_quota','failed'].includes(f.status));
 const target=clarificationTarget(projectId,run,current);
 const active=['queued','running','waiting_remote','waiting_provider'].includes(run.status);
 async function submit(){setBusy(true);setError('');try{
  await post('/projects/'+projectId+'/feedback',{run_id:run.id,prompt,request_id:requestId});
  setPrompt('');setRequestId(crypto.randomUUID());await query.refetch();
 }catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 async function respond(){setBusy(true);setError('');try{
  if(!target)return;
  await post(target.path,{answer});
  setAnswer('');await query.refetch();await cache.invalidateQueries({queryKey:['projects']});
 }catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 return <section className="scene-editor reedit-panel" aria-label="Video geri bildirimi">
  <h2>Videonu birlikte geliştirelim</h2><p>Ne değişsin? İsteğini yaz; Supervisor gerekli agentları seçsin.</p>
  {error&&<p role="alert" className="error-box">{error}</p>}
  {current?.status==='waiting_provider'&&<p role="status">{feedbackStatusText(current)}</p>}
  {target?<>
   <p role="status">{target.question}</p>
   <label>Yanıtın<textarea rows={3} maxLength={4000} value={answer} onChange={e=>setAnswer(e.target.value)}/></label>
   <Button disabled={busy||!answer.trim()} onClick={respond}>Yanıtla ve devam et</Button>
  </>:<>
   <label>Neyi değiştirmek istersin?<textarea rows={4} maxLength={4000} value={prompt} onChange={e=>setPrompt(e.target.value)} placeholder="Örneğin: İkinci sahneyi değiştir, anlatıcı daha sakin olsun ve altyazıları küçült."/></label>
   <Button disabled={busy||active||!run.outputs.editor?.video||prompt.trim().length<3||current?.status==='queued'} onClick={submit}>{current?.status==='queued'?'İsteğin değerlendiriliyor…':'Değişiklikleri uygula'}</Button>
  </>}
  <p className="muted small">Değişiklikler yeni sürüm oluşturur. Yayın için yeni sürümü inceleyip onaylaman gerekir.</p>
  {query.data?.slice(0,5).map(f=><details key={f.id}><summary>{f.prompt}</summary><p role="status">{feedbackStatusText(f)}</p></details>)}
 </section>;
}
