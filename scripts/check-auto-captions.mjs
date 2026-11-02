import assert from 'node:assert/strict';
import {captionPages} from '../remotion/production/caption-pages.mjs';

const words=[0,1,2,3].map(i=>({text:['Altyazı güvenli alanı','Altmış bir yıl önce','Ölçülü görsel vurgu','Kaynaklı anlatım'][i],startMs:i*3000+900,endMs:i*3000+2100}));
const pages=captionPages(words);
assert.equal(pages.length,4,'Unspaced tokens from different scenes must not merge');
assert.equal(pages[0].durationMs,1200,'Captions must disappear during silence');
assert.equal(pages[1].tokens.length,1);
const continuous=Array.from({length:30},(_,i)=>({text:' bilgilendirici',startMs:i*120,endMs:(i+1)*120}));
const densePages=captionPages(continuous);
assert.ok(densePages.every(p=>p.text.length<=48),'Dense narration must fit the subtitle region');
assert.equal(densePages.flatMap(p=>p.tokens).length,30,'Pagination preserves all words');
assert.deepEqual(captionPages([]),[]);
console.log('Caption pagination: 6 checks passed');
