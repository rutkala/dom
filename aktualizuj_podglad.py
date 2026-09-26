"""Odtwarza samodzielny HTML po zmianie geometrii."""
import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
source = json.loads((ROOT / 'dane_zrodlowe.json').read_text(encoding='utf-8'))

geo_file = ROOT / 'geoportal_teren.json'
M = None
if geo_file.exists():
    try:
        geo = json.loads(geo_file.read_text(encoding='utf-8'))
        M = geo.get('alignment', {}).get('house_calibration', {}).get('model_to_geo_local_affine_mm')
    except Exception:
        pass

rooms = []
for r in source['rooms']:
    pts = r['floor_reference_polygon_mm']
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    if M:
        gx = (M[0][0]*cx + M[0][1]*cy + M[0][2]) / 1000.0
        gy = (M[1][0]*cx + M[1][1]*cy + M[1][2]) / 1000.0
    else:
        gx = cx / 1000.0
        gy = cy / 1000.0
    rooms.append({'x': round(gx, 4), 'y': round(gy, 4), 'number': r['number'], 'name': r['name']})

s = (ROOT / 'podglad_szablon.html').read_text(encoding='utf-8')
s = s.replace('__SCENE__', (ROOT / 'scena_modelu.json').read_text(encoding='utf-8').replace('</', '<\\/'))
s = s.replace('__ROOM_LABELS__', json.dumps(rooms, ensure_ascii=False))
ortho = (ROOT / 'geoportal_ortho.jpg')
s = s.replace('__ORTHO_JPG__', base64.b64encode(ortho.read_bytes()).decode() if ortho.exists() else '')
for marker, f in [('__GLB_INTERIOR__', 'dom_wnetrze.glb'), ('__GLB_EXTERIOR__', 'dom_bryla.glb')]:
    f_path = ROOT / f
    if f_path.exists():
        s = s.replace(marker, base64.b64encode(f_path.read_bytes()).decode())
    else:
        s = s.replace(marker, '')

(ROOT / 'podglad_3d.html').write_text(s, encoding='utf-8')
(ROOT / 'index.html').write_text(s, encoding='utf-8')
print('Zaktualizowano podglad_3d.html i index.html')
