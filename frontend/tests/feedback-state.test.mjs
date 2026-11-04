import test from 'node:test';
import assert from 'node:assert/strict';
import {clarificationTarget,feedbackStatusText} from '../src/feedback-state.ts';

const run={id:'source',status:'waiting_input',outputs:{editor:{video:'existing-video'}}};
const feedback={id:'command',source_run_id:'source',prompt:'İlk sahnedeki çift yazıyı ve daireleri kaldır.',answer:'',status:'failed',decision:{},error:'HTTP 503'};

test('failed command leaves the change composer available, never routes to production answers',()=>{
 assert.equal(clarificationTarget('project',run,feedback),null);
 assert.equal(feedbackStatusText(feedback),'HTTP 503');
 assert.doesNotMatch(feedbackStatusText(feedback),/Değerlendiriliyor/);
 for(const status of ['waiting_provider','waiting_quota','queued'])assert.equal(clarificationTarget('project',run,{...feedback,status}),null);
});
test('feedback question routes to feedback even when the source has waiting_input',()=>{
 const target=clarificationTarget('project',run,{...feedback,status:'needs_clarification',decision:{clarification:'Hangi yazı kalsın?'}});
 assert.equal(target.path,'/projects/project/feedback/command/answers');
 assert.equal(clarificationTarget('project',run,{...feedback,status:'needs_clarification'}),null);
});
test('production clarification applies only before a video exists',()=>{
 const withQuestion={...run,outputs:{...run.outputs,clarification:{question:'Hedef kitle?'}}};
 assert.equal(clarificationTarget('project',withQuestion),null);
 assert.equal(clarificationTarget('project',{...withQuestion,outputs:{clarification:{question:'Hedef kitle?'}}}).path,'/runs/source/answers');
});
test('provider outage is waiting automatically, not completed or awaiting an answer',()=>{
 const text=feedbackStatusText({...feedback,status:'waiting_provider'});
 assert.match(text,/otomatik/);
 assert.doesNotMatch(text,/tamamlanamadı|Yanıtın/);
});
