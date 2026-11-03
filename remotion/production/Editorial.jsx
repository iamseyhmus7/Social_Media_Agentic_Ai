import React from 'react';
import {AbsoluteFill,OffthreadVideo,Sequence,Freeze,Img,staticFile,useCurrentFrame,useVideoConfig,interpolate,Easing} from './timeline.jsx';
const clamp={extrapolateLeft:'clamp',extrapolateRight:'clamp'};
const snap={...clamp,easing:Easing.bezier(.16,1,.3,1)};
const paper='#F1EDE3',black='#101216';
const Media=({clip,scale=1,position='50% 50%',offset=0})=>{
 const style={width:'100%',height:'100%',objectFit:'cover',objectPosition:position,transform:scale===1?undefined:`scale(${scale})`};
 return clip.kind==='clip'?<OffthreadVideo src={staticFile(clip.file)} muted trimBefore={offset} style={style}/>:<Img src={staticFile(clip.file)} style={style}/>;
};
const Coverage=({clip,index})=>{
 const f=useCurrentFrame();
 const cut=clip.punch_in&&f>=Math.round(clip.frames*.48);
 const scale=interpolate(f,[0,clip.frames],[cut?1.28:1.06,cut?1.19:1.12],clamp);
 return <AbsoluteFill style={{transform:`translateX(${interpolate(f,[0,clip.frames],index%2?[-14,14]:[14,-14],clamp)}px)`}}><Media clip={clip} scale={scale} position={index%2?'55% 45%':'45% 50%'}/></AbsoluteFill>;
};
const EditorialShot=({clip,next,index})=>{
 const f=useCurrentFrame();const n=clip.transition_frames||10;
 const incoming=['whip','push'].includes(clip.transition)?interpolate(f,[0,n],[1080,0],snap):0;
 const outgoing=next&&['whip','push'].includes(next.transition)?interpolate(f,[clip.frames,clip.frames+next.transition_frames],[0,-1080],snap):0;
 const edge=interpolate(f,[0,n],[118,0],snap);
 const opacity=clip.transition==='dissolve'?interpolate(f,[0,n],[0,1],clamp):1;
 return <AbsoluteFill style={{overflow:'hidden',background:black,opacity,transform:incoming+outgoing?`translateX(${incoming+outgoing}px)`:undefined,clipPath:clip.transition==='reveal'&&f<n?`polygon(${edge}% 0,100% 0,100% 100%,${Math.max(0,edge-18)}% 100%)`:undefined}}>
 {f>=clip.frames?<Freeze frame={clip.frames-1}><Coverage clip={clip} index={index}/></Freeze>:<Coverage clip={clip} index={index}/>}
 <AbsoluteFill style={{background:'linear-gradient(180deg,#0004,transparent 35%,transparent 60%,#0005)'}}/>
 {clip.transition==='whip'&&f<n&&<AbsoluteFill style={{opacity:interpolate(f,[0,n*.4,n],[0,.35,0],clamp),background:'repeating-linear-gradient(0deg,transparent 0px,transparent 65px,#f1ede380 66px,transparent 68px)'}}/>}
 </AbsoluteFill>;
};
const Rise=({text,frame,size=120,color=paper})=><span style={{display:'block',overflow:'hidden',paddingBottom:10}}><span style={{display:'block',fontSize:size,fontWeight:800,lineHeight:.99,overflowWrap:'anywhere',letterSpacing:-size*.045,color,transform:`translateY(${interpolate(frame,[0,14],[140,0],snap)}%)`}}>{text}</span></span>;
const Opening=({clips,teaser_shots,intro_beats,opening_title,color,duration_frames})=>{
 const f=useCurrentFrame();const pick=teaser_shots.map(id=>clips.find(c=>c.file.startsWith(id+'.')));
 const beat=f<21?0:f<40?1:2;const beatStart=[2,23,42][beat];const phrase=intro_beats[beat];
 return <AbsoluteFill style={{background:black}}>
 <Sequence from={0} durationInFrames={22}><AbsoluteFill><Media clip={pick[0]} offset={8} scale={interpolate(f,[0,22],[1.3,1.1],snap)}/></AbsoluteFill></Sequence>
 <Sequence from={18} durationInFrames={25}><AbsoluteFill style={{transform:`translateX(${interpolate(f,[18,28],[1080,0],snap)}px)`}}><div style={{position:'absolute',left:0,top:0,bottom:0,width:'61%',overflow:'hidden',borderRight:`8px solid ${paper}`}}><Media clip={pick[1]} offset={12} scale={1.12}/></div><div style={{position:'absolute',right:0,top:0,bottom:0,width:'39%',overflow:'hidden'}}><Media clip={pick[2]} offset={32} scale={1.3} position="70% 50%"/></div></AbsoluteFill></Sequence>
 <Sequence from={40} durationInFrames={24}><AbsoluteFill><Media clip={pick[2]} offset={4} scale={interpolate(f,[40,64],[1.2,1.05],snap)}/></AbsoluteFill></Sequence>
 <Sequence from={60} durationInFrames={80}><AbsoluteFill style={{overflow:'hidden',clipPath:`inset(${interpolate(f,[60,94],[210,0],snap)}px ${interpolate(f,[60,94],[170,0],snap)}px)`}}><Media clip={clips[0]} offset={35} scale={1.06}/></AbsoluteFill></Sequence>
 <AbsoluteFill style={{background:'linear-gradient(180deg,#0005,transparent 25%,#0005 80%)'}}/>
 <div style={{position:'absolute',left:72,top:100,fontSize:23,letterSpacing:5,fontWeight:600}}>KISA FİLM <span style={{color,marginLeft:20}}>{String(Math.round(duration_frames/30)).padStart(2,'0')} SANİYE</span></div>
 {f<61&&<div style={{position:'absolute',left:70,right:140,top:690,transform:`rotate(${beat===1?-3:0}deg)`}}><div style={{display:'inline-block',background:color,color:black,fontSize:22,fontWeight:800,padding:'9px 16px',letterSpacing:3,marginBottom:22}}>0{beat+1} / 03</div><Rise text={phrase.toLocaleUpperCase('tr-TR')} frame={f-beatStart} size={phrase.length>14?105:145}/><div style={{height:9,width:interpolate(f,[beatStart,beatStart+14],[0,260],snap),background:color,marginTop:20}}/></div>}
 {f>=62&&<div style={{position:'absolute',left:75,right:150,top:570}}><div style={{fontSize:22,letterSpacing:5,marginBottom:22,color}}>{intro_beats[2].toLocaleUpperCase('tr-TR')}</div><Rise text={opening_title} frame={f-64} size={104}/></div>}
 <div style={{position:'absolute',left:74,right:154,bottom:180,height:3,background:'#ffffff35'}}><div style={{height:'100%',width:`${Math.min(100,f/140*100)}%`,background:color}}/></div>
 </AbsoluteFill>;
};
const Chapter=({chapter,start,index,color})=>{
 const f=useCurrentFrame();const local=f-start;
 const opacity=interpolate(local,[0,7,43,57],[0,1,1,0],clamp);
 return <AbsoluteFill style={{opacity,background:'linear-gradient(90deg,#101216a8,transparent 95%)'}}>
 <div style={{position:'absolute',left:70,right:150,top:index%2?780:620}}>
 <div style={{display:'flex',alignItems:'center',gap:22,marginBottom:24}}><span style={{fontSize:100,fontWeight:800,lineHeight:1,color,letterSpacing:-7}}>{String(index+1).padStart(2,'0')}</span><span style={{height:2,background:paper,width:interpolate(local,[0,18],[0,200],snap)}}/></div>
 <Rise text={chapter.title.toLocaleUpperCase('tr-TR')} frame={local-3} size={88}/>
 <div style={{fontFamily:'DejaVu Serif,serif',fontStyle:'italic',fontSize:49,lineHeight:1.25,marginTop:26,transform:`translateX(${interpolate(local,[6,22],[50,0],snap)}px)`}}>{chapter.phrase}</div>
 </div>
 </AbsoluteFill>;
};
const Closing=({title,eyebrow,color,brand,duration_frames})=>{
 const f=useCurrentFrame();const local=f-(duration_frames-76);
 const words=title.split(' ');const last=words.pop();
 return <AbsoluteFill style={{background:'linear-gradient(180deg,transparent,#101216e6 70%)'}}>
 <div style={{position:'absolute',left:70,right:150,bottom:360}}><div style={{fontSize:24,letterSpacing:5,marginBottom:28,color}}>{eyebrow.toLocaleUpperCase('tr-TR')}</div><Rise text={words.join(' ')} frame={local} size={85}/><Rise text={last} frame={local-5} size={last.length>12?86:132} color={color}/><div style={{width:interpolate(local,[0,26],[0,310],snap),height:5,background:color,marginTop:30}}/>{brand&&<div style={{marginTop:35,fontSize:25,letterSpacing:4}}>{brand}</div>}</div>
 </AbsoluteFill>;
};
export const Editorial=(props)=>{
 const f=useCurrentFrame();const {fps}=useVideoConfig();
 const starts=props.chapters.map(c=>props.clips.find(s=>s.scene_index===c.scene_index)?.start_frame||0);
 return <AbsoluteFill style={{background:black,color:paper,fontFamily:'DejaVu Sans Condensed, DejaVu Sans, sans-serif'}}>
 {props.clips.map((clip,index)=>{const next=props.clips[index+1];return <Sequence key={clip.file} from={clip.start_frame} premountFor={fps} durationInFrames={Math.min(clip.frames+(next&&next.transition!=='cut'?next.transition_frames:0),props.duration_frames-clip.start_frame)}><EditorialShot clip={clip} next={next} index={index}/></Sequence>;})}
 {f<140&&<Opening {...props}/>}
 {props.chapters.map((chapter,index)=>{const start=index===0?160:starts[index];return f>=start&&f<start+58?<Chapter key={index} chapter={chapter} start={start} index={index} color={props.color}/>:null;})}
 {f>=props.duration_frames-76&&<Closing title={props.ending_title} eyebrow={props.chapters[props.chapters.length-1].title} color={props.color} brand={props.brand} duration_frames={props.duration_frames}/>}
 {f>=140&&f<props.duration_frames-76&&<><div style={{position:'absolute',top:85,left:72,right:150,display:'flex',justifyContent:'space-between',fontSize:21,fontWeight:600,letterSpacing:4,textShadow:'0 2px 4px #000'}}><span>{props.brand||props.opening_title}</span><span style={{color:props.color}}>{String(starts.filter(s=>s<=f).length).padStart(2,'0')} / {String(props.chapters.length).padStart(2,'0')}</span></div><div style={{position:'absolute',left:72,right:150,bottom:170,height:2,background:'#ffffff35'}}><div style={{height:'100%',width:`${f/props.duration_frames*100}%`,background:props.color}}/></div></>}
 </AbsoluteFill>;
};




