"""Linux-only, isolated local render benchmark; never calls model/GPU APIs.

Run inside the provisioned worker. Inputs are read-only; all output goes to a
new directory. Sampled CPU is a lower bound for very short-lived processes.
PSS avoids counting shared Chromium pages multiple times; RSS is also reported.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import statistics
import subprocess
import time


def snapshot():
    result = {}
    for directory in Path('/proc').iterdir():
        if not directory.name.isdigit():
            continue
        try:
            raw = (directory / 'stat').read_text()
            fields = raw[raw.rfind(')') + 2:].split()
            cmd = (directory / 'cmdline').read_bytes().replace(b'\0', b' ').decode(errors='replace')
            result[int(directory.name)] = {
                'ppid': int(fields[1]), 'session': int(fields[3]),
                'ticks': int(fields[11]) + int(fields[12]),
                'identity': fields[19], 'cmd': cmd,
                'rss_mib': int(fields[21]) * os.sysconf('SC_PAGE_SIZE') / 1048576,
            }
        except (OSError, ValueError, IndexError):
            pass
    return result


def category(cmd):
    executable = cmd.split(' ', 1)[0].lower()
    if 'ffmpeg' in executable:
        return 'ffmpeg'
    if 'compositor' in executable:
        return 'compositor'
    if 'chrome' in executable or 'chromium' in executable:
        return 'chromium'
    if Path(executable).name == 'node':
        return 'node'
    return 'other'


def pss(pid):
    try:
        for line in Path(f'/proc/{pid}/smaps_rollup').read_text().splitlines():
            if line.startswith('Pss:'):
                return int(line.split()[1]) / 1024
    except OSError:
        pass
    return None


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--part', type=Path, required=True)
    parser.add_argument('--public', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--renderer', type=Path, default=Path('/app/remotion/production/render.mjs'))
    parser.add_argument('--browser', default='')
    parser.add_argument('--concurrency', type=int, default=2, choices=range(1, 5))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    inputs = {name: sha(args.part / name) for name in ('manifest.json', 'render-range.json', 'video.mp4')}
    report = {'sample_interval_seconds': .5, 'logical_cpus': os.cpu_count(),
              'notes': ['Per-category CPU sampled lower bound; short-lived children may be missed.',
                        'Category memory peaks occur at different times; do not add them.',
                        'Warm bundle, unchanged render inputs, no model or GPU generation calls.'],
              'input_hashes': inputs, 'runs': []}
    report_path = args.output / 'report.json'
    hz = os.sysconf('SC_CLK_TCK')
    for index in range(4):
        folder = args.output / ('warmup' if index == 0 else f'measured-{index}')
        folder.mkdir()
        for name in ('manifest.json', 'render-range.json'):
            shutil.copyfile(args.part / name, folder / name)
        command = ['node', str(args.renderer), str(folder / 'manifest.json'),
                   str(args.public), str(folder / 'video.mp4'), args.browser, 'chunk', str(args.concurrency)]
        samples, seen, cpu, peaks = [], {}, {}, {}
        started = time.monotonic()
        with (folder / 'render.log').open('w') as log:
            proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                while True:
                    processes = snapshot()
                    owned = {proc.pid} | {pid for pid, item in processes.items()
                        if (pid, item['identity']) in seen}
                    while True:
                        descendants = {pid for pid, item in processes.items() if item['ppid'] in owned}
                        if descendants <= owned:
                            break
                        owned |= descendants
                    if any(pid != proc.pid and item['session'] != proc.pid
                           and 'production/render.mjs' in item['cmd']
                           and category(item['cmd']) == 'node' for pid, item in processes.items()):
                        raise RuntimeError('Production render became active; benchmark stopped to avoid contention.')
                    if time.monotonic() - started > 180:
                        raise RuntimeError('Bounded benchmark timed out.')
                    groups = {}
                    for pid, item in processes.items():
                        if pid not in owned:
                            continue
                        name = category(item['cmd'])
                        key = (pid, item['identity'])
                        previous = seen.get(key, 0)
                        cpu[name] = cpu.get(name, 0) + max(0, item['ticks'] - previous) / hz
                        seen[key] = item['ticks']
                        group = groups.setdefault(name, {'rss_mib': 0, 'pss_mib': 0, 'processes': 0, 'pss_unavailable': 0})
                        group['rss_mib'] += item['rss_mib']
                        value = pss(pid)
                        group['pss_mib'] += value or 0
                        group['pss_unavailable'] += value is None
                        group['processes'] += 1
                    for name, group in groups.items():
                        peak = peaks.setdefault(name, {'rss_mib': 0, 'pss_mib': 0})
                        for field in peak:
                            peak[field] = max(peak[field], group[field])
                    samples.append({'seconds': round(time.monotonic() - started, 3), 'groups': groups})
                    if proc.poll() is not None:
                        break
                    time.sleep(.5)
            finally:
                # Only the benchmark's private process group can be terminated.
                if proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGTERM)
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait()
        (folder / 'samples.json').write_text(json.dumps(samples, indent=2))
        if proc.returncode:
            raise RuntimeError(f'Render exited {proc.returncode}; see {folder}/render.log')
        probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-count_frames',
            '-show_streams', '-of', 'json', str(folder / 'video.mp4')]))
        video = next(stream for stream in probe['streams'] if stream['codec_type'] == 'video')
        span = json.loads((folder / 'render-range.json').read_text())
        assert (video['width'], video['height'], video['avg_frame_rate'], int(video['nb_read_frames'])) == (
            1080, 1920, '30/1', span['end_frame'] - span['start_frame'] + 1)
        metrics = json.loads((folder / 'render-metrics.json').read_text())
        row = {'warmup': index == 0, 'elapsed_seconds': round(time.monotonic() - started, 3),
               'metrics': metrics, 'sampled_cpu_seconds': cpu, 'peak_memory_mib': peaks,
               'peak_combined_pss_mib': max(sum(g['pss_mib'] for g in s['groups'].values()) for s in samples),
               'sample_count': len(samples), 'output_sha256': sha(folder / 'video.mp4'), 'technical_check': 'passed'}
        report['runs'].append(row)
        report_path.write_text(json.dumps(report, indent=2))
        print(json.dumps(row), flush=True)
    assert inputs == {name: sha(args.part / name) for name in inputs}, 'Source inputs changed'
    measured = report['runs'][1:]
    report['median_render_seconds'] = statistics.median(r['metrics']['render_seconds'] for r in measured)
    report['source_unchanged'] = True
    report_path.write_text(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
