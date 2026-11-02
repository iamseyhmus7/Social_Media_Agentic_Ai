import {createTikTokStyleCaptions} from '@remotion/captions';

export const captionPages=(words)=>{
 let characters=0,count=0;
 const normalized=words.map((word,index)=>{
  const text=word.text.trim();characters+=text.length+1;count++;
  const next=words[index+1];
  const pageBreakAfter=Boolean(word.pageBreakAfter||!next||next.startMs-word.endMs>=300||characters+(next?.text.trim().length||0)>48||count>=6);
  if(pageBreakAfter){characters=0;count=0;}
  // Remotion uses leading spaces to distinguish new words from continuations.
  return {...word,text:(index?' ':'')+text,pageBreakAfter};
 });
 return createTikTokStyleCaptions({captions:normalized,combineTokensWithinMilliseconds:700,breakOnSilenceAfterMilliseconds:300}).pages
  .map(page=>({...page,durationMs:Math.min(page.durationMs,Math.max(...page.tokens.map(t=>t.toMs))-page.startMs)}));
};
