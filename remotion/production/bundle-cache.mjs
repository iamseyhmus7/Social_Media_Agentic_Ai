import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import os from 'node:os';
import {spawn} from 'node:child_process';
import {setTimeout} from 'node:timers/promises';

export const codeHash=(root)=>{
 const hash=crypto.createHash('sha256');
 for(const name of fs.readdirSync(root).sort()){
  if(!/\.(jsx|js|mjs|json)$/.test(name)||!fs.statSync(path.join(root,name)).isFile())continue;
  hash.update(name);hash.update(fs.readFileSync(path.join(root,name)));
 }
 return hash.digest('hex');
};

export async function prepareBundle({root,publicDir,serveUrl,onChild,check}){
 const key=codeHash(root);
 const cache=path.resolve(process.env.REMOTION_BUNDLE_CACHE||path.join(os.tmpdir(),'sahne-remotion-bundles'));
 fs.mkdirSync(cache,{recursive:true});
 const target=path.join(cache,key),lock=target+'.lock';
 let owner=false;
 for(let attempt=0;attempt<600;attempt++){
  check();
  if(fs.existsSync(path.join(target,'.complete')))break;
  try{fs.mkdirSync(lock);owner=true;break;}catch(error){if(error.code!=='EEXIST')throw error;}
  // A killed compiler cannot leave a permanent lock.
  try{
   if(Date.now()-fs.statSync(lock).mtimeMs>600000)fs.rmSync(lock,{recursive:true,force:true});
  }catch(error){if(error.code!=='ENOENT')throw error;}
  await setTimeout(500);
 }
 let hit=!owner;
 if(owner){
  const partial=target+'.'+process.pid+'.partial',empty=path.join(partial,'empty-public');
  fs.mkdirSync(empty,{recursive:true});
  try{
   await new Promise((resolve,reject)=>{
    const child=spawn(process.execPath,[path.join(root,'bundle.mjs'),empty,path.join(partial,'code')],{cwd:root,stdio:'inherit'});
    onChild(child);child.once('error',reject);child.once('close',code=>{onChild(undefined);code===0?resolve():reject(new Error('Composition bundling failed'));});
   });
   check();fs.writeFileSync(path.join(partial,'code','.complete'),key);
   fs.renameSync(path.join(partial,'code'),target);
  }finally{fs.rmSync(partial,{recursive:true,force:true});fs.rmSync(lock,{recursive:true,force:true});}
 }
 if(!fs.existsSync(path.join(target,'.complete')))throw new Error('Bundle cache wait expired');
 // Only generated code is shared. Media is copied into this run's serving root.
 fs.rmSync(serveUrl,{recursive:true,force:true});fs.cpSync(target,serveUrl,{recursive:true});
 fs.cpSync(publicDir,path.join(serveUrl,'public'),{recursive:true});
 return {cache_hit:hit,bundle_key:key};
}
