import type {AgentActivity,Run} from './types';
export const activityLabels:Record<AgentActivity['state'],string>={pending:'Sırada',done:'Hazır',active:'Çalışıyor',waiting:'Bekliyor',remote:'GPU’da çalışıyor',paused:'Duraklatıldı',queued:'Kuyrukta'};
export function agentActivity(run:Run|null,key:string,summary:string,demo=false):AgentActivity{
 if(!demo&&run?.agent_progress?.[key])return run.agent_progress[key];
 if(run?.outputs[key])return {state:'done',label:'Görev tamamlandı'};
 if(run?.stage===key){
  if(run.status==='waiting_provider')return {state:'waiting',label:summary,detail:'Model hizmetinin yanıtı bekleniyor.',...run.provider_wait};
  if(['failed','waiting_quota','waiting_input','cancelled'].includes(run.status))return {state:'paused',label:summary,detail:run.error||undefined};
  if(run.status==='queued')return {state:'queued',label:'Üretim kuyruğunda bekliyor'};
  if(['running','waiting_remote'].includes(run.status))return {state:run.status==='waiting_remote'?'remote':'active',label:summary};
 }
 return {state:'pending',label:run?'Önceki görevlerin tamamlanmasını bekliyor':'Yeni üretimle başlayacak'};
}
export function diagramLayout(ids:string[],columns:number){
 const two:Record<string,[number,number]>={supervisor:[0,0],strategy:[346,0],script:[346,168],voice:[0,168],visual:[0,336],motion:[346,336],editor:[346,504],publisher:[0,504],music:[0,672]};
 const three:Record<string,[number,number]>={supervisor:[0,0],strategy:[346,0],script:[692,0],voice:[692,168],visual:[346,168],motion:[0,168],editor:[0,336],publisher:[346,336],music:[692,336]};
 const points:Record<string,[number,number]>=Object.fromEntries(ids.map((id,i)=>[id,columns===1?[0,i*164]:(columns===3?three:two)[id]||[0,i*164]]));
 const positions=Object.fromEntries(Object.entries(points).map(([id,[x,y]])=>[id,{x,y}]));
 const main=['supervisor','strategy','script','voice','visual',...(ids.includes('motion')?['motion']:[]),'editor','publisher'].filter(id=>ids.includes(id));
 const links=main.slice(1).map((id,i)=>[main[i],id]);
 if(ids.includes('music')){
  if(columns===1){
   const before=main.indexOf('editor');
   links.splice(before-1,1,[main[before-1],'music'],['music','editor']);
  }else links.push(['script','music'],['music','editor']);
 }
 return {positions,links,height:Math.max(...Object.values(positions).map(p=>p.y),0)+172};
}
