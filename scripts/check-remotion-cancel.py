"""Exercise the real renderer cancellation without changing any production run."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

folder = Path(sys.argv[1]).resolve()
probe = folder / 'cancel-check'
probe.mkdir(exist_ok=True)
(probe / 'render-metrics.json').unlink(missing_ok=True)


def chrome_pids():
    result = set()
    for item in Path('/proc').glob('[0-9]*/cmdline'):
        try:
            if item.read_bytes().split(b'\0')[0].endswith(b'chrome-headless-shell'):
                result.add(item.parent.name)
        except (FileNotFoundError, ProcessLookupError):
            pass
    return result


before = chrome_pids()
with (probe / 'renderer.log').open('wb') as log:
    process = subprocess.Popen(['node', '/app/remotion/production/render.mjs',
                                str(folder / 'render-manifest.json'), str(folder / 'render-inputs'),
                                str(probe / 'probe.mp4')], stdout=log, stderr=log, start_new_session=True)
    try:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            metrics_path = probe / 'render-metrics.json'
            metrics = json.loads(metrics_path.read_text()) if metrics_path.exists() else {}
            if metrics.get('rendered_frames', 0) >= 3:
                break
            if process.poll() is not None:
                raise RuntimeError('Renderer exited before the cancellation probe.')
            time.sleep(0.2)
        else:
            raise RuntimeError('Renderer did not reach frame processing in the bounded probe.')
        start = time.monotonic()
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=10)
        metrics = json.loads(metrics_path.read_text())
        leaked = chrome_pids() - before
        assert metrics.get('cancelled') is True, metrics
        assert not leaked, f'Browser processes remained: {leaked}'
        print(json.dumps({'cancelled': True, 'shutdown_seconds': round(time.monotonic() - start, 3),
                          'new_browser_processes_remaining': len(leaked), 'processed_frames': metrics['rendered_frames']}))
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
