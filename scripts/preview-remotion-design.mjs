// Local visual QA only. No generation, narration, publication or GPU jobs.
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const project=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const root=path.join(project,'remotion/production');
const require=createRequire(path.join(root,'package.json'));
const {openBrowser,selectComposition,renderStill}=require('@remotion/renderer');
const [folderArg,mediaArg]=process.argv.slice(2);
if(!folderArg||!mediaArg)throw new Error('Usage: preview-remotion-design.mjs OUTPUT_FOLDER EXISTING_CLIP');
const folder=path.resolve(folderArg),publicDir=path.join(folder,'public'),serveUrl=path.join(folder,'bundle');
fs.mkdirSync(publicDir,{recursive:true});
fs.copyFileSync(path.resolve(mediaArg),path.join(publicDir,'shot-000.mp4'));
const build=spawnSync(process.execPath,[path.join(root,'bundle.mjs'),publicDir,serveUrl],{cwd:root,stdio:'inherit'});
if(build.status!==0)throw new Error('QA bundle failed');
const {SceneDesignDefaults}=await import('./preview-scene-defaults.mjs');
const samples=[];
const clip=(design={},extra={})=>({file:'shot-000.mp4',kind:'clip',start_frame:0,source_in_frame:0,frames:90,transition:'cut',transition_frames:12,handle_frames:0,title:'İstanbul’un izinde: ışık ve derinlik',design:{...SceneDesignDefaults,...design},...extra});
const base={version:2,style:'auto',duration_frames:90,clips:[clip()],captions:[],words:[],graphics:[],sources:[],sound_cues:[],brand:'',logo:'',captions_enabled:false,reconstruction_label:'Canlandırma'};
for(const type of ['iris','diagonal_wipe','blur_dissolve','zoom_out','slide_up']){
 for(const offset of [-1,0,6,12]){
  samples.push({name:`transition-${type}-${offset+1}`,frame:45+offset,props:{...base,clips:[clip({},{frames:45,handle_frames:12,title:''}),clip({font_family:'serif'},{start_frame:45,frames:45,transition:type})]}});
 }
}
for(const kind of ['tilt_up','tilt_down','roll_left','roll_right','snap_zoom','arc'])samples.push({name:'camera-'+kind,frame:65,props:{...base,clips:[clip({camera:{kind,strength:.12}})]}});
for(const type of ['blur_in','elastic','typewriter','flip','tracking'])samples.push({name:'type-'+type,frame:12,props:{...base,clips:[clip({typography:type,font_family:'serif'})]}});
for(const template of ['editorial','glass','blueprint','cinema'])samples.push({name:'template-'+template,frame:30,props:{...base,clips:[clip({template,font_family:template==='cinema'?'serif':'sans'})]}});
for(const kind of ['cube','sphere','torus','icosahedron'])samples.push({name:'object-'+kind,frame:40,props:{...base,clips:[clip({font_family:'serif',object_3d:{kind,color:'#D5AD72',position:'center',scale:1,speed:.4,wireframe:kind==='sphere'}})]}});
for(const text_style of ['outline','extruded','accent'])samples.push({name:'text-'+text_style,frame:30,props:{...base,clips:[clip({text_style})]}});
const launch={browserExecutable:process.env.REMOTION_BROWSER_EXECUTABLE||'C:/Program Files/Google/Chrome/Application/chrome.exe',chromiumOptions:{gl:'angle'},logLevel:'error'};
let browser;
try{
 browser=await openBrowser('chrome',launch);
 for(const sample of samples){
  const options={serveUrl,id:'SahneProduction',inputProps:sample.props,...launch,puppeteerInstance:browser};
  const composition=await selectComposition(options);
  await renderStill({...options,composition,frame:sample.frame,imageFormat:'png',scale:.5,output:path.join(folder,sample.name+'.png')});
  console.log('Verified frame:',sample.name);
 }
 fs.writeFileSync(path.join(folder,'samples.json'),JSON.stringify(samples,null,2));
}finally{if(browser)await browser.close({silent:true});}
