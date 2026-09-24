"""Odtwarza samodzielny HTML po zmianie geometrii (Python + Shapely)."""
import base64
import json
from pathlib import Path
from shapely.geometry import Polygon
ROOT=Path(__file__).resolve().parent
source=json.loads((ROOT/'dane_zrodlowe.json').read_text(encoding='utf-8'))
rooms=[]
for r in source['rooms']:
    p=Polygon(r['floor_reference_polygon_mm']).representative_point()
    rooms.append({'x':p.x/1000,'y':p.y/1000,'number':r['number'],'name':r['name']})
s=(ROOT/'podglad_szablon.html').read_text(encoding='utf-8')
s=s.replace('__SCENE__',(ROOT/'scena_modelu.json').read_text(encoding='utf-8').replace('</','<\\/'))
s=s.replace('__ROOM_LABELS__',json.dumps(rooms,ensure_ascii=False))
for marker,f in [('__GLB_INTERIOR__','dom_wnetrze.glb'),('__GLB_EXTERIOR__','dom_bryla.glb')]:
    s=s.replace(marker,base64.b64encode((ROOT/f).read_bytes()).decode())
(ROOT/'podglad_3d.html').write_text(s,encoding='utf-8')
(ROOT/'index.html').write_text(s,encoding='utf-8')
print('Zaktualizowano podglad_3d.html i index.html')
