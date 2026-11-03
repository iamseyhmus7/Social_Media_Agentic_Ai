import React from 'react';
import {AbsoluteFill,OffthreadVideo,staticFile,useCurrentFrame,interpolate,Easing} from './timeline.jsx';
import {cameraStyle,transitionStyle,titleMotion,unit} from './motion-design.mjs';
import {Object3D} from './Object3D.jsx';
import {SceneTransition,EffectFootage,FootageMotionBlur,TitleAnnotation,LottieOverlay} from './ProEditing.jsx';
const clamp={extrapolateLeft:'clamp',extrapolateRight:'clamp'};
const ease={...clamp,easing:Easing.bezier(.16,1,.3,1)};

const Footage=({clip,file,offset,style})=>{
 const frame=useCurrentFrame();const d=clip.design;
 return <div style={{position:'absolute',overflow:'hidden',...style}}><EffectFootage file={file} offset={offset} design={d}
  style={{width:'100%',height:'100%',objectFit:'cover',...cameraStyle(frame,clip.frames,d.camera,clip.punch_in)}}/></div>;
};

export const DirectedSegment=({clip,next})=>{
 const f=useCurrentFrame();const d=clip.design,n=clip.transition_frames;
 const layout=d.layout;
 const titleSize=d.object_3d?Math.min(76,d.title_size):d.title_size;
 // Reserve space for long Turkish headings above the geometry and captions below.
 const titleLines=Math.ceil((clip.title||'').length*titleSize*.65/760);
 const objectTop=Math.max(470,270+titleLines*titleSize*1.16);
 const seed=[...clip.file].reduce((a,c)=>a+c.charCodeAt(0),0);
 return <SceneTransition clip={clip}><AbsoluteFill style={{background:'#111419',overflow:'hidden',...transitionStyle(f,clip,next)}}>
  <FootageMotionBlur enabled={d.motion_blur}>
  <Footage clip={clip} file={clip.file} offset={clip.source_in_frame} style={layout==='split'?{inset:'0 0 50% 0'}:{inset:0}}/>
  {layout!=='full'&&<Footage clip={clip} file={clip.secondary_file} offset={clip.secondary_source_in_frame}
   style={layout==='split'?{inset:'50% 0 0 0'}:{left:'54%',right:'7%',top:'12%',height:'29%',border:'3px solid #ffffffb0',borderRadius:20}}/>}
  </FootageMotionBlur>
  {d.lighting==='gradient'&&<AbsoluteFill style={{background:`linear-gradient(${120+f*.15}deg,#10152a77,transparent 55%,#9020d030)`}}/>}
  {d.lighting==='glow'&&<AbsoluteFill style={{background:`radial-gradient(ellipse at ${40+Math.sin(f/30)*10}% 25%,#ffffff30,transparent 65%)`,mixBlendMode:'screen'}}/>}
  {d.lighting==='sweep'&&<AbsoluteFill style={{background:'linear-gradient(110deg,transparent 40%,#ffffff2a 50%,transparent 60%)',translate:`${interpolate(f,[0,clip.frames],[-150,150],clamp)}% 0`,mixBlendMode:'screen'}}/>}
  {clip.transition==='light_sweep'&&f<n&&<AbsoluteFill style={{background:'linear-gradient(90deg,transparent,#fff9,transparent)',translate:`${interpolate(f,[0,n],[-100,100],ease)}% 0`,mixBlendMode:'screen'}}/>}
  {d.template==='blueprint'&&<AbsoluteFill style={{opacity:.16,backgroundImage:'linear-gradient(#b2dcff 1px,transparent 1px),linear-gradient(90deg,#b2dcff 1px,transparent 1px)',backgroundSize:'80px 80px',maskImage:'linear-gradient(black,transparent 75%)'}}/>}
  {d.template==='cinema'&&<><div style={{position:'absolute',top:0,width:'100%',height:65,background:'#000'}}/><div style={{position:'absolute',bottom:0,width:'100%',height:65,background:'#000'}}/></>}
  {d.object_3d&&<Object3D object={d.object_3d} top={objectTop}/>}
  <LottieOverlay asset={d.lottie_asset}/>
  {Array.from({length:d.particles},(_,i)=><div key={i} style={{position:'absolute',left:`${(seed+i*37)%100}%`,top:`${((seed+i*61)-f*(.2+i%3*.07)+10000)%100}%`,width:3+i%4,height:3+i%4,borderRadius:'50%',background:'#ffffff80',opacity:.25+.2*Math.sin((f+i*13)/20)}}/>)}
  {clip.title&&<div style={{position:'absolute',left:82,right:155,top:230,fontSize:titleSize,fontFamily:d.font_family==='serif'?'Sahne Serif, serif':'Sahne Sans, sans-serif',fontWeight:d.font_family==='serif'?700:800,lineHeight:1.16,textShadow:d.text_style==='extruded'?'1px 1px #1c2633,2px 2px #1c2633,3px 3px #1c2633,4px 4px #1c2633,0 5px 20px #000':'0 3px 16px #000',color:d.text_style==='accent'?'#D5AD72':d.text_style==='outline'?'transparent':'#F4F2ED',WebkitTextStroke:d.text_style==='outline'?'2px #F4F2ED':undefined,overflow:'hidden',overflowWrap:'anywhere',...(d.template==='glass'?{padding:32,background:'#102335bb',border:'1px solid #ffffff4d',borderRadius:20,backdropFilter:'blur(12px)'}:{}),...(d.template==='editorial'?{borderLeft:'6px solid #D5AD72',paddingLeft:28}:{}),...(d.template==='blueprint'?{borderTop:'2px solid #a8dbff',paddingTop:24,color:'#d7efff'}:{})}}>
   <TitleAnnotation kind={d.annotation} text={d.annotation_text}>{d.typography==='words'||d.typography==='characters'?(d.typography==='words'?clip.title.split(' '):[...clip.title]).map((text,i,items)=>{
    const delay=i*Math.min(2,Math.max(1,clip.frames*.4-8)/Math.max(1,items.length-1));
    return <span key={i} style={{display:'inline-block',whiteSpace:'pre',opacity:interpolate(f,[delay,delay+6],[0,1],clamp),translate:`0 ${interpolate(f,[delay,delay+8],[20,0],ease)}px`}}>{text}{d.typography==='words'?' ':''}</span>;
   }):
    <span style={{display:'block',...(d.typography==='typewriter'?{}:titleMotion(f,clip.frames,d.typography))}}>{d.typography==='typewriter'?clip.title.slice(0,Math.ceil(clip.title.length*unit(f/Math.min(45,clip.frames*.45)))):clip.title}</span>}</TitleAnnotation>
  </div>}
 </AbsoluteFill></SceneTransition>;
};
