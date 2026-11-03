export function outputClock(manifest){
 const fps=manifest.output_fps??30;
 if(![30,60].includes(fps))throw new Error('Output FPS must be 30 or 60');
 const ratio=fps/30;
 return {fps,ratio,frame:tick=>Math.round(tick*ratio),
  range:(start,end)=>[Math.round(start*ratio),Math.round((end+1)*ratio)-1]};
}
