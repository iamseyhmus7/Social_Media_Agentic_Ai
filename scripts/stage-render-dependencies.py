"""Stage only new, locked pure-JS dependencies over an existing Linux runtime.

The baseline version map must come from the runtime's package-lock.json.
Platform-specific compositors, browser binaries and unchanged dependencies stay
in the verified base image. A full clean build still uses npm ci in backend/Dockerfile.
"""
import json
from pathlib import Path
import shutil
import sys

root = Path(__file__).resolve().parents[1]
stage = Path(sys.argv[1]).resolve()
base = json.loads((stage / 'base-package-versions.json').read_text(encoding='utf-8-sig'))
production = root / 'remotion/production'
packages = json.loads((production / 'package-lock.json').read_text(encoding='utf-8'))['packages']
changed = [name for name, item in packages.items() if name and name in base and base[name] != item['version']]
if changed:
    raise SystemExit('Existing runtime dependency versions changed: ' + ', '.join(changed))
new = [name for name in packages if name and name not in base]
parents = [name for name in new if not any(name.startswith(other + '/') for other in new if other != name)]
def copy_changed(source, destination):
    existing = Path(destination)
    original = Path(source).stat()
    if not existing.is_file() or (existing.stat().st_size, existing.stat().st_mtime_ns) != (original.st_size, original.st_mtime_ns):
        shutil.copy2(source, destination)
    return str(destination)


for name in parents:
    source = production / name
    if packages[name].get('os') or packages[name].get('cpu') or list(source.rglob('*.node')):
        raise SystemExit('Native dependency requires a Linux installation: ' + name)
    actual = json.loads((source / 'package.json').read_text(encoding='utf-8'))['version']
    if actual != packages[name]['version']:
        raise SystemExit('Installed package differs from lock: ' + name)
    destination = stage / 'dependencies' / name.removeprefix('node_modules/')
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, dirs_exist_ok=True, copy_function=copy_changed)
(stage / 'dependency-versions.json').write_text(json.dumps({name: packages[name]['version'] for name in new}, indent=2))
print(f'Staged {len(new)} locked dependency entries; existing runtime versions unchanged.')
