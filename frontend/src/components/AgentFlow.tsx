import {useEffect,useRef,useState,type CSSProperties} from 'react';
import {ReactFlow,BaseEdge,Handle,Position,Background,BackgroundVariant,Controls,MarkerType,type NodeProps,type EdgeProps} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {Sparkles,CheckCircle2,Clock3,LoaderCircle,PauseCircle,Maximize2,Minimize2,Workflow,Radio,ArrowRight} from 'lucide-react';
import type {AgentActivity,Project,Run} from '../types';
import {agents} from '../agents';
import {agentActivity,activityLabels,diagramLayout} from '../agent-progress';
import './agent-flow.css';
import {AgentInspector} from './AgentInspector';

function ActivityIcon({state}:{state:AgentActivity['state']}){
 if(state==='done')return <CheckCircle2 size={14}/>;
 if(state==='active'||state==='remote')return <LoaderCircle size={14} className="activity-spinner"/>;
 if(state==='paused'||state==='waiting')return <PauseCircle size={14}/>;
 return <Clock3 size={14}/>;
}
const sides={top:Position.Top,left:Position.Left,right:Position.Right,bottom:Position.Bottom};
function AgentNode({data}:NodeProps){
 const Icon=data.icon as typeof Sparkles;
 const activity=data.activity as AgentActivity;
 const progress=typeof activity.completed==='number'&&typeof activity.total==='number'&&activity.total>0;
 const percent=progress?Math.min(100,100*activity.completed!/activity.total!):0;
 return <div className={'agent-node live-agent '+activity.state+(data.supervisor?' supervisor-node':'')}>
  {Object.entries(sides).map(([side,position])=><Handle key={'in-'+side} type="target" id={'in-'+side} position={position} isConnectable={false}/>)}
  <div className="live-agent-heading"><span className="agent-icon"><Icon size={21} strokeWidth={1.6}/></span><strong>{String(data.label)}</strong><span className={'live-agent-state '+activity.state}><ActivityIcon state={activity.state}/>{activityLabels[activity.state]}</span></div>
  <div className="live-agent-copy"><p>{activity.label}</p>{activity.detail&&<small title={activity.detail}>{activity.detail}</small>}</div>
  <div className="live-agent-bottom">{progress?<><span className="live-agent-meter" role="progressbar" aria-label={String(data.label)+' ilerlemesi'} aria-valuenow={activity.completed!} aria-valuemin={0} aria-valuemax={activity.total!}><i style={{width:percent+'%'}}/></span><span className="live-agent-count">{activity.completed}/{activity.total}</span></>:<span className="live-agent-phase">{activity.state==='active'||activity.state==='remote'?<><i/><i/><i/></>:activity.state==='done'?'Çıktı kaydedildi':activity.state==='waiting'?'Hazır çıktılar korunuyor':activity.state==='pending'?'Bağımlı görev bekleniyor':''}</span>}</div>
  {Object.entries(sides).map(([side,position])=><Handle key={'out-'+side} type="source" id={'out-'+side} position={position} isConnectable={false}/>)}
 </div>;
}
const nodeTypes={agent:AgentNode};
function OutsideEdge({sourceX,sourceY,targetX,targetY,data,markerEnd,style}:EdgeProps){
 const route=data?.route as string;
 const outside=Number(data?.outside);
 const lane=sourceY>targetY?(sourceY+targetY)/2:Math.max(sourceY,targetY)+32;
 const path=route==='supply'?`M ${sourceX} ${sourceY} H ${outside} V ${targetY} H ${targetX}`:
  `M ${sourceX} ${sourceY} V ${lane} H ${targetX} V ${targetY}`;
 return <BaseEdge path={path} markerEnd={markerEnd} style={style}/>;
}
const edgeTypes={outside:OutsideEdge};
const flowLabels={'controls.ariaLabel':'Akış görünümü kontrolleri','controls.zoomIn.ariaLabel':'Yakınlaştır','controls.zoomOut.ariaLabel':'Uzaklaştır','controls.fitView.ariaLabel':'Akışı ekrana sığdır'};

export function AgentFlow({run,project,demo=false,focusAgent}:{run:Run|null;project?:Project;demo?:boolean;focusAgent?:string}){
 const [selected,setSelected]=useState<string|null>(null);
 useEffect(()=>setSelected(null),[run?.id]);
 useEffect(()=>{if(focusAgent)setSelected(focusAgent);},[focusAgent]);
 const [expanded,setExpanded]=useState(false);
 const [width,setWidth]=useState(650);
 const [clock,setClock]=useState(()=>Date.now()/1000);
 const surface=useRef<HTMLDivElement>(null);
 const instance=useRef<{fitView:(options:{padding:number;duration?:number;maxZoom:number})=>Promise<boolean>}|null>(null);
 useEffect(()=>{const target=surface.current;if(!target)return;const observer=new ResizeObserver(entries=>{setWidth(entries[0].contentRect.width);requestAnimationFrame(()=>{void instance.current?.fitView({padding:.12,duration:0,maxZoom:1});});});observer.observe(target);return()=>observer.disconnect();},[]);
 useEffect(()=>{if(!expanded)return;const escape=(e:KeyboardEvent)=>{if(e.key==='Escape')setExpanded(false);};document.addEventListener('keydown',escape);return()=>document.removeEventListener('keydown',escape);},[expanded]);
 useEffect(()=>{const timer=window.setInterval(()=>setClock(Date.now()/1000),1000);return()=>window.clearInterval(timer);},[]);
 const visible=agents.filter(a=>(a.id!=='motion'||!run||demo||(run.pipeline_version||1)>=2)&&(a.id!=='music'||!run||demo||run.outputs.music||!run.outputs.editor));
 const activities=Object.fromEntries(visible.map(a=>[a.id,agentActivity(run,a.id,a.summary,demo)]));
 const columns=width>=(expanded?690:950)?3:width<470?1:2;
 const layout=diagramLayout(visible.map(a=>a.id),columns);
 const identity=visible.map(a=>a.id).join(',');
 useEffect(()=>{const timer=window.setTimeout(()=>{void instance.current?.fitView({padding:.12,duration:0,maxZoom:1});},80);return()=>window.clearTimeout(timer);},[columns,expanded,identity]);
 const nodes=visible.map(a=>({id:a.id,type:'agent',position:layout.positions[a.id],selected:selected===a.id,ariaLabel:a.name+' — '+activityLabels[activities[a.id].state]+': '+activities[a.id].label,data:{label:a.name,icon:a.icon,activity:activities[a.id],supervisor:a.id==='supervisor'}}));
 const edges=layout.links.map(([source,target])=>{
  const a=layout.positions[source],b=layout.positions[target];
  const lateral=a.y===b.y;
  const direction=b.x>a.x?'right':'left';
  const supply=source==='script'&&target==='music'&&columns>1;
  const returning=source==='music'&&target==='editor'&&columns>1;
  const active=['active','remote'].includes(activities[target].state)&&activities[source].state==='done';
  const done=activities[source].state==='done'&&activities[target].state==='done';
  const color=active?'#8b56c5':done?'#8cae9e':'#d3c8df';
  const downward=b.y>a.y;
  return {id:source+'-'+target,source,target,type:supply||returning?'outside':'smoothstep',
   sourceHandle:'out-'+(supply?'right':returning?(columns===2?'top':'bottom'):lateral?direction:downward?'bottom':'top'),
   targetHandle:'in-'+(supply?'right':returning?'bottom':lateral?(direction==='right'?'left':'right'):downward?'top':'bottom'),
   data:{route:supply?'supply':'return',outside:Math.max(...Object.values(layout.positions).map(p=>p.x))+320},
   animated:active,selectable:false,className:active?'live-edge-active':'',style:{stroke:supply||returning?'#ad91ca':color,strokeWidth:active?2.5:1.8},markerEnd:{type:MarkerType.ArrowClosed,color:supply||returning?'#ad91ca':color,width:18,height:18},pathOptions:{borderRadius:14,offset:24}};
 });
 const current=visible.find(a=>a.id===(run?.stage==='quality'?'editor':run?.stage));
 const activity=current?activities[current.id]:null;
 const completed=visible.filter(a=>activities[a.id].state==='done').length;
 const currentState=activity?.state||'pending';
 const wait=activity?.retry_at?Math.max(0,Math.ceil(activity.retry_at-clock)):null;
 const terminal=!!run&&['awaiting_approval','published','scheduled','script_ready'].includes(run.status);
 return <section className={'agent-workspace live-flow '+(expanded?'is-expanded':'')} aria-label="Agent çalışma alanı">
  <div className="flow-toolbar"><div><Workflow size={18}/><span>Üretim ekibi</span><em className="flow-mode">{demo?'Örnek akış':`${visible.length} agent`}</em></div><button className="flow-expand" aria-label={expanded?'Agent alanını küçült':'Agent alanını genişlet'} aria-expanded={expanded} onClick={()=>setExpanded(!expanded)}>{expanded?<Minimize2 size={16}/>:<Maximize2 size={16}/>}<span>{expanded?'Küçült':'Genişlet'}</span></button></div>
  <div className={'flow-current '+currentState} role="status" aria-live="polite"><span className="flow-current-icon"><Radio size={18}/></span><div><span>{demo?'Örnek çalışma':terminal?'Üretim tamamlandı':current?current.name:'Üretim bekleniyor'}</span><strong>{terminal?(run?.status==='awaiting_approval'?'Video incelemen için hazır':run?.status==='script_ready'?'Senaryo hazır':'Üretim çıktıları hazır'):activity?.label||'Bir konu yazdığında ekibin burada çalışmaya başlayacak.'}</strong>{!terminal&&activity?.detail&&<p>{activity.detail}</p>}{!terminal&&activity?.state==='waiting'&&<p>{activity.automatic?(wait===null?'Otomatik yeniden deneme etkin.':wait>0?`Sonraki otomatik deneme ${wait} saniye sonra.`:'Otomatik yeniden deneme sırası bekleniyor.'):'Otomatik yeniden deneme planlanmadı.'}</p>}</div><span className="flow-live-tag"><span/>{demo?'Örnek':run?'Canlı takip':'Hazır'}</span></div>
  <div ref={surface} className="flow live-flow-surface" style={{'--live-flow-height':layout.height+'px'} as CSSProperties} aria-label="Agent üretim akışı"><ReactFlow onInit={value=>{instance.current={fitView:options=>value.fitView(options)};void value.fitView({padding:.12,maxZoom:1});}} ariaLabelConfig={flowLabels} nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} fitView fitViewOptions={{padding:.12,maxZoom:1}} minZoom={.3} maxZoom={1.3} nodesDraggable={false} nodesConnectable={false} panOnDrag zoomOnScroll={false} zoomOnPinch onNodeClick={(_,node)=>setSelected(node.id)} proOptions={{hideAttribution:false}}><Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#d9cfe5"/><Controls showInteractive={false}/></ReactFlow></div>
  <div className="flow-footer"><span><CheckCircle2 size={14}/>{completed}/{visible.length} görev hazır</span><small>Ana hat: üretim sırası · Yan kol: müzik<ArrowRight size={12}/>Çıktılar için karta dokun</small></div>
  {run&&selected&&activities[selected]&&<AgentInspector key={run.id+selected} id={selected} run={run} project={project} activity={activities[selected]} onClose={()=>setSelected(null)}/>}
 </section>;
}
