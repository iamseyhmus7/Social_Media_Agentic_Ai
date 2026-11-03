import {useEffect,useState} from 'react';
import {ReactFlow,Handle,Position,Background,BackgroundVariant,Controls,type NodeProps} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {Sparkles,FileText,ScrollText,Image,Mic,Film,Send,CheckCircle2,Clock3,LoaderCircle,AlertCircle,Maximize2,Minimize2,Workflow} from 'lucide-react';
import type {Run} from '../types';
import {agents} from '../agents';
import {visualProgress} from '../visual-progress';
const roles=agents.map(a=>[a.id,a.name,a.summary,a.icon] as const);
function AgentNode({data}:NodeProps){
const Icon=data.icon as typeof Sparkles;const state=data.state as string;
return <div className={'agent-node '+state+(data.supervisor?' supervisor-node':'')}><Handle type="target" position={Position.Top}/><span className="agent-icon"><Icon size={23} strokeWidth={1.6}/></span><div className="agent-node-copy"><strong>{String(data.label)}</strong><small>{String(data.subtitle)}</small></div><span className="agent-state">{state==='done'?<CheckCircle2 size={18}/>:state==='active'?<LoaderCircle size={19} className="spin"/>:state==='error'?<AlertCircle size={18}/>:<Clock3 size={18}/>}<span>{state==='done'?'Tamamlandı':state==='waiting'?'Bekliyor':state==='error'?'Durduruldu':'Çalışıyor'}</span></span><Handle type="source" position={Position.Bottom}/></div>;
}
const nodeTypes={agent:AgentNode};
const flowLabels={'controls.ariaLabel':'Akış görünümü kontrolleri','controls.zoomIn.ariaLabel':'Yakınlaştır','controls.zoomOut.ariaLabel':'Uzaklaştır','controls.fitView.ariaLabel':'Akışı ekrana sığdır'};
export function AgentFlow({run,demo=false,onSelect}:{run:Run|null;demo?:boolean;onSelect?:(stage:string)=>void}){
const [expanded,setExpanded]=useState(false);
const [compact,setCompact]=useState(()=>window.innerWidth<700);
useEffect(()=>{const update=()=>setCompact(window.innerWidth<700);const escape=(event:KeyboardEvent)=>{if(event.key==='Escape')setExpanded(false);};window.addEventListener('resize',update);window.addEventListener('keydown',escape);return()=>{window.removeEventListener('resize',update);window.removeEventListener('keydown',escape);};},[]);
const visualState=visualProgress(run,demo);
const visibleRoles=roles.filter(([id])=>id!=='motion'||!run||demo||(run.pipeline_version||1)>=2);
const nodes=visibleRoles.map(([key,label,subtitle,icon],i)=>{const done=!!run?.outputs[key];const active=run?.stage===key&&['running','waiting_remote','waiting_provider','failed','waiting_quota','waiting_input'].includes(run.status);const state=active?(['running','waiting_remote','waiting_provider'].includes(run?.status||'')?'active':'error'):done?'done':'waiting';return {id:key,type:'agent',position:{x:compact?0:185,y:i*84},ariaLabel:label+' — '+(state==='done'?'Tamamlandı':state==='active'?'Çalışıyor':state==='error'?'Durduruldu':'Bekliyor'),data:{label:key==='script'&&active&&run?.script_progress?.phase?run.script_progress.label:label,icon,state,supervisor:key==='supervisor',subtitle:key==='script'&&active&&run?.script_progress?.text_approved?'Metin onaylandı; görsel plan hazırlanıyor.':state==='waiting'?'Sırada bekliyor.':key==='visual'&&active?`${visualState.completed} / ${visualState.total} ${visualState.label} hazır`:subtitle}};});
const pairs=(run?.pipeline_version||1)>=3?visibleRoles.filter(r=>r[0]!=='supervisor').map(r=>['supervisor',r[0]]):visibleRoles.slice(1).map((r,i)=>[visibleRoles[i][0],r[0]]);
const edges=pairs.map(([source,target])=>({id:source+target,source,target,type:'smoothstep',style:{stroke:run?.outputs[source]?'#ac97d2':'#d4cfdf',strokeWidth:1.5},animated:run?.stage===target&&run.status==='running'}));
const completed=nodes.filter(node=>node.data.state==='done').length;
return <section className={'agent-workspace '+(expanded?'is-expanded':'')} aria-label="Agent çalışma alanı"><div className="flow-toolbar"><div><Workflow size={16}/><span>SUPERVISOR + {visibleRoles.length-1} UZMAN</span><em className="flow-mode">{demo?"Örnek akış":(run?.pipeline_version||1)<2?"Eski üretim akışı":(run?.pipeline_version||1)>=3?"Otonom agent akışı":"Proje akışı"}</em></div><button className="flow-expand" aria-label={expanded?'Agent alanını küçült':'Agent alanını genişlet'} onClick={()=>setExpanded(!expanded)}>{expanded?<Minimize2 size={16}/>:<Maximize2 size={16}/>}<span>{expanded?'Küçült':'Genişlet'}</span></button></div><div className="flow" aria-label="Agent üretim akışı"><ReactFlow key={(compact?'compact':'desktop')+(expanded?'expanded':'inline')} ariaLabelConfig={flowLabels} nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{padding:compact?0.055:0.06}} minZoom={0.35} maxZoom={1.1} nodesDraggable={false} nodesConnectable={false} panOnDrag zoomOnScroll={false} zoomOnPinch onNodeClick={(_,node)=>onSelect?.(node.id)} proOptions={{hideAttribution:false}}><Background variant={BackgroundVariant.Dots} gap={20} size={1.1} color="#d6cfe5"/><Controls showInteractive={false}/></ReactFlow></div><div className="flow-footer"><span><span className="status-dot"/>{completed} / {visibleRoles.length} agent tamamlandı</span><small>Çıktıları görmek için bir agent seç</small></div></section>;
}
