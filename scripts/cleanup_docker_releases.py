"""Remove only obsolete Sahne release images, protecting every container image.

Dry-run by default. Volumes, files, networks, build caches and other projects
are never deleted. Supply explicit obsolete IDs for known web releases or this build stage.
"""
import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

PROJECT = 'sosyal_medya_agentic_ai'
REPOS = {f'{PROJECT}-{service}' for service in ('api', 'worker', 'beat', 'web')}


def docker(*args):
    result = subprocess.run(['docker', *args], check=True, capture_output=True, text=True, encoding='utf-8')
    return result.stdout.strip()


def container_images():
    ids = docker('ps', '-aq').splitlines()
    containers = json.loads(docker('inspect', *ids)) if ids else []
    return containers, {container['Image'] for container in containers}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--obsolete-image-id', '--prior-web-id', dest='prior_web_id', action='append', default=[])
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    containers, protected = container_images()
    rows = [json.loads(line) for line in docker('image', 'ls', '--all', '--no-trunc', '--format', '{{json .}}').splitlines()]
    candidates = {}
    for row in rows:
        image_id, repo, tag = row['ID'], row['Repository'], row['Tag']
        if image_id in protected:
            continue
        if not (repo.startswith('sahne-') or repo in REPOS or image_id in args.prior_web_id):
            continue
        item = candidates.setdefault(image_id, {'id': image_id, 'references': [], 'result': 'planned'})
        reference = f'{repo}:{tag}' if repo != '<none>' and tag != '<none>' else image_id
        if reference not in item['references']:
            item['references'].append(reference)
    report = {
        'time_utc': datetime.now(timezone.utc).isoformat(),
        'project': PROJECT,
        'apply': args.apply,
        'protected_container_images': sorted(protected),
        'project_containers': [
            {'name': c['Name'].lstrip('/'), 'image': c['Image'], 'state': c['State']['Status'],
             'mounts': [{'type': m['Type'], 'source': m.get('Name', m['Source']), 'target': m['Destination']} for m in c['Mounts']]}
            for c in containers if c['Config'].get('Labels', {}).get('com.docker.compose.project') == PROJECT
        ],
        'images': list(candidates.values()),
        'scope': 'Obsolete Sahne release images only; no volumes, data, other-project containers/images or build caches.',
    }
    path = Path(args.report)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.apply:
        for item in report['images']:
            _, current_protected = container_images()
            if item['id'] in current_protected:
                raise RuntimeError(f"Refusing to remove a container image: {item['id']}")
            item['output'] = docker('image', 'rm', *item['references'])
            item['result'] = 'removed'
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'apply': args.apply, 'count': len(candidates), 'images': report['images'], 'report': str(path)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
