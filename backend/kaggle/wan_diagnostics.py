"""Dependency-free, bounded progress and resource logs for finite Wan workers."""
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import traceback


def safe_text(value, limit=4096):
    return re.sub(r'https?://[^\s<>"\x27]+','[url]',str(value))[:limit]


class Diagnostics:
    def __init__(self, output, interval=30):
        self.output=Path(output);self.started=time.monotonic();self.phase='starting'
        self.interval=interval;self.process=None;self.stopped=threading.Event();self.thread=None
        self.phase_started=self.started;self.timings={}
        self.previous_cpu=None
        self.graph_nodes={};self.current_node=None;self.events_thread=None;self.events_ready=threading.Event()

    def phase_durations(self):
        result=dict(self.timings)
        result[self.phase]=result.get(self.phase,0)+round(time.monotonic()-self.phase_started,3)
        return result

    def emit(self, event, **values):
        record={'event':event,'phase':self.phase,'elapsed_seconds':round(time.monotonic()-self.started,2),**values}
        line=json.dumps(record,ensure_ascii=False)
        print('[Sahne] '+line,flush=True)

    def set_phase(self, phase, **values):
        instant=time.monotonic()
        self.timings[self.phase]=self.timings.get(self.phase,0)+round(instant-self.phase_started,3)
        self.phase=phase;self.phase_started=instant
        self.emit('phase',**values)

    def failure(self, exc):
        error={'phase':self.phase,'exception_type':type(exc).__name__,
               'message':safe_text(exc,2048),'elapsed_seconds':round(time.monotonic()-self.started,2)}
        self.emit('error',**{k:v for k,v in error.items() if k!='phase'})
        print('[Sahne traceback] '+safe_text(''.join(traceback.format_exception(type(exc),exc,exc.__traceback__)),16384),flush=True)
        return error

    def sample(self):
        values={'node_type':self.current_node}
        try:
            memory={line.split(':')[0]:int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines() if ':' in line and line.split()[1].isdigit()}
            values.update(host_available_mib=memory.get('MemAvailable',0)//1024,
                          swap_used_mib=(memory.get('SwapTotal',0)-memory.get('SwapFree',0))//1024)
            pid=self.process.pid if self.process is not None else os.getpid()
            process={line.split(':')[0]:line.split(':',1)[1].strip() for line in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line}
            values['process_rss_mib']=int(process.get('VmRSS','0').split()[0])//1024
            io={line.split(':')[0]:int(line.split(':')[1]) for line in Path(f'/proc/{pid}/io').read_text().splitlines()}
            values['process_io']=io
            fields=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
            cpu_seconds=(int(fields[11])+int(fields[12]))/os.sysconf('SC_CLK_TCK')
            instant=time.monotonic()
            if self.previous_cpu and self.previous_cpu[0]==pid:
                values['process_cpu_percent']=round(100*(cpu_seconds-self.previous_cpu[1])/max(.001,instant-self.previous_cpu[2]),1)
            self.previous_cpu=(pid,cpu_seconds,instant)
            # Report both cards separately; only GPU 0 is selected by this profile.
            result=subprocess.run(['nvidia-smi','--query-gpu=index,name,utilization.gpu,memory.used,memory.total',
                '--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=5)
            values['gpus']=[line.strip() for line in result.stdout.splitlines()][:8]
            values['selected_gpu']=0
        except Exception as exc:
            values['resource_probe_error']=type(exc).__name__
        self.emit('resources',**values)

    def start(self):
        def monitor():
            while not self.stopped.is_set():
                self.sample()
                self.stopped.wait(self.interval)
        self.thread=threading.Thread(target=monitor,name='wan-resource-log',daemon=True)
        self.thread.start()

    def node_event(self, message):
        kind=message.get('type');data=message.get('data',{})
        if not isinstance(data,dict):return
        if kind=='executing':
            node=data.get('node')
            self.current_node=self.graph_nodes.get(str(node)) if node is not None else None
            self.emit('node_start' if node is not None else 'graph_done',node_id=node,node_type=self.current_node)
        elif kind=='progress':
            self.emit('sampling_progress',node_type=self.current_node,value=data.get('value'),total=data.get('max'))
        elif kind=='execution_error':
            self.emit('node_error',node_type=data.get('node_type'),exception_type=data.get('exception_type'),
                      message=safe_text(data.get('exception_message',''),2048))

    def observe_nodes(self):
        # The same client_id is used by /prompt. This observes Comfy's own
        # executing/progress events; it does not alter the graph or sampler.
        def observe():
            import asyncio
            async def listen():
                import aiohttp
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=None,sock_connect=3)) as session:
                    async with session.ws_connect('http://127.0.0.1:8188/ws?clientId=sahne',max_msg_size=4*1024*1024) as socket:
                        self.events_ready.set()
                        while not self.stopped.is_set():
                            try: message=await socket.receive(timeout=2)
                            except asyncio.TimeoutError:continue
                            if message.type==aiohttp.WSMsgType.TEXT:
                                try:self.node_event(json.loads(message.data))
                                except (ValueError,TypeError):continue
                            elif message.type in (aiohttp.WSMsgType.CLOSED,aiohttp.WSMsgType.ERROR):break
            try:asyncio.run(listen())
            except Exception as exc:self.emit('node_observer_unavailable',exception_type=type(exc).__name__)
            finally:self.events_ready.set()
        self.events_thread=threading.Thread(target=observe,name='wan-node-progress',daemon=True)
        self.events_thread.start()
        self.events_ready.wait(timeout=4)

    def mirror(self, process):
        self.process=process
        def forward():
            path=self.output/'comfy.log'
            with path.open('a',encoding='utf-8') as target:
                for line in process.stdout:
                    text=safe_text(line)
                    if path.stat().st_size>2*1024*1024:
                        target.seek(0);target.truncate();target.write('[Earlier Comfy log truncated]\n')
                    target.write(text);target.flush()
                    print('[ComfyUI] '+text.rstrip(),flush=True)
        thread=threading.Thread(target=forward,name='wan-comfy-log',daemon=True)
        thread.start()
        return thread

    def close(self):
        self.stopped.set()
        if self.thread:self.thread.join(timeout=6)
        if self.events_thread:self.events_thread.join(timeout=3)
        self.emit('finished',phase_timings=self.phase_durations())
