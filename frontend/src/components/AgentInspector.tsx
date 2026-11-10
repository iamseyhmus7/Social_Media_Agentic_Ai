import {useEffect,useRef,useState} from 'react';
import {ArrowDownLeft,ArrowUpRight,CheckCircle2,FileText,X} from 'lucide-react';
import type {AgentActivity,Project,Run} from '../types';
import {agents} from '../agents';
import {activityLabels} from '../agent-progress';
import {VoiceCasting} from './VoiceCasting';
import {assetUrl} from '../visual-progress';

const labels:Record<string,string>={goal:'Amaç',audience:'Hedef kitle',tone:'Anlatım tonu',duration:'Hedef süre',visual_direction:'Görsel yaklaşım',editorial_direction:'Kurgu yaklaşımı',title:'Başlık',angle:'Anlatı yaklaşımı',plan_revision_proposals:'Anlatı önerileri',checks:'Kontroller',reason:'Karar gerekçesi',rationale:'Değerlendirme',description:'Açıklama',tags:'Etiketler',format:'Format',continuity:'Devamlılık',cta:'Kapanış',mood:'Duygu',bpm:'Tempo',mode:'Tonalite',license:'Lisans',provider:'Kaynak',content_review:'İçerik değerlendirmesi'};
function Notes({value}:{value:unknown}){
 if(value==null||value==='')return null;
 if(typeof value==='string'||typeof value==='number')return <p>{String(value)}</p>;
 if(typeof value==='boolean')return <p>{value?'Evet':'Hayır'}</p>;
 if(Array.isArray(value))return <ul>{value.map((item,i)=><li key={i}><Notes value={item}/></li>)}</ul>;
 return <dl className="agent-facts">{Object.entries(value as Record<string,unknown>).filter(([key,item])=>labels[key]&&item!=null).map(([key,item])=><div key={key}><dt>{labels[key]}</dt><dd><Notes value={item}/></dd></div>)}</dl>;
}
function ScriptText({run}:{run:Run}){
 const script=run.outputs.script;
 const approved=run.script_progress?.approved_text;
 if(!script&&!approved)return <p className="inspector-empty">Senaryo henüz hazırlanmadı.</p>;
 return <div className="agent-script"><blockquote><span>Açılış kancası</span>{script?.hook||approved?.hook}</blockquote>{(script?.scenes||approved?.beats||[]).map((scene:{title:string;narration:string},i:number)=><article key={i}><span className="inspector-kicker">SAHNE {String(i+1).padStart(2,'0')}</span><h4>{scene.title}</h4><p>{scene.narration}</p></article>)}{script?.cta&&<p><strong>Kapanış</strong> · {script.cta}</p>}</div>;
}
function Media({run,id,kind,label,poster}:{run:Run;id?:string;kind:'image'|'audio'|'video';label:string;poster?:string}){
 const url=assetUrl(run,id);
 if(!url)return <p className="inspector-empty">{label} henüz hazır değil.</p>;
 return kind==='image'?<img loading="lazy" src={url} alt={label}/>:kind==='audio'?<audio controls preload="none" src={url} aria-label={label}/>:<video controls playsInline preload="none" src={url} poster={poster} aria-label={label}/>;
}
function Visuals({run,inputs=false}:{run:Run;inputs?:boolean}){
 const visual=run.outputs.visual||{};
 const shots=visual.storyboard?.shots||run.source_shots||[];
 const images=visual.shot_images||run.visual_progress?.shot_images||{};
 const generation=visual.generation||run.visual_progress?.generation||{};
 if(!shots.length){
  const scenes=visual.images||run.visual_progress?.scene_images||{};
  return Object.keys(scenes).length?<div className="agent-shots">{Object.entries(scenes).map(([i,asset])=><article className="agent-shot" key={i}><div className="agent-shot-image"><Media run={run} id={String(asset)} kind="image" label={`Sahne ${Number(i)+1}`}/></div><h4>{run.outputs.script?.scenes?.[Number(i)]?.title||`Sahne ${Number(i)+1}`}</h4></article>)}</div>:<p className="inspector-empty">Çekim planı ve kaynak görseller hazırlandığında burada görünecek.</p>;
 }
 return <div className="agent-shots">{shots.map((shot:any,i:number)=>{if(!inputs&&!images[shot.shot_id])return null;const receipt=generation[shot.shot_id];const source=receipt?.source;return <article className="agent-shot" key={shot.shot_id}>
  {!inputs&&<div className="agent-shot-image"><Media run={run} id={images[shot.shot_id]} kind="image" label={`${run.outputs.script?.scenes?.[shot.scene_index]?.title||'Sahne'} · Çekim ${i+1}`}/></div>}
  <div className="agent-shot-copy"><span className="inspector-kicker">SAHNE {shot.scene_index+1} · ÇEKİM {String(i+1).padStart(2,'0')}</span><h4>{run.outputs.script?.scenes?.[shot.scene_index]?.title||'Çekim'}</h4><p>{shot.purpose}</p>{inputs?<details><summary>Görsel yönergesi</summary><p lang="en">{shot.reference_prompt}</p></details>:<><p className="agent-shot-action">{shot.expected_action}</p><span className="agent-source">{source?'Lisanslı stok görsel':'Üretilen görsel'} · {source?.license||receipt?.model?.split('/').at(-1)||'Görsel üretimi'}</span>{receipt?.reason&&<details><summary>Seçim gerekçesi</summary><p>{receipt.reason}</p></details>}{source&&<p className="agent-attribution"><a href={source.creator_url||source.foreign_landing_url} target="_blank" rel="noreferrer">{source.creator}</a> · <a href={source.foreign_landing_url} target="_blank" rel="noreferrer">Kaynak</a> · <a href={source.license_url} target="_blank" rel="noreferrer">Lisans</a></p>}</> }</div>
 </article>;})}</div>;
}

function MotionClips({run}:{run:Run}){
 const final=run.outputs.motion?.clips as Run['motion_previews'];
 const clips=Object.entries(final||run.motion_previews||{}).sort(([a],[b])=>a.localeCompare(b));
 const playable=clips.filter(([,item])=>!!assetUrl(run,item.asset_id));
 const pending=clips.length-playable.length;
 return <>
  {pending>0&&<p className="agent-live-note" role="status">{pending} çekim Kaggle’da tamamlandı. Dosyalar aktarıldığında burada oynatılabilecek.</p>}
  {playable.length>0&&<div className="agent-clips">{playable.map(([shot,item])=>{
   const number=Number(shot.replace('shot-',''))+1;
   return <article key={shot}><Media run={run} id={item.asset_id} kind="video" label={`Çekim ${number}`} poster={assetUrl(run,run.outputs.visual?.shot_images?.[shot])}/><h4>Çekim {number} · {Number(item.duration_seconds).toFixed(1)} sn</h4>{!final&&!item.original&&<span className="agent-source">Canlı önizleme</span>}</article>;
  })}</div>}
  {!clips.length&&<p className="inspector-empty">Tamamlanan hareketli çekimler burada görünecek.</p>}
 </>;
}

function EditorVideos({run}:{run:Run}){
 const video=run.outputs.editor?.video;
 if(video)return <Media run={run} id={video} kind="video" label="Kurgulanan video"/>;
 const parts=Object.entries(run.editor_progress?.render||{}).filter(([,entry])=>entry.status==='rendered'&&entry.asset_id);
 return <div className="agent-clips">{parts.map(([id,entry])=>{
  const [scene,part]=id.split('-');
  const label=`Sahne ${Number(scene)+1} · ${part==='boundary'?'Geçiş':'Kurgu parçası'}`;
  return <article key={id}><Media run={run} id={entry.asset_id} kind="video" label={label}/><h4>{label}</h4></article>;
 })}</div>;
}
function Output({id,run}:{id:string;run:Run}){
 const out=run.outputs;
 if(id==='music'&&!out.music)return <p className="inspector-empty">Müzik henüz seçilmedi.</p>;
 if(id==='music'&&out.music?.provider==='none')return <p className="inspector-empty">{out.music.reason||'Kurgu arka plan müziği olmadan devam ediyor.'}</p>;
 if(id==='script')return <ScriptText run={run}/>;
 if(id==='visual')return <Visuals run={run}/>;
 if(id==='voice')return <><Notes value={{reason:out.voice?.selection?.decision?.reason}}/>{out.voice?.selection?.name&&<p className="agent-source">Anlatıcı · {out.voice.selection.name}</p>}<div className="agent-audios">{(out.voice?.audios||Object.values(run.voice_progress||{})).map((asset:string,i:number)=><article key={asset}><h4>{i+1}. {out.script?.scenes?.[i]?.title||'Seslendirme'}</h4><p>{out.script?.scenes?.[i]?.narration}</p><Media run={run} id={asset} kind="audio" label={`Sahne ${i+1} seslendirmesi`}/></article>)}</div>{out.voice_casting&&<details><summary>Anlatıcı seçimi ve ses örnekleri</summary><VoiceCasting casting={out.voice_casting} audioUrl={asset=>run.assets.find(a=>a.id===asset)?.url}/></details>}</>;
 if(id==='motion')return <MotionClips run={run}/>;
 if(id==='music')return <><h4>{out.music?.source?.title||(out.music?.provider==='user_upload'?'Yüklediğin müzik':'Bu video için oluşturulan enstrümantal eşlik')}</h4>{out.music?.source&&<p className="agent-attribution">{out.music.source.creator} · <a href={out.music.source.foreign_landing_url} target="_blank" rel="noreferrer">Müziğin kaynağı</a> · <a href={out.music.source.license_url} target="_blank" rel="noreferrer">Lisans: {out.music.source.license}</a></p>}<Notes value={out.music?.brief}/>{out.music?.asset_id&&<Media run={run} id={out.music.asset_id} kind="audio" label="Seçilen arka plan müziği"/>}<Notes value={{reason:out.music?.reason}}/>{out.music?.ducking&&<p className="agent-source">Konuşma sırasında müzik seviyesi otomatik düşürülür.</p>}</>;
 if(id==='editor')return <><EditorVideos run={run}/><Notes value={out.editor?.report?.content_review}/></>;
 if(id==='publisher')return <><Notes value={out.publisher}/>{out.publisher?.package&&<a className="button button-secondary" href={run.assets.find(a=>a.id===out.publisher.package)?.url+'?download=true'}>Paylaşım paketini indir</a>}</>;
 return <Notes value={out[id]}/>;
}
function Inputs({id,run,project}:{id:string;run:Run;project?:Project}){
 if(id==='supervisor'||id==='strategy')return <><span className="inspector-kicker">VİDEO FİKRİ</span><p className="agent-input-brief">{project?.topic||'Bu üretimin başlangıç konusu kayıtta bulunmuyor.'}</p>{project&&<Notes value={{audience:project.audience,tone:project.tone,duration:project.duration+' saniye'}}/>}{id==='strategy'&&<Notes value={run.outputs.supervisor}/>}</>;
 if(id==='script')return <Notes value={run.outputs.strategy}/>;
 if(id==='visual'||id==='voice'||id==='music')return <><ScriptText run={run}/>{id==='visual'&&<Visuals run={run} inputs/>}</>;
 if(id==='motion')return <Visuals run={run}/>;
 if(id==='editor')return <><p>Hareketli çekimler, sahne seslendirmeleri ve senaryoya göre seçilen arka plan müziği.</p><Output id="motion" run={run}/><Output id="voice" run={run}/><Output id="music" run={run}/></>;
 if(id==='publisher')return <Output id="editor" run={run}/>;
 return null;
}

export function AgentInspector({id,run,project,activity,onClose}:{id:string;run:Run;project?:Project;activity:AgentActivity;onClose:()=>void}){
 const panel=useRef<HTMLElement>(null);
 useEffect(()=>{if(!panel.current?.closest('.is-expanded'))panel.current?.scrollIntoView({block:'nearest',behavior:'smooth'});},[id]);
 const [tab,setTab]=useState<'input'|'output'>('output');
 const agent=agents.find(a=>a.id===id)!;
 const Icon=agent.icon;
 const exists=!!run.outputs[id]
  ||(id==='script'&&!!run.script_progress?.approved_text)
  ||(id==='voice'&&(!!run.outputs.voice_casting||!!Object.keys(run.voice_progress||{}).length))
  ||(id==='visual'&&!!run.visual_progress?.completed)
  ||(id==='motion'&&!!Object.keys(run.motion_previews||{}).length)
  ||(id==='editor'&&Object.values(run.editor_progress?.render||{}).some(item=>item.asset_id));
 return <section ref={panel} className="agent-inspector" aria-label={agent.name+' ayrıntıları'}>
  <header className="agent-inspector-header"><span className="agent-inspector-icon"><Icon size={22}/></span><div><span className="inspector-kicker">AGENT AYRINTISI</span><h3>{agent.name}</h3></div><span className={'inspector-status '+activity.state}><CheckCircle2 size={13}/>{activityLabels[activity.state]}</span><button type="button" onClick={onClose} aria-label="Agent ayrıntısını kapat"><X size={18}/></button></header>
  <div className="agent-inspector-tabs" role="tablist" aria-label={agent.name+' verileri'}><button id="agent-input-tab" role="tab" aria-controls="agent-detail-panel" aria-selected={tab==='input'} onClick={()=>setTab('input')}><ArrowDownLeft size={16}/>Girdiler<span>01</span></button><button id="agent-output-tab" role="tab" aria-controls="agent-detail-panel" aria-selected={tab==='output'} onClick={()=>setTab('output')}><ArrowUpRight size={16}/>Çıktılar<span>02</span></button><small><FileText size={13}/>Bu üretime ait kayıtlar</small></div>
  <div id="agent-detail-panel" className="agent-inspector-body" role="tabpanel" aria-labelledby={tab==='input'?'agent-input-tab':'agent-output-tab'} tabIndex={0}>{tab==='input'?<Inputs id={id} run={run} project={project}/>:exists?<Output id={id} run={run}/>:<div className="inspector-empty"><Icon size={28}/><h4>Çıktı henüz hazır değil</h4><p>{activity.label}</p></div>}</div>
 </section>;
}
