import React, {useMemo} from 'react';
import {Automatic} from './Automatic.jsx';
import {Editorial} from './Editorial.jsx';
import {AbsoluteFill,Composition,Sequence,Freeze,Img,OffthreadVideo,registerRoot,staticFile,useCurrentFrame,useVideoConfig,interpolate,spring,Easing} from './timeline.jsx';
import {createTikTokStyleCaptions} from '@remotion/captions';
const clamp={extrapolateLeft:'clamp',extrapolateRight:'clamp'};
const ease={...clamp,easing:Easing.inOut(Easing.cubic)};
const ink=(color)=>{const rgb=color.slice(1).match(/../g).map(v=>{const c=parseInt(v,16)/255;return c<=.04045?c/12.92:((c+.055)/1.055)**2.4;});return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722>.179?'#111419':'#F4F2ED';};
const Footage=({clip})=>{
 const frame=useCurrentFrame();const middle=Math.round(clip.frames*.5);
 const scale=clip.punch_in&&frame>=middle?interpolate(frame,[middle,middle+9],[1.12,1.1],clamp):1;
 const style={width:'100%',height:'100%',objectFit:'cover',transform:`scale(${scale})`};
 return <AbsoluteFill>{clip.kind==='clip'?<OffthreadVideo src={staticFile(clip.file)} muted style={style}/>:<Img src={staticFile(clip.file)} style={style}/>}</AbsoluteFill>;
};
const Shot=({clip,next,dynamic})=>{
 const frame=useCurrentFrame();const length=clip.transition_frames||7;
 const incoming=clip.transition==='push'?interpolate(frame,[0,length],[1080,0],ease):0;
 const outgoing=next?.transition==='push'?interpolate(frame,[clip.frames,clip.frames+(next.transition_frames||7)],[0,-1080],ease):0;
 const opacity=clip.transition==='dissolve'?interpolate(frame,[0,length],[0,1],clamp):1;
 return <AbsoluteFill style={{opacity,transform:`translateX(${incoming+outgoing}px)`,overflow:'hidden',background:'#111419'}}>
 {frame>=clip.frames?<Freeze frame={clip.frames-1}><Footage clip={clip}/></Freeze>:<Footage clip={clip}/>}
 <AbsoluteFill style={{background:'linear-gradient(180deg,rgba(0,0,0,.3),transparent 30%,transparent 58%,rgba(0,0,0,.55))'}}/>
 {!dynamic&&clip.title&&<div style={{position:'absolute',left:80,right:80,top:220,fontSize:56,fontWeight:700,lineHeight:1.15}}>{clip.title}</div>}</AbsoluteFill>;
};
const DynamicCaptions=({words,color})=>{
 const frame=useCurrentFrame();const {fps}=useVideoConfig();const ms=frame/fps*1000;
 const {pages}=useMemo(()=>createTikTokStyleCaptions({captions:words,combineTokensWithinMilliseconds:900,breakOnSilenceAfterMilliseconds:350}),[words]);
 const page=pages.find(p=>ms>=p.startMs&&ms<p.startMs+p.durationMs);if(!page)return null;
 const pop=spring({frame:frame-Math.round(page.startMs/1000*fps),fps,config:{damping:18,stiffness:260}});
 return <div style={{position:'absolute',bottom:300,left:80,right:155,textAlign:'center',fontSize:66,fontWeight:800,lineHeight:1.45,transform:`scale(${.94+.06*pop})`,textShadow:'0 3px 3px #000, 0 0 12px #000',overflowWrap:'anywhere'}}>{page.tokens.map((token,i)=>{
 const active=ms>=token.fromMs&&ms<token.toMs;
 return <React.Fragment key={i}>{i>0?' ':''}<span style={{display:'inline-block',padding:'0 9px',borderRadius:10,background:active?color:'transparent',color:active?ink(color):'#F4F2ED',textShadow:active?'none':undefined}}>{token.text.trim()}</span></React.Fragment>;
 })}</div>;
};
const ProductionContent=(props)=>{
 const frame=useCurrentFrame();const {fps}=useVideoConfig();const dynamic=props.style==='dynamic';
 const caption=props.captions.find(c=>frame>=Math.round(c.start*fps)&&frame<Math.round(c.end*fps));
 const reveal=spring({frame:frame-3,fps,config:{damping:20,stiffness:180}});
 const openingOpacity=interpolate(frame,[0,4,55,65],[0,1,1,0],clamp);
 if(props.style==='auto')return <Automatic {...props}/>;
 if(props.style==='editorial')return <Editorial {...props}/>;
 return <AbsoluteFill style={{background:'#111419',color:'#F4F2ED',fontFamily:'DejaVu Sans, sans-serif'}}>
 {props.clips.map((c,i)=>{const next=props.clips[i+1];return <Sequence key={c.file} from={c.start_frame} premountFor={fps} durationInFrames={Math.min(c.frames+(next&&next.transition!=='cut'?(next.transition_frames||7):0),props.duration_frames-c.start_frame)}><Shot clip={c} next={next} dynamic={dynamic}/></Sequence>;})}
 {props.logo&&<Img src={staticFile(props.logo)} style={{position:'absolute',top:88,left:80,width:100,height:100,objectFit:'contain'}}/>}
 {props.brand&&<div style={{position:'absolute',top:props.logo?205:88,left:80,fontSize:30,color:props.color,fontWeight:700}}>{props.brand}</div>}
 {dynamic&&props.opening_title&&frame<65&&<AbsoluteFill style={{opacity:openingOpacity,background:'linear-gradient(180deg,rgba(0,0,0,.42),transparent 70%)'}}><div style={{position:'absolute',left:84,right:156,top:350,fontSize:92,fontWeight:800,lineHeight:1.08,letterSpacing:-3,textShadow:'0 4px 16px #0009',transform:`translateY(${(1-reveal)*30}px)`}}>{props.opening_title}<div style={{width:100,height:8,background:props.color,marginTop:28}}/></div></AbsoluteFill>}
 {dynamic?<DynamicCaptions words={props.words} color={props.color}/>:caption&&<div style={{position:'absolute',bottom:270,left:80,right:80,textAlign:'center',fontSize:49,fontWeight:700,lineHeight:1.3,textShadow:'0 3px 8px #000',background:'rgba(17,20,25,.75)',borderRadius:16,padding:'18px 24px'}}>{caption.text}</div>}
 {dynamic&&props.ending_title&&frame>=props.duration_frames-42&&<div style={{position:'absolute',bottom:570,left:84,right:156,fontSize:48,fontWeight:700,lineHeight:1.2,textAlign:'center',textShadow:'0 3px 10px #000',opacity:interpolate(frame,[props.duration_frames-42,props.duration_frames-34],[0,1],clamp)}}>{props.ending_title}</div>}
 </AbsoluteFill>;
};
const defaults={duration_frames:900,clips:[],captions:[],words:[],style:'classic',brand:'',color:'#A98BFF'};
const Production=ProductionContent;
registerRoot(()=> <Composition id="SahneProduction" component={Production} width={1080} height={1920} fps={30} durationInFrames={900} defaultProps={defaults} calculateMetadata={({props})=>({fps:props.output_fps??30,durationInFrames:props.duration_frames*(props.output_fps??30)/30})}/>);


