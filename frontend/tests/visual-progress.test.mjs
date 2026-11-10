import test from 'node:test';
import assert from 'node:assert/strict';
import {visualProgress,visualCover,assetUrl} from '../src/visual-progress.ts';
import {agentActivity,diagramLayout} from '../src/agent-progress.ts';

const run={outputs:{script:{scenes:[{},{}]}},assets:[
  {id:'old-0',kind:'image',url:'/old-0'},{id:'old-1',kind:'image',url:'/old-1'}]};

test('service waits stay paused and retain actual activity instead of animating work',()=>{
 const current={...run,stage:'visual',status:'waiting_provider',error:'503',
  agent_progress:{visual:{state:'waiting',label:'Açık lisanslı kaynak aranıyor',completed:3,total:14,automatic:true,retry_at:120}}};
 assert.equal(agentActivity(current,'visual','Görsel tasarımı').state,'waiting');
 assert.equal(agentActivity(current,'visual','Görsel tasarımı').completed,3);
 assert.equal(agentActivity({...current,agent_progress:undefined},'visual','Görsel tasarımı').state,'waiting');
});
test('queued jobs are not shown as working and completed outputs remain complete',()=>{
 assert.equal(agentActivity({...run,status:'queued',stage:'visual'},'visual','Görseller').state,'queued');
 assert.equal(agentActivity({...run,status:'waiting_provider',stage:'visual'},'script','Senaryo').state,'done');
});
test('diagram branches at normal widths and preserves real data dependencies',()=>{
 const ids=['supervisor','strategy','script','voice','visual','motion','music','editor','publisher'];
 for(const columns of [2,3]){
  const diagram=diagramLayout(ids,columns);
  assert.ok(new Set(Object.values(diagram.positions).map(p=>p.x)).size>1);
  assert.ok(diagram.links.some(([a,b])=>a==='voice'&&b==='visual'));
  assert.ok(diagram.links.some(([a,b])=>a==='music'&&b==='editor'));
  assert.equal(diagram.links.length,9);
  assert.equal(diagram.links.some(([a,b])=>a==='voice'&&b==='editor'),false);
  assert.equal(diagram.links.filter(([a])=>a==='supervisor').length,1);
 }
 assert.equal(new Set(Object.values(diagramLayout(ids,1).positions).map(p=>p.x)).size,1);
});

test('cloned images do not count as new revision progress or appear as new previews',()=>{
  const progress=visualProgress(run);
  assert.equal(progress.completed,0);
  assert.deepEqual(progress.images,[undefined,undefined]);
});
test('partial shot progress uses validated scene mapping and the actual shot total',()=>{
  const progress=visualProgress({...run,visual_progress:{completed:2,total:4,unit:'shots',scene_images:{'0':'new-0'}}});
  assert.equal(progress.completed,2);assert.equal(progress.total,4);
  assert.deepEqual(progress.images,['new-0',undefined]);
});
test('completed revisions and older APIs use only their confirmed visual output',()=>{
  const progress=visualProgress({...run,outputs:{...run.outputs,visual:{images:['new-0','new-1'],
    shot_images:{a:'new-0',b:'new-2',c:'new-1',d:'new-3'}}}});
  assert.equal(progress.completed,4);assert.equal(progress.total,4);
  assert.deepEqual(progress.images,['new-0','new-1']);
});
test('project thumbnails use the current cover rather than the first cloned asset',()=>{
  assert.equal(visualCover(run),undefined);
  assert.equal(visualCover({...run,outputs:{...run.outputs,visual:{cover:'new-cover',images:['new-image']}},
    assets:[...run.assets,{id:'new-cover',kind:'cover',url:'/new-cover'}]}),'/new-cover');
});

test('Unsplash source photos retain API hotlinks while generated media uses owned assets',()=>{
 const current={...run,outputs:{...run.outputs,visual:{shot_images:{a:'old-0'},generation:{a:{source:{catalog:'unsplash',preview_url:'https://images.unsplash.com/photo-1?ixid=reference'}}}}}};
 assert.equal(assetUrl(current,'old-0'),'https://images.unsplash.com/photo-1?ixid=reference');
 assert.equal(assetUrl(current,'old-1'),'/old-1');
});
