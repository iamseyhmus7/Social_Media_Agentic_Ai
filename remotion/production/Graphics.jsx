import React from 'react';
import {AbsoluteFill,Sequence,interpolate,spring,useCurrentFrame,useVideoConfig} from 'remotion';
import {MapFlyover} from './MapFlyover.jsx';

const clamp={extrapolateLeft:'clamp',extrapolateRight:'clamp'};
const safe={position:'absolute',left:80,right:155};
const serif='Sahne Sans, sans-serif';

const Graphic=({cue,palette,sources})=>{
 const frame=useCurrentFrame();const {fps}=useVideoConfig();
 const enter=spring({frame,fps,config:{damping:22,stiffness:150},durationInFrames:Math.min(20,cue.frames)});
 const opacity=interpolate(frame,[0,5,cue.frames-6,cue.frames-1],[0,1,1,0],clamp);
 const common={color:palette.text,opacity};
 if(cue.kind==='map_flyover')return <MapFlyover cue={cue} palette={palette}/>;
 if(cue.kind==='spotlight'){
  const r=cue.region;
  return <AbsoluteFill style={common}>
   <div style={{position:'absolute',left:`${(r.x-r.width/2)*100}%`,top:`${(r.y-r.height/2)*100}%`,width:`${r.width*100}%`,height:`${r.height*100}%`,border:`5px solid ${palette.accent}`,borderRadius:'50%',boxShadow:'0 0 0 2500px rgba(5,12,20,.48)',scale:.92+.08*enter}}/>
   <div style={{...safe,top:200,fontSize:48,fontWeight:700,textShadow:'0 3px 14px #000'}}>{cue.title}</div>
  </AbsoluteFill>;
 }
 if(cue.kind==='kinetic_text'){
  return <div style={{...safe,...common,top:280,translate:`0 ${(1-enter)*40}px`,textShadow:'0 4px 28px #0008'}}>
   <div style={{width:56,height:4,background:palette.accent,marginBottom:28}}/>
   <div style={{fontFamily:serif,fontSize:cue.title.length>45?76:104,letterSpacing:-3,fontWeight:700,lineHeight:1.02,overflowWrap:'break-word'}}>{cue.title}</div>
   {cue.detail&&<div style={{fontSize:34,lineHeight:1.35,marginTop:30,maxWidth:740,color:'#eee8dc'}}>{cue.detail}</div>}
  </div>;
 }
 if(cue.kind==='timeline'){
  const first=cue.events[0].year,last=cue.events.at(-1).year;
  const progress=interpolate(frame,[8,Math.min(cue.frames-8,2*fps)],[0,1],clamp);
  if(cue.events.length===2)return <div style={{...safe,...common,top:370,padding:'44px 30px',background:'linear-gradient(135deg,#06151cf2,#06151cdc)',translate:`0 ${(1-enter)*35}px`}}>
   <div style={{fontSize:23,letterSpacing:5,color:palette.accent,fontWeight:700,marginBottom:32}}>TARİHLER KONUŞUYOR</div>
   <div style={{fontSize:55,letterSpacing:-2,lineHeight:1.08,fontWeight:700,marginBottom:66}}>{cue.title}</div>
   <div style={{display:'flex',justifyContent:'space-between',gap:35}}>{cue.events.map((event,i)=><div key={event.year} style={{flex:1,opacity:interpolate(frame,[8+i*20,22+i*20],[0,1],clamp)}}>
    <div style={{fontSize:128,fontWeight:700,letterSpacing:-7,color:i?palette.text:palette.accent,lineHeight:1}}>{event.year}</div>
    <div style={{fontSize:27,lineHeight:1.3,marginTop:22,maxWidth:330}}>{event.label}</div>
   </div>)}</div>
   <div style={{height:2,background:'#ffffff35',marginTop:46}}><div style={{width:`${progress*100}%`,height:2,background:palette.accent}}/></div>
   <div style={{fontSize:150,fontWeight:700,letterSpacing:-6,color:palette.accent,marginTop:42,opacity:interpolate(progress,[.35,.7],[0,1],clamp)}}>{last-first}<span style={{fontSize:52,letterSpacing:-1,marginLeft:18}}>yıl önce</span></div>
   {cue.detail&&<div style={{fontSize:31,lineHeight:1.4,maxWidth:700}}>{cue.detail}</div>}
  </div>;
  const eventsHeight=cue.events.length>2?500:340;
  return <div style={{...safe,...common,top:275,padding:'42px 40px',background:palette.background,borderLeft:`6px solid ${palette.accent}`,translate:`0 ${(1-enter)*25}px`}}>
   {cue.title&&<div style={{fontSize:46,lineHeight:1.18,fontWeight:700,marginBottom:34}}>{cue.title}</div>}
   <div style={{position:'relative',height:eventsHeight,marginLeft:18}}>
    <div style={{position:'absolute',left:5,top:26,width:3,height:eventsHeight-80,background:palette.text,opacity:.2}}/>
    <div style={{position:'absolute',left:5,top:26,width:3,height:(eventsHeight-80)*progress,background:palette.accent}}/>
    {cue.events.map((event,i)=>{
     const fraction=(event.year-first)/(last-first);const y=fraction*(eventsHeight-100);
     return <div key={event.year} style={{position:'absolute',left:0,right:0,top:y,opacity:interpolate(progress,[Math.max(0,fraction-.1),Math.max(.1,fraction)],[0,1],clamp)}}>
      <div style={{position:'absolute',top:23,left:-4,width:22,height:22,borderRadius:'50%',background:palette.accent}}/>
      <div style={{marginLeft:44,fontFamily:serif,fontSize:66,lineHeight:1.1,color:palette.accent}}>{event.year<0?`MÖ ${Math.abs(event.year)}`:event.year}</div>
      <div style={{marginLeft:44,fontSize:32,lineHeight:1.25,marginTop:6}}>{event.label}</div>
     </div>;
    })}
   </div>
   <div style={{fontFamily:serif,fontSize:92,lineHeight:1.1,color:palette.accent,marginTop:20,opacity:interpolate(progress,[.3,.6],[0,1],clamp)}}>{last-first} yıl</div>
   <div style={{fontSize:34,marginTop:12,lineHeight:1.35}}>{cue.detail||'İki tarih arasındaki fark'}</div>
  </div>;
 }
 const chosen=sources.filter(source=>cue.source_ids.includes(source.id));
 return <div style={{...safe,...common,top:270,background:palette.background,padding:'42px 40px',borderTop:`5px solid ${palette.accent}`,translate:`0 ${(1-enter)*25}px`}}>
  <div style={{fontFamily:serif,fontSize:54,lineHeight:1.15,marginBottom:28}}>{cue.title||'Kaynaklar'}</div>
  {cue.detail&&<div style={{fontSize:36,lineHeight:1.4,marginBottom:30}}>{cue.detail}</div>}
  {chosen.map(source=><div key={source.id} style={{fontSize:34,lineHeight:1.35,padding:'16px 0',borderTop:'1px solid #ffffff35',overflowWrap:'anywhere'}}>{source.label}</div>)}
 </div>;
};

export const Graphics=({graphics=[],palette,sources=[]})=>{
 const {fps}=useVideoConfig();
 return <>{graphics.map((cue,index)=><Sequence key={index} name={cue.kind} from={cue.start_frame} durationInFrames={cue.frames} premountFor={fps}><Graphic cue={cue} palette={palette} sources={sources}/></Sequence>)}</>;
};
