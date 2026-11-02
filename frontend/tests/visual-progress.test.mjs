import test from 'node:test';
import assert from 'node:assert/strict';
import {visualProgress,visualCover} from '../src/visual-progress.ts';

const run={outputs:{script:{scenes:[{},{}]}},assets:[
  {id:'old-0',kind:'image',url:'/old-0'},{id:'old-1',kind:'image',url:'/old-1'}]};

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
