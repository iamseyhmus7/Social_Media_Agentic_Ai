import React,{useMemo} from 'react';
import {useCurrentFrame,useVideoConfig} from './timeline.jsx';
import {captionPages} from './caption-pages.mjs';

export const AutoCaptions=({words=[],captions=[],accent,size=47})=>{
 const frame=useCurrentFrame();const {fps}=useVideoConfig();const ms=frame/fps*1000;
 // These words belong to original-speed narration, independently of footage trims.
 const pages=useMemo(()=>captionPages(words),[words]);
 const page=pages.find(p=>ms>=p.startMs&&ms<p.startMs+p.durationMs);
 const fallback=!words.length&&captions.find(c=>ms>=c.start*1000&&ms<c.end*1000);
 if(!page&&!fallback)return null;
 return <div data-caption="auto" style={{position:'absolute',left:82,right:120,bottom:265,textAlign:'center',fontSize:size,fontWeight:700,letterSpacing:-.6,lineHeight:1.28,color:'#F5F0E5',textShadow:'0 2px 4px #000,0 4px 22px #000d',padding:'15px 10px',overflowWrap:'break-word'}}>
  {page?page.tokens.map((token,index)=><React.Fragment key={index}>{index>0?' ':''}<span style={{color:ms>=token.fromMs&&ms<token.toMs?accent:'#F5F0E5'}}>{token.text.trim()}</span></React.Fragment>):fallback.text}
 </div>;
};
