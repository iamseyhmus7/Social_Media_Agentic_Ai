// Compile in a disposable process. Never keep Webpack's heap beside Chromium.
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {bundle} from '@remotion/bundler';
const root=path.dirname(fileURLToPath(import.meta.url));
const [publicDir,outDir]=process.argv.slice(2).map(p=>path.resolve(p));
process.chdir(root);
let last=-1;
await bundle({entryPoint:path.join(root,'src.jsx'),publicDir,publicPath:'/',outDir,onProgress:progress=>{
  const step=Math.floor(progress/25);
  if(step!==last){last=step;console.log(`Composition bundle ${Math.min(100,step*25)}%`);}
}});
