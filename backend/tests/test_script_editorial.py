from copy import deepcopy
import pytest
from pydantic import ValidationError
from backend.app.script_editorial import generate_editorial_script, SpokenDraft, SpokenReview
from backend.app.schemas import Script
from backend.app.providers import ProviderError


DRAFT = {'hook':'Ekran saldırı diyordu.', 'narration':'Ekran saldırı diyordu. Görevli subay uyarıyı sorguladı. Sonunda bunun yanlış alarm olduğu anlaşıldı.'}


class Writer:
    def __init__(self, *, mutate=False, ready=True):
        self.calls=[]
        self.mutate=mutate
        self.ready=ready

    def generate(self,schema,role,context):
        self.calls.append(role)
        if schema is SpokenDraft:
            value=deepcopy(DRAFT)
        elif schema is SpokenReview:
            value={'ready':self.ready,'opening_evidence':'Somut bir saldırı uyarısıyla açılıyor.',
                   'spoken_language_evidence':'Cümleler kısa ve kolay okunuyor.',
                   'progression_evidence':'Uyarı, şüphe ve çözüm ilerliyor.',
                   'factual_limits':'Bağımsız tarihsel doğrulama yapılmadı.',
                   'changes':[],'draft':deepcopy(DRAFT)}
        else:
            texts=['Ekran saldırı diyordu.','Görevli subay uyarıyı sorguladı.',
                   'Sonunda bunun yanlış alarm olduğu anlaşıldı.']
            if self.mutate:
                texts[1]='Görevli subay dünyayı kurtardı.'
            value={'hook':DRAFT['hook'],'cta':texts[-1],
                   'scenes':[{'title':f'Sahne {i}', 'narration':text,
                              'visual_prompt':'Vertical cinematic illustration'} for i,text in enumerate(texts)]}
        return schema.model_validate(value).model_dump()


def test_approved_story_is_preserved_through_scene_allocation():
    llm=Writer()
    script,audit=generate_editorial_script(llm,Script,{'duration_seconds':45},'Sahnele.')
    assert ' '.join(s['narration'] for s in script['scenes'])==DRAFT['narration']
    assert audit['reviews'][0]['ready']
    assert llm.calls==['Senaryo Yazarı','Supervisor / Senaryo editörü','Senaryo Yazarı / Sahneleme']


def test_scene_allocation_cannot_rewrite_approved_words():
    with pytest.raises(ValidationError,match='Onaylanan anlatımı'):
        generate_editorial_script(Writer(mutate=True),Script,{},'Sahnele.')


def test_rejected_editorial_review_stops_before_allocation():
    llm=Writer(ready=False)
    with pytest.raises(ProviderError,match='editoryal'):
        generate_editorial_script(llm,Script,{},'Sahnele.')
    assert len(llm.calls)==3
    assert not any('Sahneleme' in r for r in llm.calls)


def test_opening_must_be_present_in_spoken_text():
    with pytest.raises(ValidationError,match='hook'):
        SpokenDraft.model_validate({**DRAFT,'hook':'Farklı bir açılış.'})


def test_script_only_stops_supervisor_and_blocks_direct_media(setup,monkeypatch):
    from backend.tests.test_agentic import create_run
    from backend.app import orchestration, pipeline
    from backend.app.providers import Evren
    ident=create_run({'_script_only':True,'script':{'scenes':[]}})
    monkeypatch.setattr(Evren,'generate',lambda *a,**k:pytest.fail('No model/media may start after script'))
    with pytest.raises(orchestration.NeedsInput,match='Senaryo hazır'):
        orchestration.supervise(ident)
    for stage in ('voice','visual','motion','editor'):
        with pytest.raises(orchestration.NeedsInput,match='medya'):
            pipeline.run_stage(ident,stage)


def test_script_only_option_is_persisted_from_authenticated_ui_request(clients,project,monkeypatch):
    from backend.app import main
    from backend.app.db import DB,Run
    monkeypatch.setattr(main,'dispatch',lambda:None)
    response=clients[0].post('/api/v1/projects/'+project['id']+'/runs',json={'script_only':True})
    assert response.status_code==202
    with DB() as db:
        assert db.get(Run,response.json()['id']).outputs['_script_only'] is True


def v2_context():
    return {'duration_seconds':45,'creative_brief':{'editorial_direction':{
        'story_question':'Uyarının nedeni nasıl anlaşıldı?', 'stakes':'Hatalı bilgi önemli bir kararı etkiliyordu.',
        'causal_focus':'Görevlinin şüphesinin gerekçesi anlatılmalı.', 'payoff':'Uyarının gerçek nedeni açıklanmalı.',
        'scene_count':5,'closing_mode':'result','evidence_required':True,'research_query':'test sensor alarm'}},
        'story_research':{'sources':[{'id':'source:1','text':'The sensor produced a false warning. A reflection caused the warning.'}]}}


def v2_draft():
    texts=['Bir uyarı kararı değiştirebilirdi.', 'Görevli ekrandaki bilgiyi kontrol etti.',
           'Başka ölçüm olmadığı için uyarıdan şüphelendi.', 'İnceleme tamamlanana kadar sonucu bekledi.',
           'Sonunda uyarının ışık yansımasından kaynaklandığı anlaşıldı.']
    return {'hook':texts[0], 'beats':[{'title':f'Adım {i}','narration':t} for i,t in enumerate(texts)],
        'stakes_sentence':texts[0],'cause_sentence':texts[2],'payoff_sentence':texts[4],
        'facts':[{'claim':'Sensör yanlış uyarı verdi.','source_id':'source:1','quote':'The sensor produced a false warning.'},
                 {'claim':'Neden ışık yansımasıydı.','source_id':'source:1','quote':'A reflection caused the warning.'}]}


class WriterV2:
    def __init__(self, fail_visual=False, reject=False):
        self.calls=[]; self.fail_visual=fail_visual; self.reject=reject

    def generate(self,schema,role,context):
        from backend.app.script_editorial import StoryDraft,EditorialVerdict,CRITERIA,VisualVerdict
        self.calls.append(role)
        if issubclass(schema,StoryDraft):
            assert 'authority' in context
            value=v2_draft()
        elif issubclass(schema,EditorialVerdict):
            assert 'draft' not in schema.model_fields  # judge cannot rewrite and approve itself
            value={'decision':'revise' if self.reject else 'approve','reason':'Supervisor metni değerlendirdi ve kararını verdi.', 'checks':[{'criterion':c,'passed':not self.reject,'severity':'major' if self.reject else 'minor',
                'evidence_quote':v2_draft()['beats'][0 if c=='opening' else -1]['narration'],
                'reason':'Bu metindeki sonuç cümlesi değerlendirme kanıtıdır.'} for c in sorted(CRITERIA)]}
        elif schema is VisualVerdict:
            value={'decision':'approve','reason':'Görsel yönergeler onaylı metinle tutarlı.','findings':[]}
        else:
            if self.fail_visual:
                raise RuntimeError('temporary visual metadata outage')
            assert 'narration' not in schema.model_fields
            value={'format':'documentary','continuity':'Consistent sensor room and duty officer.',
                'scenes':[{'scene_index':i,'visual_prompt':'Vertical 9:16 illustration of a sensor control room.',
                    'action':'Görevli ekranı inceler.','state_before':'Ekran ışığı yanar.','state_after':'Görevli ekrana döner.'} for i in range(len(context['approved_beats']))]}
        return schema.model_validate(value).model_dump()


def test_v2_resumes_visual_outage_without_rewriting_or_rereviewing():
    from backend.app.script_editorial import generate_editorial_script_v2
    from backend.app.schemas import StoryScript
    checkpoints=[];llm=WriterV2(fail_visual=True)
    with pytest.raises(RuntimeError,match='outage'):
        generate_editorial_script_v2(llm,StoryScript,v2_context(),'Sahnele',save=checkpoints.append)
    assert checkpoints[-1]['approved'] is True
    resumed=WriterV2()
    script,audit=generate_editorial_script_v2(resumed,StoryScript,v2_context(),'Sahnele',progress=checkpoints[-1])
    assert resumed.calls==['Senaryo Yazarı / Sahneleme','Supervisor / Görsel senaryo editörü']
    assert [s['narration'] for s in script['scenes']]==[b['narration'] for b in v2_draft()['beats']]
    assert script['cta']==v2_draft()['payoff_sentence']


def test_v2_missing_sources_never_calls_a_model():
    from backend.app.script_editorial import generate_editorial_script_v2
    llm=WriterV2();ctx=v2_context();ctx['story_research']['sources']=[]
    with pytest.raises(ProviderError,match='kaynak'):
        generate_editorial_script_v2(llm,Script,ctx,'Sahnele')
    assert llm.calls==[]


def test_v2_negative_judgment_cannot_reach_visuals():
    from backend.app.script_editorial import generate_editorial_script_v2
    llm=WriterV2(reject=True);checkpoints=[]
    with pytest.raises(ProviderError,match='iki editoryal'):
        generate_editorial_script_v2(llm,Script,v2_context(),'Sahnele',save=checkpoints.append)
    assert 'Senaryo Yazarı / Sahneleme' not in llm.calls
    assert len(checkpoints[-1]['drafts'])==2


@pytest.mark.parametrize('fault',['source'])
def test_v2_rejects_invented_evidence_and_structural_failures(fault):
    from backend.app.script_editorial import generate_editorial_script_v2,StoryDraft,EditorialVerdict,CRITERIA
    class InvalidWriter(WriterV2):
        def generate(self,schema,role,context):
            if issubclass(schema,StoryDraft):
                value=v2_draft()
                if fault=='source':value['facts'][0]['quote']='This quote was never in the source.'
                if fault=='payoff':value['payoff_sentence']='Peki sonunda kim karar verecek?'
                if fault=='count':value['beats'].pop()
                return schema.model_validate(value).model_dump()
            if issubclass(schema,EditorialVerdict):
                return schema.model_validate({'checks':[{'criterion':c,'passed':True,
                    'evidence_quote':'Anlatımda bulunmayan bir kanıt.', 'reason':'Olmayan alıntıyla onay üretilemez.'} for c in CRITERIA]}).model_dump()
            return super().generate(schema,role,context)
    with pytest.raises(ValidationError):
        generate_editorial_script_v2(InvalidWriter(),Script,v2_context(),'Sahnele')


def test_story_research_uses_fixed_destination_and_actual_article_text():
    import httpx
    from backend.app.providers import research_story
    def respond(request):
        assert request.url.host=='en.wikipedia.org'
        if request.url.params.get('list')=='search':
            return httpx.Response(200,json={'query':{'search':[{'pageid':42,'title':'Sensor alarm'}]}})
        return httpx.Response(200,json={'query':{'pages':{'42':{'title':'Sensor alarm','extract':'A reflection caused the warning.'}}}})
    sources=research_story('Sensor alarm',transport=httpx.MockTransport(respond),user_agent='TestResearchBot/1.0 (https://example.test/research)')
    assert sources['sources'][0]['id']=='wikipedia:42'
    assert 'reflection' in sources['sources'][0]['text']
    assert 'not independent' in sources['verification_scope']


def test_story_research_failure_does_not_fabricate_sources():
    import httpx
    from backend.app.providers import research_story
    sources=research_story('Sensor alarm',transport=httpx.MockTransport(lambda r:httpx.Response(403)),user_agent='TestResearchBot/1.0 (https://example.test/research)')
    assert sources['sources']==[] and sources['errors']


def test_completed_script_only_run_is_a_successful_terminal_state(setup,monkeypatch):
    from backend.tests.test_agentic import create_run
    from backend.app import pipeline,orchestration
    from backend.app.db import DB,Run
    ident=create_run({'_script_only':True,'script':{'scenes':[{'narration':'Hazır anlatım.'}]}})
    class Graph:
        def invoke(self,*a,**kw):
            raise orchestration.NeedsInput('Senaryo hazır.')
    monkeypatch.setattr(pipeline,'build_graph',lambda version:Graph())
    pipeline.execute(ident)
    with DB() as db:
        run=db.get(Run,ident)
        assert run.status=='script_ready' and run.error is None and run.stage=='script'
        assert run.active_owner is None and run.finished is not None


def test_strategy_does_not_claim_research_is_done_when_source_fetch_failed(setup,monkeypatch):
    from backend.tests.test_agentic import create_run
    from backend.app import pipeline,providers
    from backend.app.config import settings
    monkeypatch.setattr(settings(),'story_research_enabled',True)
    ident=create_run({'_config':{'script_editorial_policy':2},'supervisor':v2_context()['creative_brief']})
    monkeypatch.setattr(pipeline,'research',lambda topic:{'sources':[]})
    monkeypatch.setattr(providers,'research_story',lambda query:{'sources':[],'errors':['HTTP 403']})
    monkeypatch.setattr(pipeline.Evren,'generate',lambda *a,**kw:pytest.fail('No source-free strategy call'))
    with pytest.raises(ProviderError,match='kaynak metni alınamadı'):
        pipeline.run_stage(ident,'strategy')


def test_changed_brief_invalidates_old_editorial_checkpoint():
    from backend.app.script_editorial import generate_editorial_script_v2
    llm=WriterV2();_,audit=generate_editorial_script_v2(llm,Script,v2_context(),'Sahnele')
    changed=v2_context();changed['creative_brief']['editorial_direction']['stakes']='Güncellenen supervisor kararının önemi.'
    resumed=WriterV2()
    generate_editorial_script_v2(resumed,Script,changed,'Sahnele',progress=audit)
    assert resumed.calls[0]=='Senaryo Yazarı'


def test_knowledge_only_writes_and_reviews_without_sources_or_fake_citations():
    from backend.app.script_editorial import generate_editorial_script_v2,StoryDraft
    class KnowledgeWriter(WriterV2):
        def generate(self,schema,role,context):
            if issubclass(schema,StoryDraft):
                self.calls.append(role)
                assert 'LLM bilgisi' in context['knowledge_policy']
                value=v2_draft();value['facts']=[]
                return schema.model_validate(value).model_dump()
            return super().generate(schema,role,context)
    ctx=v2_context()  # even a cached supervisor's old evidence_required=true cannot block this mode
    ctx['story_research']={'sources':[],'verification_scope':'model_knowledge_only'}
    llm=KnowledgeWriter()
    script,audit=generate_editorial_script_v2(llm,Script,ctx,'Sahnele')
    assert script['hook']==v2_draft()['hook'] and audit['approved']
    assert audit['draft']['facts']==[]


def test_strategy_skips_new_research_service_when_disabled(setup,monkeypatch):
    from backend.tests.test_agentic import create_run
    from backend.app import pipeline,providers
    from backend.app.config import settings
    from backend.app.db import DB,Run
    monkeypatch.setattr(settings(),'story_research_enabled',False)
    ident=create_run({'_config':{'script_editorial_policy':2},'supervisor':v2_context()['creative_brief']})
    monkeypatch.setattr(pipeline,'research',lambda topic:{'sources':[]})
    monkeypatch.setattr(providers,'research_story',lambda *a,**kw:pytest.fail('External source service must not run'))
    def generate(self,schema,role,context,**kw):
        assert 'LLM bilgisi' in context['knowledge_policy']
        return {'title':'Örnek anlatı açısı','angle':'Somut bir kararın nedenini anlat.','audience':'Meraklı izleyici'}
    monkeypatch.setattr(pipeline.Evren,'generate',generate)
    pipeline.run_stage(ident,'strategy')
    with DB() as db:
        o=db.get(Run,ident).outputs
        assert o['_story_research']['verification_scope']=='model_knowledge_only'
        assert 'strategy' in o


def test_supervisor_can_approve_minor_notes_and_paraphrased_quotes():
    from backend.app.script_editorial import generate_editorial_script_v2,SupervisorVerdict,CRITERIA
    class MinorNotes(WriterV2):
        def generate(self,schema,role,context):
            if issubclass(schema,SupervisorVerdict):
                self.calls.append(role)
                return schema.model_validate({'decision':'approve','reason':'Küçük ifade farkları anlatının amacını bozmuyor.',
                    'checks':[{'criterion':c,'passed':False,'severity':'minor',
                        'evidence_quote':'Metnin birebir kopyası olmayan bir açıklama.', 'beat_indices':[0],
                        'reason':'Küçük üslup önerisi var; üretimi durduracak bir sorun değil.'} for c in sorted(CRITERIA)]}).model_dump()
            return super().generate(schema,role,context)
    ctx=v2_context();ctx['creative_brief']['editorial_direction']['scene_count']=6
    script,audit=generate_editorial_script_v2(MinorNotes(),Script,ctx,'Sahnele')
    assert len(script['scenes'])==5  # supervisor explicitly accepted the writer's five-scene alternative
    assert audit['approved'] and audit['accepted_scene_count']==5
    assert audit['reviews'][0]['checks'][0]['resolved_evidence'][0]['text']==v2_draft()['beats'][0]['narration']


def test_major_problem_cannot_be_approved_in_the_same_verdict():
    from backend.app.script_editorial import SupervisorVerdict,CRITERIA
    with pytest.raises(ValidationError,match='Büyük/kritik'):
        SupervisorVerdict.model_validate({'decision':'approve','reason':'Çelişkili bir onay kararı örneği.',
            'checks':[{'criterion':c,'passed':False,'severity':'major','reason':'Ana konu ve kullanıcı hedefi tamamen değişmiş.'} for c in sorted(CRITERIA)]})


def test_closing_field_uses_approved_last_narration_instead_of_a_separate_slogan():
    from backend.app.script_editorial import generate_editorial_script_v2, StoryDraft
    class SeparateSlogan(WriterV2):
        def generate(self, schema, role, context):
            value = super().generate(schema, role, context)
            if issubclass(schema, StoryDraft):
                value['payoff_sentence'] = 'Anlatımda bulunmayan ve daha kesin bir sonuç vaat eden slogan.'
            return schema.model_validate(value).model_dump()
    script, _ = generate_editorial_script_v2(SeparateSlogan(), Script, v2_context(), 'Sahnele')
    assert script['cta'] == script['scenes'][-1]['narration']
    assert 'slogan' not in script['cta']


def test_approved_closing_is_not_cut_to_the_old_metadata_limit():
    from backend.app.script_editorial import generate_editorial_script_v2, StoryDraft
    closing = 'Sonuç, gözlenen ışık yansımasıyla açıklanır. ' * 9
    assert 300 < len(closing) < 800
    class LongClosing(WriterV2):
        def generate(self, schema, role, context):
            value = super().generate(schema, role, context)
            if issubclass(schema, StoryDraft):
                value['beats'][-1]['narration'] = closing
            return schema.model_validate(value).model_dump()
    script, _ = generate_editorial_script_v2(LongClosing(), Script, v2_context(), 'Sahnele')
    assert script['cta'] == script['scenes'][-1]['narration'] == closing


def test_visual_revision_changes_only_target_metadata_and_survives_review_outage():
    from backend.app.script_editorial import generate_editorial_script_v2, VisualVerdict
    class VisualCorrection(WriterV2):
        def __init__(self):
            super().__init__()
            self.review_count = 0
        def generate(self, schema, role, context):
            if schema is VisualVerdict:
                self.calls.append(role)
                self.review_count += 1
                if self.review_count == 2:
                    raise RuntimeError('temporary visual review outage')
                return schema.model_validate({'decision':'revise',
                    'reason':'Bir sahnede görsel ölçek anlatılan ilişkiyi değiştiriyor.',
                    'findings':[{'scene_indices':[2], 'severity':'major',
                        'reason':'Miktarı yokmuş gibi gösterme; yalnız anlatımın desteklediği ilişkiyi göster.'}]}).model_dump()
            if schema.__name__ == 'VisualPatch':
                self.calls.append(role)
                assert context['target_scene_indices'] == [2]
                scene = deepcopy(context['current_visuals']['scenes'][2])
                scene['visual_prompt'] = 'Vertical 9:16 illustration preserving the described scale and quantity.'
                return schema.model_validate({'scenes':[scene], 'continuity':None}).model_dump()
            return super().generate(schema, role, context)
    checkpoints = []
    with pytest.raises(RuntimeError, match='review outage'):
        generate_editorial_script_v2(VisualCorrection(), Script, v2_context(), 'Sahnele', save=checkpoints.append)
    saved = checkpoints[-1]
    assert saved['approved'] and saved['visual_repair_done']
    resumed = WriterV2()
    script, audit = generate_editorial_script_v2(resumed, Script, v2_context(), 'Sahnele', progress=saved)
    assert resumed.calls == ['Supervisor / Görsel senaryo editörü']
    assert audit['visuals_approved']
    assert [s['narration'] for s in script['scenes']] == [b['narration'] for b in v2_draft()['beats']]
    assert 'preserving the described scale' in script['scenes'][2]['visual_prompt']
    assert script['scenes'][1]['visual_prompt'] == 'Vertical 9:16 illustration of a sensor control room.'


def test_supervisor_plan_revision_reaches_visual_specialist_without_rewriting_narration():
    from backend.app.script_editorial import generate_editorial_script_v2, StoryDraft, SupervisorVerdict
    question = {'question':'Uyarı hangi mekanizmayla oluştu?', 'priority':'core',
                'answer_requirements':'Işık yansımasının sensördeki yanlış uyarıya nasıl dönüştüğünü açıkla.'}
    received = {}
    class PlanRevision(WriterV2):
        def generate(self, schema, role, context):
            value = super().generate(schema, role, context)
            if issubclass(schema, StoryDraft):
                value['plan_revision_proposals'] = ['Mekanizmaya daha fazla açıklama ayır; giriş bağlamını kısalt.']
            elif issubclass(schema, SupervisorVerdict):
                assert context['draft']['plan_revision_proposals']
                value['plan_updates'] = {'critical_questions':[question],
                    'attention_allocation':'Ana mekanizmaya daha fazla anlatım alanı, bağlama daha az alan ayır.'}
            else:
                received.update(context['creative_brief']['editorial_direction'])
            return schema.model_validate(value).model_dump()
    script, audit = generate_editorial_script_v2(PlanRevision(), Script, v2_context(), 'Sahnele')
    assert received['critical_questions'] == [question]
    assert audit['accepted_editorial_direction']['critical_questions'] == [question]
    assert [s['narration'] for s in script['scenes']] == [b['narration'] for b in v2_draft()['beats']]


def test_approved_content_priority_update_is_committed_to_shared_plan(setup, monkeypatch):
    from backend.tests.test_agentic import create_run
    from backend.app import pipeline, script_editorial
    from backend.app.db import DB, Run
    from backend.app.schemas import StoryScript
    ctx = v2_context()
    script, audit = script_editorial.generate_editorial_script_v2(WriterV2(), StoryScript, ctx, 'Sahnele')
    accepted = {**ctx['creative_brief']['editorial_direction'],
                'attention_allocation':'Mekanizma açıklamasına öncelik ver; destek bölümünü kısa tut.'}
    audit['accepted_editorial_direction'] = accepted
    ident = create_run({'_config':{'script_editorial_policy':2}, '_edit_style':'auto',
                        'supervisor':ctx['creative_brief']})
    monkeypatch.setattr(script_editorial, 'generate_editorial_script_v2', lambda *a, **kw:(script,audit))
    pipeline.run_stage(ident, 'script')
    with DB() as db:
        outputs = db.get(Run, ident).outputs
        assert outputs['supervisor']['editorial_direction']['attention_allocation'] == accepted['attention_allocation']
        assert outputs['_supervisor_plan_updates'][-1]['field'] == 'attention_allocation'


def test_supervisor_cancel_stops_before_writer_repair_or_visuals():
    from backend.app.script_editorial import generate_editorial_script_v2,SupervisorVerdict,CRITERIA
    from backend.app.orchestration import NeedsInput
    class Cancel(WriterV2):
        def generate(self,schema,role,context):
            if issubclass(schema,SupervisorVerdict):
                self.calls.append(role)
                return schema.model_validate({'decision':'cancel','reason':'Ana konu değişmiş ve iddialar yanıltıcı; üretime devam etme.',
                    'checks':[{'criterion':c,'passed':False,'severity':'critical','reason':'İçerik istenen konudan büyük ölçüde sapıyor.'} for c in sorted(CRITERIA)]}).model_dump()
            return super().generate(schema,role,context)
    llm=Cancel();saved=[]
    with pytest.raises(NeedsInput,match='Supervisor senaryoyu durdurdu'):
        generate_editorial_script_v2(llm,Script,v2_context(),'Sahnele',save=saved.append)
    assert llm.calls==['Senaryo Yazarı','Supervisor / Senaryo editörü']
    assert saved[-1]['reviews'][-1]['decision']=='cancel'


def test_old_failed_review_checkpoint_reuses_existing_draft():
    from backend.app.script_editorial import generate_editorial_script_v2
    _,audit=generate_editorial_script_v2(WriterV2(),Script,v2_context(),'Sahnele')
    audit.pop('review_policy');audit.pop('visuals');audit['approved']=False;audit['reviews']=[]
    resumed=WriterV2()
    generate_editorial_script_v2(resumed,Script,v2_context(),'Sahnele',progress=audit)
    assert resumed.calls==['Supervisor / Senaryo editörü','Senaryo Yazarı / Sahneleme','Supervisor / Görsel senaryo editörü']


def test_failed_model_review_can_retry_without_losing_draft(clients,monkeypatch):
    from backend.tests.test_agentic import create_run
    from backend.app import main
    from backend.app.db import DB,Run
    checkpoint={'draft':v2_draft(),'fingerprint':'preserve'}
    ident=create_run({'_script_editorial':checkpoint,'_recovery':{'active':'model_output'}})
    with DB() as db:
        r=db.get(Run,ident);r.status='waiting_input';r.stage='script';r.error='Model üç denemede çıktı üretmedi.';db.commit()
    monkeypatch.setattr(main,'dispatch',lambda:None)
    assert clients[0].get('/api/v1/runs/'+ident).json()['can_retry'] is True
    assert clients[0].post('/api/v1/runs/'+ident+'/retry').status_code==202
    with DB() as db:
        r=db.get(Run,ident)
        assert r.outputs['_script_editorial']==checkpoint
        assert r.status=='queued' and r.outputs['_recovery']['active'] is None


def test_accepted_scene_count_reaches_the_shared_supervisor_plan(setup,monkeypatch):
    from backend.tests.test_agentic import create_run
    from backend.app import pipeline,script_editorial
    from backend.app.db import DB,Run
    from backend.app.schemas import StoryScript
    context=v2_context()
    accepted,_=script_editorial.generate_editorial_script_v2(WriterV2(),StoryScript,context,'Sahnele')
    brief=context['creative_brief'];brief['editorial_direction']['scene_count']=6
    ident=create_run({'_config':{'script_editorial_policy':2},'_edit_style':'auto','supervisor':brief})
    def generate(*a,**kw):
        return accepted,{'reviews':[{'decision':'approve','reason':'Beş sahnelik öneri daha iyi; kabul ediyorum.'}]}
    monkeypatch.setattr(script_editorial,'generate_editorial_script_v2',generate)
    pipeline.run_stage(ident,'script')
    with DB() as db:
        outputs=db.get(Run,ident).outputs
        assert outputs['supervisor']['editorial_direction']['scene_count']==len(outputs['script']['scenes'])==5
        assert outputs['_supervisor_plan_updates'][-1]['previous']==6


def test_clarification_cannot_be_skipped_using_model_review_retry(clients,monkeypatch):
    from backend.tests.test_agentic import create_run
    from backend.app.db import DB,Run
    ident=create_run({'clarification':{'question':'Hangi ürünü anlatıyoruz?'}})
    with DB() as db:
        run=db.get(Run,ident);run.status='waiting_input';run.stage='supervisor';db.commit()
    assert clients[0].post('/api/v1/runs/'+ident+'/retry').status_code==409


def test_visual_review_limit_waits_and_explicit_retry_preserves_text(clients, monkeypatch):
    from backend.app.script_editorial import generate_editorial_script_v2, VisualVerdict
    from backend.app.orchestration import NeedsInput
    from backend.app import main
    from backend.app.db import DB, Run
    from backend.tests.test_agentic import create_run
    class RejectVisuals(WriterV2):
        def generate(self, schema, role, context):
            if schema is VisualVerdict:
                self.calls.append(role)
                return schema.model_validate({'decision':'revise','reason':'Eylem anlatımla çelişiyor.',
                    'findings':[{'scene_indices':[2],'severity':'major','reason':'Eylemi anlatımla eşleştir.'}]}).model_dump()
            if schema.__name__ == 'VisualPatch':
                self.calls.append(role)
                return schema.model_validate({'scenes':[context['current_visuals']['scenes'][2]],'continuity':None}).model_dump()
            return super().generate(schema, role, context)
    checkpoints=[]
    llm=RejectVisuals()
    with pytest.raises(NeedsInput, match='Görsel plan düzeltme bekliyor'):
        generate_editorial_script_v2(llm,Script,v2_context(),'Sahnele',save=checkpoints.append)
    saved=checkpoints[-1]
    assert saved['approved'] and not saved['visuals_approved']
    assert saved['phase']=='visual_revision_pending' and len(saved['visual_reviews'])==2
    assert llm.calls.count('Senaryo Yazarı / Görsel düzeltme')==1
    ident=create_run({'_script_editorial':saved,'_script_only':True})
    with DB() as db:
        run=db.get(Run,ident);run.status='waiting_input';run.stage='script';db.commit()
    monkeypatch.setattr(main,'dispatch',lambda:None)
    public=clients[0].get('/api/v1/runs/'+ident).json()
    assert public['can_retry'] and public['script_progress']['approved_text']==saved['draft']
    assert 'script' not in public['outputs']  # Pending metadata must not unlock media.
    assert '_script_editorial' not in public['outputs']
    assert clients[0].post('/api/v1/runs/'+ident+'/retry').status_code==202
    with DB() as db:
        resumed=db.get(Run,ident).outputs['_script_editorial']
    assert resumed['visual_review_window_start']==2
    assert resumed['draft']==saved['draft'] and resumed['visuals']==saved['visuals']
    class RepairThenApprove(WriterV2):
        def generate(self,schema,role,context):
            if schema.__name__=='VisualPatch':
                self.calls.append(role)
                return schema.model_validate({'scenes':[context['current_visuals']['scenes'][2]],'continuity':None}).model_dump()
            return super().generate(schema,role,context)
    finisher=RepairThenApprove()
    script,audit=generate_editorial_script_v2(finisher,Script,v2_context(),'Sahnele',progress=resumed)
    assert finisher.calls==['Senaryo Yazarı / Görsel düzeltme','Supervisor / Görsel senaryo editörü']
    assert audit['phase']=='ready' and audit['visuals_approved']
    assert [s['narration'] for s in script['scenes']]==[s['narration'] for s in saved['draft']['beats']]


@pytest.mark.parametrize('question,requirement', [
    ('Bir sensör uyarısı neden yanlış çıktı?', 'Algılanan sinyalin hatalı sonuca nasıl dönüştüğünü açıkla.'),
    ('Bir ekip işi neden daha hızlı bitirdi?', 'İş adımları değişince bekleme süresinin nasıl azaldığını açıkla.'),
])
def test_reviewed_plan_and_missing_answer_reach_repair_and_final_visuals(question, requirement):
    from backend.app.script_editorial import generate_editorial_script_v2, SupervisorVerdict, StoryDraft, VisualVerdict
    revised = {'story_question':question, 'critical_questions':[{'question':question,'priority':'core',
        'answer_requirements':requirement}], 'opening_direction':'Sonucu göster; ana açıklamayı geciktirmeden başlat.',
        'closing_direction':'Açılıştaki sorunun cevabını somut sonuçla tamamla.'}
    coverage=[{'question':question,'beat_indices':[2],'assessment':'Sebebin adı var; sonuca nasıl dönüştüğü seslendirmede eksik.'}]
    observed={}
    class DynamicReview(WriterV2):
        def __init__(self):
            super().__init__();self.reviews=0
        def generate(self,schema,role,context):
            if issubclass(schema,SupervisorVerdict):
                self.reviews+=1
                assert context['spoken_text']==' '.join(b['narration'] for b in context['draft']['beats'])
                assert 'beats[].narration' in context['answer_scope']
                value=super().generate(schema,role,context)
                if self.reviews==1:
                    value.update(decision='revise', plan_updates=revised, question_coverage=coverage)
                    check=next(c for c in value['checks'] if c['criterion']=='progression')
                    check.update(passed=False,severity='major',reason='Ana cevabın bağlantısı eksik; görsel bunu ikame edemez.')
                else:
                    assert context['creative_brief']['editorial_direction']['story_question']==question
                    value.update(plan_updates=None,question_coverage=coverage)
                return schema.model_validate(value).model_dump()
            if role=='Senaryo Yazarı / Editoryal düzeltme':
                assert context['question_coverage']==coverage
                assert context['creative_brief']['editorial_direction']['closing_direction']==revised['closing_direction']
                observed['repair']=True
            if role=='Senaryo Yazarı / Sahneleme':
                observed['visual_direction']=context['creative_brief']['editorial_direction']
            return super().generate(schema,role,context)
    llm=DynamicReview()
    _,audit=generate_editorial_script_v2(llm,Script,v2_context(),'Sahnele')
    assert observed['repair']
    assert observed['visual_direction']['story_question']==question
    assert observed['visual_direction']['critical_questions']==revised['critical_questions']
    assert audit['accepted_editorial_direction']['opening_direction']==revised['opening_direction']
    assert llm.calls==['Senaryo Yazarı','Supervisor / Senaryo editörü','Senaryo Yazarı / Editoryal düzeltme',
        'Supervisor / Senaryo editörü','Senaryo Yazarı / Sahneleme','Supervisor / Görsel senaryo editörü']



def ready_script_run():
    from backend.tests.test_agentic import create_run
    from backend.app.db import DB,Run
    outputs={'_script_only':True,'supervisor':{'duration':45},'strategy':{'title':'Hazır konu'},
        'script':{'hook':'Hazır giriş.','scenes':[{'narration':'Hazır giriş. Mevcut anlatım korunur.','visual_prompt':'Existing approved visual direction.'}]},
        '_config':{'script_editorial_policy':2},'_script_editorial':{'approved':True,'visuals_approved':True}}
    ident=create_run(outputs)
    with DB() as db:
        r=db.get(Run,ident);r.status='script_ready';r.stage='script';r.finished=123;db.commit()
    return ident,outputs


def test_continue_script_reuses_run_and_completed_outputs(clients,monkeypatch):
    from backend.app import main,orchestration
    from backend.app.db import DB,Run
    ident,outputs=ready_script_run();dispatched=[]
    monkeypatch.setattr(main,'dispatch',lambda:dispatched.append(True))
    assert clients[0].get('/api/v1/runs/'+ident).json()['can_continue'] is True
    response=clients[0].post('/api/v1/runs/'+ident+'/continue')
    assert response.status_code==202 and response.json()['id']==ident
    assert response.json()['can_continue'] is False and dispatched==[True]
    with DB() as db:
        r=db.get(Run,ident)
        assert r.outputs=={**outputs,'_script_only':False}
        assert r.status=='queued' and r.active_owner=='alice' and r.finished is None
        assert orchestration.eligible(r.outputs)==['voice']
    assert clients[0].post('/api/v1/runs/'+ident+'/continue').status_code==409


def test_continue_script_enforces_ownership(clients,monkeypatch):
    from backend.app import main
    ident,_=ready_script_run()
    monkeypatch.setattr(main,'dispatch',lambda:pytest.fail('Unauthorized dispatch'))
    assert clients[1].post('/api/v1/runs/'+ident+'/continue').status_code==404


@pytest.mark.parametrize('case',['review_pending','missing_scenes','old_revision','not_script_only'])
def test_continue_script_rejects_incomplete_or_stale_runs(clients,monkeypatch,case):
    from backend.app import main
    from backend.app.db import DB,Run,Project
    ident,_=ready_script_run()
    with DB() as db:
        r=db.get(Run,ident)
        if case=='review_pending':r.status='waiting_input'
        if case=='missing_scenes':r.outputs={**r.outputs,'script':{'scenes':[]}}
        if case=='old_revision':db.get(Project,r.project_id).revision=2
        if case=='not_script_only':r.outputs={**r.outputs,'_script_only':False}
        db.commit()
    monkeypatch.setattr(main,'dispatch',lambda:pytest.fail('Invalid dispatch'))
    assert clients[0].get('/api/v1/runs/'+ident).json()['can_continue'] is False
    assert clients[0].post('/api/v1/runs/'+ident+'/continue').status_code==409


def test_continue_script_active_run_conflict_rolls_back_stop_flag(clients,monkeypatch):
    from backend.app import main
    from backend.app.db import DB,Run
    from backend.tests.test_agentic import create_run
    ident,outputs=ready_script_run()
    other=create_run()
    with DB() as db:
        db.get(Run,other).active_owner='alice';db.commit()
    monkeypatch.setattr(main,'dispatch',lambda:pytest.fail('Conflicting dispatch'))
    assert clients[0].post('/api/v1/runs/'+ident+'/continue').status_code==409
    with DB() as db:
        r=db.get(Run,ident)
        assert r.status=='script_ready' and r.outputs==outputs and r.finished==123
