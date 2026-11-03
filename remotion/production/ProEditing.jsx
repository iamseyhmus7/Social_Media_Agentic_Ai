import React,{useMemo} from 'react';
import {Video} from '@remotion/media';
import {contrast} from '@remotion/effects/contrast';
import {saturation} from '@remotion/effects/saturation';
import {glow} from '@remotion/effects/glow';
import {vignette} from '@remotion/effects/vignette';
import {CameraMotionBlur} from '@remotion/motion-blur';
import {Lottie} from '@remotion/lottie';
import {Underline,Circle,Highlight} from '@remotion/rough-notation';
import {wipe} from '@remotion/transitions/wipe';
import {flip} from '@remotion/transitions/flip';
import {clockWipe} from '@remotion/transitions/clock-wipe';
import {useVideoConfig as useOutputConfig} from 'remotion';
import {OffthreadVideo,useCurrentFrame,staticFile} from './timeline.jsx';
import {lottieAssets} from './lottie-assets.mjs';

export const SceneTransition=({clip,children})=>{
 const frame=useCurrentFrame();const {fps}=useOutputConfig();
 const presentation=useMemo(()=>({wipe:()=>wipe({direction:'from-left'}),flip:()=>flip({direction:'from-left'}),clock_wipe:()=>clockWipe({width:1080,height:1920})}[clip.transition]?.()),[clip.transition]);
 if(!presentation)return children;
 const Presentation=presentation.component;
 return <Presentation presentationDirection="entering" presentationProgress={Math.max(0,Math.min(1,frame/clip.transition_frames))}
  presentationDurationInFrames={Math.round(clip.transition_frames*fps/30)} passedProps={presentation.props}>{children}</Presentation>;
};

export const EffectFootage=({file,offset,design,style})=>{
 const {fps}=useOutputConfig();const strength=design.effect_strength??.35;
 const effects=useMemo(()=>[...new Set(design.effects||[])].flatMap(effect=>{
  if(effect==='color_grade')return [contrast({amount:1+.14*strength}),saturation({amount:1+.12*strength})];
  if(effect==='glow')return [glow({radius:12,intensity:.3*strength,threshold:.75})];
  if(effect==='vignette')return [vignette({amount:.45*strength})];
  return [];
 }),[design.effects,strength]);
 if(!effects.length)return <OffthreadVideo src={staticFile(file)} trimBefore={offset} muted style={style}/>;
 return <Video src={staticFile(file)} trimBefore={Math.round(offset*fps/30)} muted style={style} effects={effects} effectsOutputSize={{width:1080,height:1920}}/>;
};

// Only footage is sampled; titles and subtitles remain sharp and readable.
export const FootageMotionBlur=({enabled,children})=>enabled?<CameraMotionBlur samples={4} shutterAngle={120}>{children}</CameraMotionBlur>:children;

export const TitleAnnotation=({kind='none',text='',children})=>{
 const frame=useCurrentFrame();const Annotation={underline:Underline,circle:Circle,highlight:Highlight}[kind];
 if(!Annotation)return children;
 // The library treats its tracked text as nowrap. Annotate one word inside
 // the animated title, rather than wrapping its whole multiline block.
 let marked=false;
 const annotate=node=>{
  if(typeof node==='string'&&!marked&&node.trim()){
   let match;
   if(text){
    const index=node.indexOf(text);
    if(index<0)return node;
    match=[node,node.slice(0,index),text,node.slice(index+text.length)];
   }else match=node.match(/^(\s*)(\S+)([\s\S]*)$/);
   marked=true;
   return <>{match[1]}<Annotation progress={Math.max(0,Math.min(1,(frame-5)/18))} seed={17}
    {...(kind==='highlight'?{}:{strokeWidth:4})}
    color={kind==='highlight'?'rgba(213,173,114,.36)':'#D5AD72'}>{match[2]}</Annotation>{match[3]}</>;
  }
  if(React.isValidElement(node)&&node.props.children!==undefined)return React.cloneElement(node,{},React.Children.map(node.props.children,annotate));
  return node;
 };
 return React.Children.map(children,annotate);
};

export const LottieOverlay=({asset='none'})=>{
 const animationData=lottieAssets[asset];
 if(!animationData)return null;
 return <Lottie animationData={animationData} loop renderer="svg" style={{position:'absolute',left:380,top:670,width:320,height:320,pointerEvents:'none'}}/>;
};
