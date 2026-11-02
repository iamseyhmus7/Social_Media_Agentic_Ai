import React from 'react';
import {AbsoluteFill,interpolate,useCurrentFrame,Easing} from 'remotion';
import geography from './geography.mjs';

const clamp={extrapolateLeft:'clamp',extrapolateRight:'clamp'};
const paths=(geometry)=>{
 const rings=geometry.type==='MultiPolygon'?geometry.coordinates.flat():geometry.type==='Polygon'?geometry.coordinates:geometry.type==='MultiLineString'?geometry.coordinates:[geometry.coordinates];
 return rings.map(ring=>ring.map(([x,y],i)=>`${i?'L':'M'}${x},${-y}`).join(' ')+(geometry.type.includes('Polygon')?'Z':'')).join(' ');
};
const countries=geography.countries.map(c=>({...c,path:paths(c)}));
const rivers=geography.rivers.map(paths);

// Local, deterministic geographic vectors. Perspective is a 3D CSS camera;
// no external tiles, WebGL context, access token or historical origin claim.
export const MapFlyover=({cue,palette})=>{
 const f=useCurrentFrame(),n=cue.frames,l=cue.location;
 const travel=interpolate(f,[5,n*.76],[0,1],{...clamp,easing:Easing.bezier(.62,0,.18,1)});
 const zoom=Math.exp(Math.log(3.7)+(Math.log(70)-Math.log(3.7))*travel);
 const cx=l.longitude-15*(1-travel),cy=-l.latitude+12*(1-travel);
 const px=540+(l.longitude-cx)*zoom,py=920+(-l.latitude-cy)*zoom;
 const exit=interpolate(f,[n-16,n-1],[1,0],clamp);
 const marker=interpolate(travel,[.40,.74],[0,1],clamp);
 const fade=interpolate(f,[0,8],[0,1],clamp);
 return <AbsoluteFill style={{background:'#071b23',opacity:exit,overflow:'hidden'}}>
  <AbsoluteFill style={{perspective:1700,perspectiveOrigin:'50% 48%'}}>
   <AbsoluteFill style={{transform:`rotateX(${28*(1-travel)}deg) rotateZ(${-12*(1-travel)}deg) translateZ(${80*travel}px)`,transformOrigin:'50% 48%'}}>
    <svg width="1080" height="1920" viewBox="0 0 1080 1920" style={{position:'absolute',inset:0}}>
     <defs><radialGradient id="atlas-sea"><stop stopColor="#21464b"/><stop offset="1" stopColor="#071b23"/></radialGradient><pattern id="atlas-dots" width="28" height="28" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r=".6" fill="#d8ba8140"/></pattern></defs>
     <rect width="1080" height="1920" fill="url(#atlas-sea)"/>
     <rect width="1080" height="1920" fill="url(#atlas-dots)"/>
     <g transform={`translate(540 920) scale(${zoom}) translate(${-cx} ${-cy})`}>
      {countries.map(c=><path key={'depth'+c.code} d={c.path} transform={`translate(0 ${4/zoom})`} fill="#030e13"/>)}
      {countries.map(c=><path key={c.code} d={c.path} fill={c.code===l.country_code?'#cfb486':'#617575'} stroke="#a8bbb455" strokeWidth={.7/zoom} strokeLinejoin="round"/>)}
      {rivers.map((d,i)=><path key={i} d={d} fill="none" stroke="#79c4cc" strokeWidth={1.8/zoom} opacity=".8"/>)}
     </g>
     <g opacity={marker}>
      <circle cx={px} cy={py} r={38-16*travel} fill="none" stroke={palette.accent} strokeWidth="1.5"/>
      <circle cx={px} cy={py} r="8" fill="#fff0c8"/>
      <path d={`M${px} ${py+28}v85h145`} fill="none" stroke={palette.accent} strokeWidth="2"/>
     </g>
    </svg>
   </AbsoluteFill>
  </AbsoluteFill>
  <AbsoluteFill style={{background:'linear-gradient(180deg,#06171ff0 0%,#06171f55 30%,transparent 48%,#06171f22 62%,#06171fee 91%)'}}/>
  <div style={{position:'absolute',left:82,right:120,top:205,opacity:fade}}>
   <div style={{fontSize:22,letterSpacing:7,color:palette.accent,fontWeight:700,marginBottom:34}}>TARİHİN İZİNDE</div>
   <div style={{fontSize:88,lineHeight:1.03,letterSpacing:-4,fontWeight:700,color:'#f5f0e5',maxWidth:850}}>{cue.title}</div>
  </div>
  <div style={{position:'absolute',left:82,right:120,top:1210,opacity:marker,translate:`0 ${22*(1-marker)}px`}}>
   <div style={{width:52,height:3,background:palette.accent,marginBottom:24}}/>
   <div style={{fontSize:70,letterSpacing:-2,fontWeight:700,color:'#f5f0e5'}}>{l.label}</div>
   <div style={{fontSize:25,letterSpacing:5,color:palette.accent,marginTop:12}}>{l.country.toLocaleUpperCase('tr-TR')}</div>
  </div>
 </AbsoluteFill>;
};
