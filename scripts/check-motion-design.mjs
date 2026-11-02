import assert from 'node:assert/strict';
import {cameraStyle,transitionStyle,titleMotion,cameras,transitions,typography} from '../remotion/production/motion-design.mjs';

for(const kind of cameras){
 for(const frame of [0,15,45,89,100]){
  const style=cameraStyle(frame,90,{kind,strength:.15});
  assert.ok(Number.isFinite(style.scale)&&style.scale>=1,kind);
  assert.ok(!JSON.stringify(style).match(/NaN|Infinity/),kind);
  assert.deepEqual(style,cameraStyle(frame,90,{kind,strength:.15}),`${kind}: frame seeking must be deterministic`);
 }
}
for(const kind of transitions){
 const clip={transition:kind,transition_frames:12,frames:90};
 const finish=transitionStyle(12,clip);
 assert.equal(finish.opacity,1,kind);
 assert.equal(finish.scale,1,kind);
 assert.equal(finish.clipPath,undefined,kind);
 assert.equal(finish.translate,'0px 0px',kind);
 const start=transitionStyle(0,clip);
 assert.ok(start.opacity>=0&&start.opacity<=1,kind);
 if(['iris','diagonal_wipe'].includes(kind))assert.ok(start.clipPath,kind);
 if(kind==='slide_up')assert.equal(start.translate,'0px 1920px');
 const outgoing=transitionStyle(102,{...clip,transition:'cut'},clip);
 if(kind==='slide_up')assert.equal(outgoing.translate,'0px -1920px');
}
for(const kind of typography){
 for(const frame of [0,6,12,30])assert.ok(!JSON.stringify(titleMotion(frame,90,kind)).match(/NaN|Infinity/),kind);
}
console.log('Frame determinism, transition boundaries and bounded camera motion passed.');
