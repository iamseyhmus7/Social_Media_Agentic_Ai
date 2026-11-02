// Bounded, sequential measurements using existing media. No generation APIs.
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {performance} from 'node:perf_hooks';
import {spawnSync} from 'node:child_process';
import {openBrowser,selectComposition,renderMedia} from '@remotion/renderer';

const [folder,reportPath]=process.argv.slice(2);
if(!folder||!reportPath)throw new Error('Usage: profile.mjs RUN_FOLDER REPORT_PATH');
const scratch=await fs.mkdtemp(path.join(os.tmpdir(),'sahne-profile-'));
const measures=[];
const measure=async(label,fn)=>{
  const start=performance.now();
  const result=await fn();
  const row={label,seconds:Number(((performance.now()-start)/1000).toFixed(3)),...result};
  measures.push(row);console.log(JSON.stringify(row));
  await fs.writeFile(reportPath,JSON.stringify({cpuCount:os.availableParallelism(),measures},null,2));
};
for(const [label,binary] of [['system-ffmpeg','ffmpeg'],['remotion-ffmpeg',path.resolve('node_modules/@remotion/compositor-linux-x64-gnu/ffmpeg')]]){
  await measure(label,async()=>{
    const input=label==='system-ffmpeg'?['-f','lavfi','-i','testsrc2=size=1080x1920:rate=30']:['-i',path.join(scratch,'system-ffmpeg.mp4')];
    const r=spawnSync(binary,['-v','error',...input,'-frames:v','30','-c:v','libx264','-preset','veryfast','-threads','2','-y',path.join(scratch,label+'.mp4')],{timeout:45000,encoding:'utf8'});
    return {status:r.status,error:r.error?.code,detail:r.status?r.stderr?.slice(-1200):undefined};
  });
}
await measure('copy-bundle-to-linux',async()=>{await fs.cp(path.join(folder,'render-bundle'),path.join(scratch,'bundle'),{recursive:true});return {};});
await fs.copyFile(path.join(folder,'reference-0.png'),path.join(scratch,'bundle/public/profile-reference.png'));
const base=JSON.parse(await fs.readFile(path.join(folder,'render-manifest.json'),'utf8'));
let browser;
try{
  await measure('open-headless-shell',async()=>{browser=await openBrowser('chrome',{chromeMode:'headless-shell',chromiumOptions:{enableMultiProcessOnLinux:true},logLevel:'error'});return {};});
  for(const sample of ['empty','image','video','video-medium','video-bind','video-medium-two-tabs']){
    const frames=sample.startsWith('video')?12:3;
    const props={...base,duration_frames:frames,brand:'',logo:'',captions:[],clips:sample==='empty'?[]:[{...base.clips[0],frames,transition:'cut',title:'',...(sample==='image'?{kind:'image',file:'profile-reference.png'}:{})}]};
    const options={serveUrl:sample==='video-bind'?path.join(folder,'render-bundle'):path.join(scratch,'bundle'),id:'SahneProduction',inputProps:props,puppeteerInstance:browser,logLevel:'error',offthreadVideoThreads:1,offthreadVideoCacheSizeInBytes:128*1024*1024};
    let composition;
    await measure(sample+'-composition',async()=>{composition=await selectComposition(options);return {frames:composition.durationInFrames};});
    await measure(sample+'-render',async()=>{await renderMedia({...options,composition,codec:'h264',pixelFormat:'yuv420p',crf:21,x264Preset:sample.includes('medium')?'medium':'veryfast',concurrency:sample.includes('two-tabs')?2:1,outputLocation:path.join(scratch,sample+'.mp4'),muted:true});return {frames};});
  }
}finally{
  if(browser)await browser.close({silent:true});
  // Only this invocation's mkdtemp directory is removed.
  await fs.rm(scratch,{recursive:true,force:true});
}
