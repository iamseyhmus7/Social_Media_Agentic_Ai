import React,{useEffect,useState} from 'react';
import {Graphics} from './Graphics.jsx';
import {AutoCaptions} from './AutoCaptions.jsx';
import {DirectedSegment} from './SceneDesign.jsx';
import fontFaces from './typography-fonts.mjs';
import serifFont from './serif-font.mjs';
import {AbsoluteFill,Sequence,Freeze,OffthreadVideo,Img,staticFile,useCurrentFrame,useVideoConfig,interpolate,Easing,delayRender,continueRender,cancelRender} from 'remotion';
const clamp={extrapolateLeft:'clamp',extrapolateRight:'clamp'};
const eased={...clamp,easing:Easing.bezier(.16,1,.3,1)};
const Source=({clip})=>{
 const f=useCurrentFrame();
 return <OffthreadVideo src={staticFile(clip.file)} muted trimBefore={clip.source_in_frame||0} style={{width:'100%',height:'100%',objectFit:'cover',scale:clip.punch_in&&f>=Math.round(clip.frames*.5)?'1.08':'1'}}/>;
};
const Segment=({clip,next})=>{
 const f=useCurrentFrame(),n=clip.transition_frames;
 const incoming=['push','whip'].includes(clip.transition)?interpolate(f,[0,n],[1080,0],eased):0;
 const outgoing=next&&['push','whip'].includes(next.transition)?interpolate(f,[clip.frames,clip.frames+next.transition_frames],[0,-1080],eased):0;
 const edge=interpolate(f,[0,n],[100,0],eased);
 const blur=clip.transition==='whip'?interpolate(f,[0,n],[8,0],clamp):0;
 return <AbsoluteFill style={{overflow:'hidden',translate:`${incoming+outgoing}px 0`,filter:blur?`blur(${blur}px)`:undefined,opacity:clip.transition==='dissolve'?interpolate(f,[0,n],[0,1],clamp):1,clipPath:clip.transition==='reveal'&&f<n?`inset(0 0 0 ${edge}%)`:undefined}}>
 {f>=clip.frames?<Freeze frame={clip.frames-1}><Source clip={clip}/></Freeze>:<Source clip={clip}/>}
 {clip.title&&<div style={{position:'absolute',left:80,right:155,top:220,fontSize:50,fontWeight:700,textShadow:'0 3px 12px #000'}}>{clip.title}</div>}
 </AbsoluteFill>;
};
export const Automatic=(props)=>{
 const frame=useCurrentFrame();const {fps}=useVideoConfig();
 const [fontHandle]=useState(()=>delayRender('Yerel yazı tipleri yükleniyor'));
 useEffect(()=>{Promise.all([document.fonts.load('700 64px "Sahne Sans"','İıŞşĞğÜüÖöÇçABC'),document.fonts.load('700 64px "Sahne Serif"','İıŞşĞğÜüÖöÇçABC')]).then(()=>continueRender(fontHandle)).catch(cancelRender);},[fontHandle]);
 const palette=props.palette||{background:'#132434',accent:'#D5AD72',text:'#F5F0E5'};
 const activeGraphic=(props.graphics||[]).some(c=>frame>=c.start_frame&&frame<c.start_frame+c.frames);
 const ending=!!props.ending_title&&frame>=props.duration_frames-2.8*fps;
 return <AbsoluteFill style={{background:'#111419',color:'#F4F2ED',fontFamily:'Sahne Sans, sans-serif'}}>
 <style>{fontFaces+serifFont}</style>
 {props.clips.map((clip,index)=>{const next=props.clips[index+1],Component=props.version>=2?DirectedSegment:Segment;return <Sequence key={`${index}-${clip.file}`} name={`Çekim ${index+1}`} from={clip.start_frame} durationInFrames={Math.min(clip.frames+(props.version>=2?clip.handle_frames:(next&&next.transition!=='cut'?next.transition_frames:0)),props.duration_frames-clip.start_frame)} premountFor={fps}><Component clip={activeGraphic?{...clip,title:''}:clip} next={next}/></Sequence>;})}
 <AbsoluteFill style={{background:'linear-gradient(180deg,#03131b70,transparent 34%,transparent 50%,#03131bad 85%)'}}/>
 {ending&&<AbsoluteFill style={{background:'#06151c',opacity:interpolate(frame,[props.duration_frames-2.8*fps,props.duration_frames-1.8*fps],[0,.76],clamp)}}/>}
 <Graphics graphics={props.graphics} palette={palette} sources={props.sources}/>
 {props.logo&&<Img src={staticFile(props.logo)} style={{position:'absolute',right:150,top:85,width:80,height:80,objectFit:'contain'}}/>}
 {props.brand&&<div style={{position:'absolute',right:150,top:props.logo?175:85,fontSize:25,fontWeight:700,color:palette.text}}>{props.brand}</div>}
 {!activeGraphic&&props.opening_title&&frame<2*fps&&<div style={{position:'absolute',left:82,right:120,top:270,fontSize:94,letterSpacing:-3,fontWeight:700,lineHeight:1.03,opacity:interpolate(frame,[0,7,1.6*fps,2*fps],[0,1,1,0],clamp),textShadow:'0 4px 28px #0008'}}>{props.opening_title}</div>}
 {!activeGraphic&&props.ending_title&&ending&&<div style={{position:'absolute',left:82,right:120,top:930,opacity:interpolate(frame,[props.duration_frames-2.8*fps,props.duration_frames-2.3*fps],[0,1],clamp),translate:`0 ${interpolate(frame,[props.duration_frames-2.8*fps,props.duration_frames-2.3*fps],[25,0],clamp)}px`}}><div style={{width:56,height:4,background:palette.accent,marginBottom:36}}/><div style={{fontSize:82,letterSpacing:-3,lineHeight:1.07,fontWeight:700}}>{props.ending_title}</div></div>}
 {(props.version<2||props.captions_enabled!==false)&&<AutoCaptions words={props.words} captions={props.captions} accent={palette.accent} size={props.version>=2?props.caption_size:47}/>}
 </AbsoluteFill>;
};
