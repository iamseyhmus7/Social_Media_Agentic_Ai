"""Bounded, read-only snapshot of one owned Kaggle job; never prints credentials."""
import os
import subprocess
import sys
from pathlib import Path
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
values = dotenv_values(root / '.env')
ref = sys.argv[1]
if not ref.startswith(values.get('KAGGLE_USERNAME', '') + '/'):
    raise SystemExit('Only configured-account jobs can be inspected.')
environment = dict(os.environ)
for name in ('KAGGLE_USERNAME', 'KAGGLE_API_TOKEN', 'KAGGLE_KEY'):
    if values.get(name):
        environment[name] = values[name]
reader = '''
import json,sys
from kaggle.api.kaggle_api_extended import KaggleApi
try:
    api=KaggleApi();api.authenticate()
    print('STATUS',api.kernels_status(sys.argv[1]),flush=True)
    for event in api.kernels_logs_stream(sys.argv[1]):
        if event.get('data','').startswith('\\r'):
            continue
        print(json.dumps(event,ensure_ascii=True),flush=True)
except Exception as exc:
    print('Log transport:',type(exc).__name__,flush=True)
'''
try:
    output = subprocess.run([sys.executable, '-u', '-c', reader, ref], cwd=root,
                            env=environment, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=25).stdout
except subprocess.TimeoutExpired as exc:
    output = exc.stdout or b''
print(output.decode('utf-8', errors='replace')[-24000:])
