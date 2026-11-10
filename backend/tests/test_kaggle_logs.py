from contextlib import nullcontext
import io
import json
import logging
from types import SimpleNamespace
import pytest
from requests.exceptions import ConnectionError
from backend.app import kaggle_logs as logs


class Response:
    def __init__(self,text,content_type='text/event-stream',timeout=False):
        self.data=text.encode();self.headers={'Content-Type':content_type};self.timeout=timeout;self.closed=False
    def iter_content(self,chunk_size=1):
        for i in range(0,len(self.data),chunk_size):yield self.data[i:i+chunk_size]
        if self.timeout:raise ConnectionError('quiet connection')
    def close(self):self.closed=True


def sse(*records):
    return ''.join('data: '+json.dumps(r)+'\n\n' for r in records)


def test_partial_live_stream_preserves_complete_unicode_events_on_timeout():
    response=Response(': heartbeat\n\n'+sse({'time':1,'data':'GPU hazır\n'})+'data: {"data":"partial',timeout=True)
    assert list(logs.read_records(response))==[{'time':1,'data':'GPU hazır\n'}]
    assert list(logs.read_records(Response(sse({'data':'ready'})+'data: END_OF_LOG\n\n'+sse({'data':'ignored'}))))==[{'data':'ready'}]


def test_terminal_json_and_replay_size_bound():
    assert list(logs.read_records(Response('[{"data":"done"}]','application/json')))==[{'data':'done'}]
    with pytest.raises(ValueError,match='byte limit'):
        list(logs.read_records(Response('x'*30),max_bytes=20))


def test_preview_transport_resumes_chunks_and_keeps_video_bytes_out_of_logs(tmp_path,monkeypatch,caplog):
    import base64
    import hashlib
    job=SimpleNamespace(id='job',run_id='run',kernel='owner/kernel',version=3)
    cfg=SimpleNamespace(kaggle_username='owner',model_dump=lambda:{})
    api=SimpleNamespace(build_kaggle_client=lambda:nullcontext(object()))
    inputs=tmp_path/'inputs'
    inputs.mkdir()
    shot='shot-000'
    (inputs/'wan-request.json').write_text(json.dumps({'shots':[{'shot_id':shot,'duration_seconds':3.5}]}))
    video=b'\x00\x00\x00\x20ftyp'+b'preview'*400
    digest=hashlib.sha256(video).hexdigest()
    chunks=[video[:2048],video[2048:]]
    def packet(index,part):
        return {'data':logs.PREVIEW_PREFIX+json.dumps({'shot_id':shot,'sha256':digest,'index':index,
            'total':2,'data':base64.b64encode(part).decode()})}
    # A preview cannot precede its shot's verified completion event.
    assert logs.receive_preview(tmp_path,packet(0,chunks[0])['data'],{shot:{}},set()) is None
    records=[{'data':'[Sahne] '+json.dumps({'event':'clip_ready','shot_id':shot})},packet(0,chunks[0])]
    published=[]
    monkeypatch.setattr(logs,'resolve_session',lambda *args:123)
    monkeypatch.setattr(logs,'send',lambda *a,**k:Response(sse(*records),timeout=True))
    monkeypatch.setattr(logs,'publish_clip_previews',
        lambda job,folder,shots,ready,previews:published.append((set(ready),dict(previews))))
    logs.sync_logs(api,job,tmp_path,'running',cfg)
    assert published==[({shot},{})]
    state_path=tmp_path/'remote-log-state.json'
    state=json.loads(state_path.read_text())
    state.update(cursor=0,next_read=0)  # replay the first binary chunk after a crash
    state_path.write_text(json.dumps(state))
    records.append(packet(1,chunks[1]))
    logs.sync_logs(api,job,tmp_path,'running',cfg)
    assert published[-1][1][shot].read_bytes()==video
    assert 'SahnePreview' not in caplog.text
    assert 'SahnePreview' not in (tmp_path/'remote.log.jsonl').read_text()


def test_mirror_redacts_and_resumes_without_reprinting_after_restart(tmp_path,monkeypatch,caplog):
    job=SimpleNamespace(id='job',run_id='run',kernel='owner/kernel',version=3)
    cfg=SimpleNamespace(kaggle_username='owner',model_dump=lambda:{'kaggle_api_token':'very-private-token'})
    api=SimpleNamespace(build_kaggle_client=lambda:nullcontext(object()))
    seen=[];responses=[]
    def resolve(client,kernel,owner):
        seen.append((kernel,owner));return 123
    monkeypatch.setattr(logs,'resolve_session',resolve)
    records=[{'time':1,'stream_name':'stderr','data':'\x1b[31mGPU ready very-private-token https://example.test/?key=hide\x1b[0m\n'}]
    def send(client,method,request,**kwargs):
        assert request.kernel_session_id==123
        response=Response(sse(*records),timeout=True);responses.append(response);return response
    monkeypatch.setattr(logs,'send',send)
    caplog.set_level(logging.INFO,logger=logs.__name__)
    logs.sync_logs(api,job,tmp_path,'running',cfg)
    # Simulate a crash after JSONL append, before the cursor state was saved.
    state=json.loads((tmp_path/'remote-log-state.json').read_text())
    state.update(cursor=0,next_read=0)
    (tmp_path/'remote-log-state.json').write_text(json.dumps(state))
    records.append({'time':2,'data':'sample 1/20\n'})
    logs.sync_logs(api,job,tmp_path,'running',cfg)
    lines=[json.loads(line) for line in (tmp_path/'remote.log.jsonl').read_text().splitlines()]
    assert [line['index'] for line in lines]==[0,1]
    assert caplog.text.count('GPU ready')==1 and caplog.text.count('sample 1/20')==1
    assert 'very-private-token' not in caplog.text and 'example.test' not in caplog.text and '\x1b' not in caplog.text
    assert seen==[('owner/kernel/3','owner')] and all(r.closed for r in responses)


def test_log_outage_is_nonfatal_and_never_leaks_exception_text(tmp_path,monkeypatch,caplog):
    job=SimpleNamespace(id='job',run_id='run',kernel='owner/kernel',version=1)
    cfg=SimpleNamespace(kaggle_username='owner',model_dump=lambda:{})
    api=SimpleNamespace(build_kaggle_client=lambda:nullcontext(object()))
    def fail(*args):raise RuntimeError('credential-do-not-print')
    monkeypatch.setattr(logs,'resolve_session',fail)
    logs.sync_logs(api,job,tmp_path,'running',cfg)
    assert 'credential-do-not-print' not in caplog.text
    assert json.loads((tmp_path/'remote-log-state.json').read_text())['error']=='RuntimeError'


def test_log_resolution_is_version_bound_and_closes_output_stream(monkeypatch):
    captured=[]
    response=SimpleNamespace(history=[],url='https://api.kaggle.com/v1/kernels/output/download_zip/321',
                             close=lambda:captured.append('closed'))
    def send(client,method,request):
        captured.append((method,request.owner_slug,request.kernel_slug,request.version_number));return response
    monkeypatch.setattr(logs,'send',send)
    assert logs.resolve_session(object(),'owner/kernel/4','owner')==321
    assert captured==[('DownloadKernelOutput','owner','kernel',4),'closed']
    for invalid in ('other/kernel/4','owner/kernel','owner/../4'):
        with pytest.raises(ValueError):logs.resolve_session(object(),invalid,'owner')


def test_runtime_progress_and_comfy_output_are_visible_and_persisted(tmp_path,capsys):
    from backend.kaggle.wan_diagnostics import Diagnostics
    diag=Diagnostics(tmp_path)
    diag.set_phase('high_noise_sampling')
    process=SimpleNamespace(pid=123,stdout=io.StringIO('loaded model\n1/20 sample\n'))
    thread=diag.mirror(process);thread.join(timeout=2)
    assert not thread.is_alive()
    failure=diag.failure(RuntimeError('bad node https://example.test/private?token=hidden'))
    diag.close()
    output=capsys.readouterr().out
    assert '[ComfyUI] 1/20 sample' in output and 'high_noise_sampling' in output
    assert 'example.test' not in output
    assert failure['exception_type']=='RuntimeError'
    assert '1/20 sample' in (tmp_path/'comfy.log').read_text()


def test_comfy_nodes_distinguish_cpu_text_encoding_from_actual_sampling(tmp_path,capsys):
    from backend.kaggle.wan_diagnostics import Diagnostics
    diag=Diagnostics(tmp_path)
    diag.graph_nodes={'4':'CLIPTextEncode','9':'KSamplerAdvanced'}
    diag.node_event({'type':'executing','data':{'node':'4'}})
    assert diag.current_node=='CLIPTextEncode'
    diag.node_event({'type':'executing','data':{'node':'9'}})
    diag.node_event({'type':'progress','data':{'value':1,'max':20}})
    output=capsys.readouterr().out
    assert 'CLIPTextEncode' in output and 'KSamplerAdvanced' in output
    assert 'sampling_progress' in output and '"value": 1' in output
