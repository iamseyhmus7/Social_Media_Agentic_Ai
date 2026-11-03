import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import crypto from 'node:crypto';
import os from 'node:os';
import {prepareBundle} from './bundle-cache.mjs';
import {outputClock} from './output-clock.mjs';
import {openBrowser,selectComposition,renderMedia,renderFrames,makeCancelSignal} from '@remotion/renderer';
const [manifestArg,publicDirArg,outputArg,browserExecutable,profile='final',concurrencyArg='2'] = process.argv.slice(2);
const manifest=path.resolve(manifestArg),publicDir=path.resolve(publicDirArg),outputLocation=path.resolve(outputArg);
const inputProps=JSON.parse(fs.readFileSync(manifest,'utf8'));
const clock=outputClock(inputProps);
const root=path.dirname(fileURLToPath(import.meta.url));
// Remotion locates its installed browser relative to the package working
// directory. The Python worker launches us from a private per-run media folder.
process.chdir(root);
const started=performance.now();
const metricsPath=path.join(path.dirname(outputLocation),profile==='preview'?'preview-metrics.json':'render-metrics.json');
const concurrency=Number(concurrencyArg);
if(!Number.isInteger(concurrency)||concurrency<1||concurrency>4)throw new Error('Invalid render concurrency');
const metrics={mode:browserExecutable?'chrome-for-testing':'headless-shell',concurrency,rendered_frames:0,encoded_frames:0};
const saveMetrics=()=>{
  metrics.total_seconds=Number(((performance.now()-started)/1000).toFixed(3));
  fs.writeFileSync(metricsPath+'.tmp',JSON.stringify(metrics,null,2));
  fs.renameSync(metricsPath+'.tmp',metricsPath);
};
const timed=async(name,fn)=>{const start=performance.now();const result=await fn();metrics[name+'_seconds']=Number(((performance.now()-start)/1000).toFixed(3));saveMetrics();console.log(`${name}: ${metrics[name+'_seconds']}s`);return result;};
const {cancelSignal,cancel}=makeCancelSignal();
let cancelled=false,bundler;
const stop=()=>{cancelled=true;metrics.cancelled=true;saveMetrics();bundler?.kill('SIGTERM');cancel();};
process.once('SIGTERM',stop);
process.once('SIGINT',stop);
let browser;
const scratch=fs.mkdtempSync(path.join(os.tmpdir(),'sahne-render-'));
const renderOutputLocation=path.join(scratch,path.basename(outputLocation));
try {
  // Webpack can retain a large heap after compilation. Exit its process before
  // Chromium starts so rendering does not compete with the compiler's memory.
  const serveUrl=path.join(scratch,'bundle');
  metrics.private_linux_scratch=true;
  Object.assign(metrics,await timed('bundle',()=>prepareBundle({root,publicDir,serveUrl,onChild:child=>{bundler=child;},check:()=>{if(cancelled)throw new Error('Render cancelled');}})));
  if(cancelled)throw new Error('Render cancelled');
  // WebGL is enabled only for requested 3D geometry; ordinary videos keep the
  // existing 2D rendering path and its resource profile.
  const uses3d=inputProps.clips?.some(clip=>clip.design?.object_3d);
  const usesEffects=inputProps.clips?.some(clip=>clip.design?.effects?.length);
  metrics.uses_3d=!!uses3d;
  metrics.uses_effects=!!usesEffects;
  const gl=process.platform==='linux'?'swangle':'angle';
  if(uses3d||usesEffects)metrics.webgl_backend=gl;
  const launchOptions={browserExecutable:browserExecutable||undefined,chromeMode:metrics.mode,chromiumOptions:{enableMultiProcessOnLinux:true,...(uses3d||usesEffects?{gl}:{})},logLevel:'error'};
  browser=await timed('browser',()=>openBrowser('chrome',launchOptions));
  if(cancelled)throw new Error('Render cancelled');
  const options={serveUrl,id:'SahneProduction',inputProps,...launchOptions,puppeteerInstance:browser,offthreadVideoThreads:1,offthreadVideoCacheSizeInBytes:256*1024*1024};
  const composition=await timed('composition',()=>selectComposition(options));
  metrics.frames=composition.durationInFrames;
  let lastProgress=-1,lastSaved=0;
  if(profile==='preview_frames'){
    const frames=JSON.parse(fs.readFileSync(path.join(path.dirname(outputLocation),'preview-request.json'),'utf8'));
    const results=[];
    await timed('render',()=>renderFrames({...options,composition,frames:frames.map(clock.frame),cancelSignal,concurrency,
      imageFormat:'jpeg',jpegQuality:85,outputDir:null,muted:true,
      onStart:()=>{},onFrameUpdate:count=>{metrics.rendered_frames=count;},
      onFrameBuffer:(buffer,frame)=>{
        frame=Math.round(frame/clock.ratio);
        const name=`preview-${String(frame).padStart(5,'0')}.jpg`;
        fs.writeFileSync(path.join(scratch,name),buffer);
        results.push({frame,file:name,sha256:crypto.createHash('sha256').update(buffer).digest('hex')});
      }}));
    results.sort((a,b)=>a.frame-b.frame);
    for(const result of results)fs.copyFileSync(path.join(scratch,result.file),path.join(path.dirname(outputLocation),result.file));
    fs.writeFileSync(outputLocation,JSON.stringify(results));
  }else{
  const windows=profile==='preview_windows'?JSON.parse(fs.readFileSync(path.join(path.dirname(outputLocation),'preview-windows-request.json'),'utf8')):undefined;
  const range=profile==='chunk'?JSON.parse(fs.readFileSync(path.join(path.dirname(outputLocation),'render-range.json'),'utf8')):undefined;
  if(range&&(!Number.isInteger(range.start_frame)||!Number.isInteger(range.end_frame)||range.start_frame<0||range.end_frame<range.start_frame||range.end_frame>=inputProps.duration_frames))throw new Error('Invalid chunk frame range');
  await timed('render',()=>renderMedia({...options,composition,cancelSignal,scale:profile==='preview'?.5:1,codec:'h264',pixelFormat:'yuv420p',crf:21,x264Preset:'veryfast',concurrency,outputLocation:renderOutputLocation,muted:true,onProgress:({progress,renderedFrames,encodedFrames})=>{
    metrics.rendered_frames=renderedFrames;metrics.encoded_frames=encodedFrames;
    const step=Math.floor(progress*10);
    if(step!==lastProgress){lastProgress=step;console.log(`Render ${step*10}% (${renderedFrames}/${composition.durationInFrames} frames, ${encodedFrames} encoded)`);}
    if(performance.now()-lastSaved>5000){lastSaved=performance.now();saveMetrics();}
  },...(windows?{frameRange:windows.map(w=>clock.range(w.start_frame,w.end_frame))}:{}),...(range?{frameRange:clock.range(range.start_frame,range.end_frame)}:{})}));
  }
  if(profile!=='preview_frames')fs.copyFileSync(renderOutputLocation,outputLocation);
  metrics.completed=true;
}catch(error){
  metrics.cancelled=cancelled;metrics.error_type=error.name;
  throw error;
} finally {
  if(browser)await browser.close({silent:true});
  fs.rmSync(scratch,{recursive:true,force:true});
  saveMetrics();
  process.removeListener('SIGTERM',stop);
  process.removeListener('SIGINT',stop);
}
