"""Embed the installed OFL font so rendering needs no font CDN."""
import base64
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
source = root / 'frontend/node_modules/@fontsource/playfair-display'
css = (source / '700.css').read_text(encoding='utf-8')
faces = []
for subset in ('latin-ext', 'latin'):
    block = re.search(r'/\* playfair-display-' + subset + r'-700-normal \*/\s*(@font-face \{.*?\})', css, re.S)[1]
    name = f'playfair-display-{subset}-700-normal.woff2'
    encoded = base64.b64encode((source / 'files' / name).read_bytes()).decode()
    block = block.replace('Playfair Display', 'Sahne Serif').replace('font-display: swap;', 'font-display: block;')
    block = re.sub(r'src:.*?;', f"src: url(data:font/woff2;base64,{encoded}) format('woff2');", block)
    faces.append(block)
target = root / 'remotion/production/serif-font.mjs'
target.write_text('// Playfair Display 700, OFL. Regenerate: python scripts/build-serif-font.py\nexport default ' + json.dumps('\n'.join(faces)) + ';\n', encoding='utf-8')
licenses = root / 'remotion/production/licenses'
licenses.mkdir(exist_ok=True)
(licenses / 'Playfair-Display-OFL.txt').write_text((source / 'LICENSE').read_text(encoding='utf-8'), encoding='utf-8')
