"""The same catalog is bundled into the web app and the production worker."""
import json
from pathlib import Path

AGENTS = json.loads((Path(__file__).resolve().parents[2] / 'shared' / 'agents.json').read_text(encoding='utf-8'))
LABELS = {agent['id']: agent['name'] for agent in AGENTS} | {'quality': 'Kalite kontrolü'}
LEGACY_STAGES = ['supervisor', 'strategy', 'script', 'voice', 'visual', 'editor', 'quality', 'publisher']
STAGES = ['supervisor', 'strategy', 'script', 'voice', 'visual', 'motion', 'editor', 'quality', 'publisher']
