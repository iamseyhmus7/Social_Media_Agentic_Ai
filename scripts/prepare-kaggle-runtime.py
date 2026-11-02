"""One-time server-side provisioning; users never open notebook cells."""
import json
import os
import shutil
from pathlib import Path
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
values = dotenv_values(root / '.env')
for key in ('KAGGLE_USERNAME', 'KAGGLE_API_TOKEN', 'KAGGLE_KEY'):
    if values.get(key):
        os.environ[key] = values[key]
from kaggle.api.kaggle_api_extended import KaggleApi
api = KaggleApi()
api.authenticate()
folder = root / 'data/kaggle-runtime'
folder.mkdir(parents=True, exist_ok=True)
slug = 'sahne-ltx-096-v1'
ref = values['KAGGLE_USERNAME'] + '/' + slug
receipt = folder / 'receipt.json'
if receipt.exists():
    saved = json.loads(receipt.read_text())
    status = api.kernels_status(ref + '/' + str(saved['version']))
    print('Runtime:', str(status.status))
else:
    shutil.copyfile(root / 'backend/kaggle/prepare_runtime.py', folder / 'prepare.py')
    (folder / 'kernel-metadata.json').write_text(json.dumps({'id': ref, 'title': slug, 'code_file': 'prepare.py', 'language': 'python', 'kernel_type': 'script', 'is_private': True, 'enable_gpu': False, 'enable_internet': True, 'dataset_sources': [], 'kernel_sources': [], 'model_sources': []}))
    # Write intent before submitting so a lost response cannot silently duplicate.
    receipt.write_text(json.dumps({'kernel': ref, 'version': None, 'status': 'submitting'}))
    response = api.kernels_push(str(folder), timeout='7200')
    version = getattr(response, 'version_number', None)
    receipt.write_text(json.dumps({'kernel': ref, 'version': version, 'status': 'submitted'}))
    print('Runtime submitted:', ref, 'version:', version)
