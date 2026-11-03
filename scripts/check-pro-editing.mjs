// Technical renderer QA: no model calls or changes to application runs.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {outputClock} from '../remotion/production/output-clock.mjs';
const root=path.resolve('remotion/production'),folder=path.resolve('output/remotion-pro-qa');
const require=createRequire(path.join(root,'package.json'));
const {openBrowser,selectComposition,renderStill,renderMedia}=require('@remotion/renderer');
const {SceneDesignDefaults}=await import('./preview-scene-defaults.mjs');
for(const fps of [30,60]){
 const clock=outputClock({output_fps:fps});
 const chunks=[[0,17],[18,44],[45,89]].map(([a,b])=>clock.range(a,b));
 assert.equal(chunks[0][0],0);
 assert.equal(chunks.at(-1)[1]+1,fps*3);
 for(let i=1;i<chunks.length;i++)assert.equal(chunks[i][0],chunks[i-1][1]+1);
}
const clip=(design={},extra={})=>({file:'shot-000.mp4',kind:'clip',start_frame:0,source_in_frame:0,frames:90,
 transition:'cut',transition_frames:12,handle_frames:0,title:'Yapay zekâ: işin nasıl değişiyor?',
 design:{...SceneDesignDefaults,...design},...extra});
const props={version:2,style:'auto',output_fps:60,duration_frames:90,clips:[clip()],captions:[],
 words:[{text:'Değişimi',startMs:0,endMs:1500},{text:'anla.',startMs:1500,endMs:3000}],graphics:[],sources:[],sound_cues:[],brand:'',logo:'',captions_enabled:true};
const launch={browserExecutable:process.env.REMOTION_BROWSER_EXECUTABLE||'C:/Program Files/Google/Chrome/Application/chrome.exe',logLevel:'error'};
const samples=[];
for(const kind of ['wipe','flip','clock_wipe'])for(const frame of [44,45,51,57])samples.push({name:`${kind}-${frame}`,frame,
 props:{...props,clips:[clip({},{frames:45,handle_frames:12,title:''}),clip({},{start_frame:45,frames:45,transition:kind})]}});
for(const effect of ['color_grade','glow','vignette'])samples.push({name:effect,frame:25,props:{...props,clips:[clip({effects:[effect],effect_strength:.65})]}});
for(const kind of ['underline','circle','highlight'])samples.push({name:kind,frame:30,props:{...props,clips:[clip({annotation:kind})]}});
for(const asset of ['pulse_ring','flow_arrow'])samples.push({name:asset,frame:20,props:{...props,clips:[clip({lottie_asset:asset})]}});
samples.push({name:'motion-blur',frame:25,props:{...props,clips:[clip({motion_blur:true,camera:{kind:'pan_right',strength:.15}})]}});
let browser;
try{
 browser=await openBrowser('chrome',launch);
 for(const sample of samples.filter(s=>!process.env.PRO_QA_FILTER||s.name.includes(process.env.PRO_QA_FILTER))){
  const options={serveUrl:path.join(folder,'bundle'),id:'SahneProduction',inputProps:sample.props,...launch,puppeteerInstance:browser};
  const composition=await selectComposition(options);
  assert.equal(composition.fps,60);assert.equal(composition.durationInFrames,180);
  await renderStill({...options,composition,frame:sample.frame*2,imageFormat:'png',scale:.5,output:path.join(folder,sample.name+'.png')});
  console.log('Verified',sample.name);
 }
 for(const fps of [30,60]){
  const inputProps={...props,output_fps:fps,duration_frames:30,clips:[clip({lottie_asset:'flow_arrow',annotation:'underline',effects:['color_grade']},{frames:30})],words:[]};
  const options={serveUrl:path.join(folder,'bundle'),id:'SahneProduction',inputProps,...launch,puppeteerInstance:browser};
  const composition=await selectComposition(options);
  await renderMedia({...options,composition,codec:'h264',pixelFormat:'yuv420p',concurrency:1,scale:.5,muted:true,outputLocation:path.join(folder,`clock-${fps}.mp4`)});
  console.log('Rendered clock',fps);
  fs.writeFileSync(path.join(folder,`manifest-${fps}.json`),JSON.stringify(inputProps));
 }
 fs.writeFileSync(path.join(folder,'qa.json'),JSON.stringify({samples:samples.map(s=>s.name),fps:[30,60],verified:true},null,2));
}finally{if(browser)await browser.close({silent:true});}
