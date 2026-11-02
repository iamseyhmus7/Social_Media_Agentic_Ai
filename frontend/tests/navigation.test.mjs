import test from 'node:test';
import assert from 'node:assert/strict';
import {resolveRoute} from '../src/navigation.ts';

test('public home stays a landing page regardless of authentication',()=>{
  for(const signedIn of [true,false])for(const pending of [true,false])assert.equal(resolveRoute('/',signedIn,pending).screen,'home');
});
test('workspace waits for session and sends anonymous visitors to login',()=>{
  assert.deepEqual(resolveRoute('/app',false,true),{screen:'loading'});
  assert.equal(resolveRoute('/app',false,false).redirect,'/login');
  assert.equal(resolveRoute('/app/studio',false,false).redirect,'/login');
  assert.equal(resolveRoute('/app',true,false).screen,'workspace');
});
test('authenticated users proceed from authentication pages to workspace',()=>{
  for(const path of ['/login','/register']){
    assert.equal(resolveRoute(path,true,false).redirect,'/app');
    assert.equal(resolveRoute(path,false,false).screen,path.slice(1));
  }
});
test('unknown paths resolve to the public home',()=>{
  assert.equal(resolveRoute('/missing',false,false).redirect,'/');
});
