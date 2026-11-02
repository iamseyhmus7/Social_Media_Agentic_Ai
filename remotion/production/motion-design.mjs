// Every value depends only on the requested frame. Safe for seeking and chunks.
export const cameras=['locked','push_in','pull_back','pan_left','pan_right','shake','tilt_up','tilt_down','roll_left','roll_right','snap_zoom','arc'];
export const transitions=['cut','dissolve','push','reveal','whip','zoom','light_sweep','iris','diagonal_wipe','blur_dissolve','zoom_out','slide_up'];
export const typography=['rise','words','characters','mask','blur_in','elastic','typewriter','flip','tracking'];
export const templates=['none','editorial','glass','blueprint','cinema'];
export const objects3d=['cube','sphere','torus','icosahedron'];
export const unit=(v)=>Math.max(0,Math.min(1,v));
const smooth=(v)=>{const p=unit(v);return 1-(1-p)**3;};

export function cameraStyle(frame,frames,camera={kind:'locked',strength:.04},punchIn=false){
 const p=unit(frame/Math.max(1,frames-1)),a=camera.strength;
 let scale=1,x=0,y=0,angle=0;
 if(camera.kind==='push_in')scale=1+a*p;
 if(camera.kind==='pull_back')scale=1+a*(1-p);
 if(['pan_left','pan_right'].includes(camera.kind)){scale=1+a;x=(camera.kind==='pan_left'?-1:1)*(p-.5)*a*100;}
 if(['tilt_up','tilt_down'].includes(camera.kind)){scale=1+a;y=(camera.kind==='tilt_up'?-1:1)*(p-.5)*a*100;}
 if(['roll_left','roll_right'].includes(camera.kind)){scale=1+a*1.8;angle=(camera.kind==='roll_left'?-1:1)*(p-.5)*a*60;}
 if(camera.kind==='shake'){scale=1+a;x=Math.sin(frame*.7)*a*5;y=Math.cos(frame*.93)*a*5;}
 if(camera.kind==='snap_zoom')scale=1+a*smooth((p-.32)/.12);
 if(camera.kind==='arc'){scale=1+a*1.8;x=Math.sin(p*Math.PI)*a*22;y=Math.cos(p*Math.PI)*a*12;angle=Math.sin(p*Math.PI)*a*15;}
 if(punchIn&&frame>=frames/2)scale+=.06;
 return {scale,translate:`${x}% ${y}%`,rotate:`${angle}deg`};
}

export function transitionStyle(frame,clip,next){
 const n=clip.transition_frames,p=smooth(frame/n),t=clip.transition;
 const out=next?smooth((frame-clip.frames)/next.transition_frames):0;
 const x=(['push','whip'].includes(t)?1080*(1-p):0)-(['push','whip'].includes(next?.transition)?1080*out:0);
 const y=(t==='slide_up'?1920*(1-p):0)-(next?.transition==='slide_up'?1920*out:0);
 const fading=['dissolve','blur_dissolve','zoom_out'].includes(t);
 const blur=t==='whip'?8*(1-p):t==='blur_dissolve'?18*(1-p):0;
 let clipPath;
 if(frame<n){
  if(['reveal','light_sweep'].includes(t))clipPath=`inset(0 0 0 ${100*(1-p)}%)`;
  if(t==='iris')clipPath=`circle(${150*p}% at 50% 50%)`;
  if(t==='diagonal_wipe')clipPath=`polygon(0 0, ${200*p}% 0, 0 ${200*p}%)`;
 }
 return {opacity:fading?p:1,translate:`${x}px ${y}px`,filter:blur?`blur(${blur}px)`:undefined,
  scale:t==='zoom'?1+.18*(1-p):t==='zoom_out'?.82+.18*p:1,clipPath};
}

export function titleMotion(frame,frames,kind){
 const length=Math.min(24,Math.max(6,frames*.35)),p=unit(frame/length),e=smooth(p);
 if(kind==='blur_in')return {opacity:e,filter:`blur(${14*(1-e)}px)`,translate:`0 ${18*(1-e)}px`};
 if(kind==='elastic')return {opacity:unit(p*5),scale:.78+.22*(1-Math.exp(-6*p)*Math.cos(10*p))};
 if(kind==='flip')return {opacity:e,transform:`perspective(900px) rotateX(${75*(1-e)}deg)`,transformOrigin:'50% 100%'};
 if(kind==='tracking')return {opacity:e,letterSpacing:`${12*(1-e)-1}px`};
 if(kind==='mask')return {clipPath:`inset(0 ${100*(1-e)}% 0 0)`};
 return {translate:`0 ${70*(1-e)}px`,opacity:e};
}
