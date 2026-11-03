import React from 'react';
import * as Remotion from 'remotion';
export * from 'remotion';

// The editor's contract stays in 30-fps ticks. The output clock may run at 60
// fps: fractional ticks animate smoothly without retiming narration or media.
export const useCurrentFrame=()=>Remotion.useCurrentFrame()*30/Remotion.useVideoConfig().fps;
export const useVideoConfig=()=>{const config=Remotion.useVideoConfig();return {...config,fps:30,durationInFrames:config.durationInFrames*30/config.fps};};
export const Sequence=({from=0,durationInFrames,premountFor,postmountFor,...props})=>{
 const ratio=Remotion.useVideoConfig().fps/30;
 const scaled=v=>v===undefined?undefined:Math.round(v*ratio);
 return <Remotion.Sequence {...props} from={scaled(from)} durationInFrames={scaled(durationInFrames)} premountFor={scaled(premountFor)} postmountFor={scaled(postmountFor)}/>;
};
export const Freeze=({frame,...props})=><Remotion.Freeze {...props} frame={Math.round(frame*Remotion.useVideoConfig().fps/30)}/>;
export const OffthreadVideo=({trimBefore,trimAfter,...props})=>{
 const ratio=Remotion.useVideoConfig().fps/30;
 return <Remotion.OffthreadVideo {...props} trimBefore={trimBefore===undefined?undefined:Math.round(trimBefore*ratio)} trimAfter={trimAfter===undefined?undefined:Math.round(trimAfter*ratio)}/>;
};
