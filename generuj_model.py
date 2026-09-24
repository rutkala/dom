#!/usr/bin/env python3
"""Geometryczny model roboczy domu z danych wektorowych PDF.

Uruchomienie: python generuj_model.py
Wymagania: cadquery, shapely, trimesh, numpy.
Dane źródłowe pozostają niezmienione. Założenia są w parametry_modelu.json.
Jednostki: CAD / STEP = mm; GLB / OBJ = m.
"""
from __future__ import annotations
import base64
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import cadquery as cq
import numpy as np
import trimesh
from shapely.geometry import Polygon, MultiPolygon, GeometryCollection, box
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent
DATA = json.loads((ROOT / 'dane_zrodlowe.json').read_text(encoding='utf-8'))
PARAM = json.loads((ROOT / 'parametry_modelu.json').read_text(encoding='utf-8'))
ROOF = json.loads((ROOT / 'obrys_dachu_z_pdf.json').read_text(encoding='utf-8'))

COLORS = {
    'sciany': [0.84,0.83,0.80,1.0],
    'izolacja': [0.93,0.92,0.88,1.0],
    'uzupelnienia': [0.84,0.83,0.80,1.0],
    'podlogi': [0.66,0.66,0.64,1.0],
    'progi': [0.66,0.66,0.64,1.0],
    'stolarka': [0.27,0.31,0.33,1.0],
    'szklo': [0.58,0.74,0.79,0.35],
    'drzwi': [0.59,0.57,0.53,1.0],
    'strop': [0.72,0.73,0.74,1.0],
    'dach': [0.38,0.41,0.43,1.0],
    'attyka': [0.91,0.90,0.86,1.0],
    'sufity': [0.94,0.94,0.92,1.0],
}
GROUP_NAMES = {
    'sciany': '01_SCIANY_RDZENIE',
    'uzupelnienia': '02_SCIANY_POD_I_NAD_OTWORAMI',
    'izolacja': '03_IZOLACJA_ZEWNETRZNA',
    'podlogi': '04_PODLOGI_POWIERZCHNIE_ODNIESIENIA',
    'stolarka': '05_STOLARKA_SCHEMATYCZNA',
    'strop': '06_STROP',
    'dach': '07_DACH_UPROSZCZONY',
    'sufity': '08_SUFITY_POWIERZCHNIE_ODNIESIENIA',
}
parts: list[dict[str, Any]] = []
shapes: dict[str, cq.Shape] = {}
meshes: dict[str, trimesh.Trimesh] = {}
used_names: set[str] = set()


def ascii_name(value: str) -> str:
    value = value.translate(str.maketrans({'ł':'l','Ł':'L'}))
    value = unicodedata.normalize('NFKD',value).encode('ascii','ignore').decode()
    return re.sub(r'[^a-zA-Z0-9_]+','_',value).strip('_')


def polygons(geometry):
    if geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry] if geometry.area > 0.1 else []
    if isinstance(geometry, (MultiPolygon, GeometryCollection)):
        return [p for child in geometry.geoms for p in polygons(child)]
    return []


def shape_from_polygon(p: Polygon, z0: float, z1: float | None) -> cq.Shape:
    """Dokładne proste krawędzie, bez rasteryzacji lub skalowania rzutu."""
    if not p.is_valid:
        raise ValueError('Nieprawidłowy wielokąt: nie naprawiam danych automatycznie.')
    p = orient(p, sign=1.0)
    outer = cq.Wire.makePolygon([(float(x),float(y),z0) for x,y in list(p.exterior.coords)[:-1]], close=True)
    holes = [cq.Wire.makePolygon([(float(x),float(y),z0) for x,y in list(r.coords)[:-1]],close=True) for r in p.interiors]
    if z1 is None:
        return cq.Face.makeFromWires(outer,holes)
    if z1 <= z0:
        raise ValueError(f'Niedodatnia wysokość: {z0}, {z1}')
    return cq.Solid.extrudeLinear(outer,holes,(0,0,z1-z0))


def add(name: str, category: str, material: str, geometry, z0: float, z1: float | None,
        source: str, assumed: bool=False, note: str='', source_id: str='', extras: dict | None=None):
    polys = polygons(geometry)
    for number,p in enumerate(polys,1):
        nm = ascii_name(name + (f'_{number:02}' if len(polys)>1 else ''))
        if nm in used_names:
            raise ValueError(f'Powtórzona nazwa {nm}')
        used_names.add(nm)
        shape = shape_from_polygon(p,z0,z1)
        if not shape.isValid():
            raise ValueError(f'Nieprawidłowy BREP: {nm}')
        vertices, faces = shape.tessellate(0.05,0.1)
        mesh = trimesh.Trimesh(vertices=np.array([[v.x,v.y,v.z] for v in vertices])/1000.0,
                               faces=np.asarray(faces),process=True)
        if z1 is not None:
            if mesh.volume < 0:
                mesh.invert()
            if not mesh.is_watertight or not mesh.is_winding_consistent:
                raise ValueError(f'Nieszczelna siatka: {nm}')
        record = {'name':nm,'category':category,'material':material,'color':COLORS[material],
            'source':source,'source_id':source_id,'assumed':assumed,'note':note,
            'z_bottom_mm':z0,'z_top_mm':z1,'plan_area_m2':round(p.area/1e6,6),
            'geometry':'face' if z1 is None else 'solid',
            'valid_brep':True,'watertight_mesh':bool(mesh.is_watertight),
            'bbox_mm':[[round(float(v)*1000,3) for v in row] for row in mesh.bounds],
            'volume_m3':round(float(mesh.volume),9) if z1 is not None else None,
            'vertices':len(mesh.vertices),'triangles':len(mesh.faces),
            'default_visible':category not in ['strop','dach','sufity']}
        if extras:
            record.update(extras)
        parts.append(record)
        shapes[nm] = shape
        meshes[nm] = mesh


def bbox(b):
    return box(*[float(x) for x in b])


def boundary_opening(rec: dict, facade: Polygon):
    """Rozszerz tylko na zewnątrz otwór rdzenia, aby przeciąć izolację."""
    a,b,c,d = map(float,rec['core_opening_bbox_mm'])
    center = ((a+c)/2,(b+d)/2)
    exterior_edges = list(facade.exterior.coords)
    candidates=[]
    horiz=rec['orientation_in_plan']=='horizontal'
    for p,q in zip(exterior_edges, exterior_edges[1:]):
        if horiz and abs(p[1]-q[1]) < 1:
            if min(p[0],q[0])-1 <= center[0] <= max(p[0],q[0])+1:
                candidates.append((abs(center[1]-p[1]),p[1],True))
        elif not horiz and abs(p[0]-q[0]) < 1:
            if min(p[1],q[1])-1 <= center[1] <= max(p[1],q[1])+1:
                candidates.append((abs(center[0]-p[0]),p[0],False))
    distance,coord,horiz = min(candidates)
    if distance > 800:
        raise ValueError(f'Nie rozpoznano zewnętrznej krawędzi otworu {rec["id"]}')
    if horiz:
        b,d = min(b,coord-1),max(d,coord+1)
    else:
        a,c = min(a,coord-1),max(c,coord+1)
    return box(a,b,c,d)


def make_window(rec:dict,z0:float,assumed:bool):
    a,b,c,d = map(float,rec['core_opening_bbox_mm'])
    h=rec['nominal_height_mm']
    edge=PARAM['symbolic_frame_width_mm']
    depth=PARAM['symbolic_frame_depth_mm']
    glass=PARAM['symbolic_glass_thickness_mm']
    horizontal=rec['orientation_in_plan']=='horizontal'
    if horizontal:
        b,d=(b+d-depth)/2,(b+d+depth)/2
    else:
        a,c=(a+c-depth)/2,(a+c+depth)/2
    opening=box(a,b,c,d)
    short_note='Symbol okna: przekrój ramy, szkła i ich osadzenie są umowne; bez profilu producenta. '
    short_note += ('Dolna krawędź 0 mm jest założeniem, hp nie podano wprost.' if assumed else 'Rzędna dolnej krawędzi przepisana z rzutu.')
    common=dict(source='PDF s.26; elementy ramy są symboliczne',assumed=True,note=short_note,source_id=rec['id'],
                extras={'source_tag':rec['source_tag'],'room_number':rec['room_number'],
                        'sill_source_mm':rec['sill_mm'],'sill_used_mm':z0,
                        'nominal_width_mm':rec['nominal_width_mm'],'nominal_height_mm':h})
    nm=f"{rec['id']}_{rec['source_tag']}_pokoj_{rec['room_number']:02}"
    add(nm+'_rama_dol','stolarka','stolarka',opening,z0,z0+edge,**common)
    add(nm+'_rama_gora','stolarka','stolarka',opening,z0+h-edge,z0+h,**common)
    if horizontal:
        ends=[box(a,b,a+edge,d),box(c-edge,b,c,d)]
        pane=box(a+edge,(b+d-glass)/2,c-edge,(b+d+glass)/2)
    else:
        ends=[box(a,b,c,b+edge),box(a,d-edge,c,d)]
        pane=box((a+c-glass)/2,b+edge,(a+c+glass)/2,d-edge)
    for j,g in enumerate(ends):
        add(nm+f'_rama_bok_{j+1}','stolarka','stolarka',g,z0+edge,z0+h-edge,**common)
    add(nm+'_szklo','stolarka','szklo',pane,z0+edge,z0+h-edge,**common)


facade = Polygon(DATA['facade_reference_outline']['polygon_mm'])
H = float(PARAM['wall_top_mm'])
openings=[]

for rec in DATA['wall_cut_profiles']:
    add(f"{rec['id']}_{rec['kind']}",'sciany','sciany',Polygon(rec['polygon_mm']),0,H,
        source='PDF s.26: profil XY; s.27-28: 2600 + 300 mm do spodu stropu',
        assumed=rec['kind']=='column',source_id=rec['id'],
        note=('Wysokość wolnostojącego słupa przyjęta roboczo do spodu stropu; jego zadaszenie nieodtworzone.' if rec['kind']=='column' else 'Współrzędne z wcześniejszej ekstrakcji; bez korekty rozbieżności i bez dodawania tynku.'))

for rec in DATA['windows']:
    assumption = rec['sill_mm'] is None
    z0 = float(rec['sill_mm'] if not assumption else PARAM['undimensioned_window_sill_mm'])
    z1 = z0+rec['nominal_height_mm']
    if z1>H:
        raise ValueError(f'Okno powyżej stropu: {rec["id"]}')
    p=bbox(rec['core_opening_bbox_mm'])
    meta=dict(source='PDF s.26; uzupełnienie muru na podstawie wysokości okna',
              assumed=assumption,source_id=rec['id'],
              note='Dolna krawędź przyjęta roboczo na 0 mm; źródłowe hp pozostaje null.' if assumption else 'hp jawnie podane na rzucie.',
              extras={'sill_source_mm':rec['sill_mm'],'sill_used_mm':z0,'opening_top_used_mm':z1})
    if z0>0:
        add(rec['id']+'_mur_pod_oknem','uzupelnienia','uzupelnienia',p,0,z0,**meta)
    if z1<H:
        add(rec['id']+'_mur_nad_oknem','uzupelnienia','uzupelnienia',p,z1,H,**meta)
    op={'id':rec['id'],'geometry':boundary_opening(rec,facade),'bottom':z0,'top':z1,'assumed':assumption}
    openings.append(op)
    make_window(rec,z0,assumption)

for rec in DATA['doors']:
    a,b,c,d=map(float,rec['core_opening_bbox_mm'])
    height=float(PARAM['door_opening_height_overrides_mm'].get(rec['id'],PARAM['door_opening_height_mm']))
    add(rec['id']+'_mur_nad_drzwiami','uzupelnienia','uzupelnienia',box(a,b,c,d),height,H,
        source='PDF s.26: XY; wysokość otworu przyjęta do modelu',assumed=True,source_id=rec['id'],
        note='2050 mm przeniesione roboczo z wybranego otworu na przekroju, nie potwierdzone dla każdych drzwi. Dla bramy użyto nominalnej wysokości 2250 mm.',
        extras={'nominal_height_mm':rec['nominal_height_mm'],'structural_height_source_mm':rec['structural_opening_height_mm'],'opening_height_used_mm':height})
    width=rec['nominal_width_mm']
    thick=PARAM['symbolic_door_leaf_thickness_mm']
    if rec['orientation_in_plan']=='horizontal':
        g=box((a+c-width)/2,(b+d-thick)/2,(a+c+width)/2,(b+d+thick)/2)
    else:
        g=box((a+c-thick)/2,(b+d-width)/2,(a+c+thick)/2,(b+d+width)/2)
    add(rec['id']+'_'+rec['source_tag']+'_symbol','stolarka','drzwi',g,0,rec['nominal_height_mm'],
        source='PDF s.26: nominalne wymiary; umowna grubość i pozycja',assumed=True,source_id=rec['id'],
        note='Uproszczony, zamknięty panel bez podziałów, okuć i ościeżnicy producenta.',
        extras={'nominal_width_mm':width,'nominal_height_mm':rec['nominal_height_mm'],'adjacent_room_numbers':rec['adjacent_room_numbers']})
    add(rec['id']+'_powierzchnia_w_przejsciu','podlogi','progi',box(a,b,c,d),0,None,
        source='PDF s.26: pole otworu; kontynuacja poziomu posadzki 0',source_id=rec['id'])
    if rec['id'] in ['DR01','DR02']:
        openings.append({'id':rec['id'],'geometry':boundary_opening(rec,facade),'bottom':0,'top':height,'assumed':True})

for rec in DATA['unlabelled_passages']:
    add(rec['id']+'_mur_nad_przejsciem','uzupelnienia','uzupelnienia',bbox(rec['core_opening_bbox_mm']),PARAM['unlabelled_passage_height_mm'],H,
        source='PDF s.26: przejście bez wysokości',assumed=True,source_id=rec['id'],
        note='Wysokość przyjęta roboczo 2600 mm. Nie dodano drzwi.')
    add(rec['id']+'_powierzchnia_w_przejsciu','podlogi','progi',bbox(rec['core_opening_bbox_mm']),0,None,
        source='PDF s.26: poziom posadzki 0',source_id=rec['id'])

# Izolacja zewnętrzna w osobnych pasach Z. Otwory przechodzą również przez izolację.
core_envelope=facade.buffer(-PARAM['external_insulation_mm'],join_style='mitre')
insulation=facade.difference(core_envelope)
heights=sorted(set([0,H]+[o[k] for o in openings for k in ['bottom','top']]))
for i,(lo,hi) in enumerate(zip(heights,heights[1:]),1):
    mid=(lo+hi)/2
    cut=unary_union([o['geometry'] for o in openings if o['bottom']<=mid<o['top']])
    layer=insulation.difference(cut)
    add(f'IZ_{i:02}_z_{int(lo)}_{int(hi)}','izolacja','izolacja',layer,lo,hi,
        source='PDF s.26: obrys; s.27-28: 260 mm izolacji',assumed=True,
        note='Pierścień odtworzony przez odsunięcie obrysu o 260 mm. Wycięcia uwzględniają robocze wysokości otworów; bez osobnej geometrii cienkiego tynku.')

for room in DATA['rooms']:
    p=Polygon(room['floor_reference_polygon_mm'])
    nm=f"{room['id']}_{ascii_name(room['name'])}"
    meta=dict(source='PDF s.26: obrys kontrolny pomieszczenia',source_id=room['id'],
              note='Powierzchnia, nie warstwa materiałowa o założonej grubości; kolor roboczy.',
              extras={'room_number':room['number'],'room_name':room['name'],'reported_area_m2':room['reported_area_m2']})
    add(nm+'_posadzka','podlogi','podlogi',p,0,None,**meta)
    add(nm+'_sufit_z_2600','sufity','sufity',p,PARAM['ceiling_level_mm'],None,**meta)

roof_outer=Polygon(ROOF['outer_polygon_mm'])
roof_inner=Polygon(ROOF['inner_polygon_mm'])
if not roof_outer.covers(roof_inner):
    raise ValueError('Wewnętrzny obrys dachu poza zewnętrznym.')
add('STROP_plyta_180mm','strop','strop',core_envelope,H,H+PARAM['slab_thickness_mm'],
    source='PDF s.27-28: 180 mm; poziom 2900 mm wyliczony; XY obrys ścian',assumed=True,
    note='Zasięg płyty przyjęty po obrysie rdzenia; bez detali podciągów, zbrojenia i zadaszenia przy słupie.')
add('STROP_izolacja_obwodowa','strop','izolacja',insulation,H,H+PARAM['slab_thickness_mm'],
    source='Kontynuacja robocza izolacji obwodowej',assumed=True)
add('DACH_wypelnienie_BEZ_SPADKOW','dach','dach',roof_inner,H+PARAM['slab_thickness_mm'],PARAM['simplified_roof_surface_mm'],
    source='PDF s.31: wektorowy obrys wewnętrzny; poziom powierzchni jest uproszczeniem',assumed=True,
    note='Stały poziom 3710 mm przyjęty WYŁĄCZNIE do bryły. +3.71 to lokalna rzędna na rysunku. Nie odtworzono spadków 5° i 0.5% ani układu warstw.')
add('DACH_attyka_UPROSZCZONA','dach','attyka',roof_outer.difference(roof_inner),H+PARAM['slab_thickness_mm'],PARAM['parapet_top_mm'],
    source='PDF s.31: zewnętrzny i wewnętrzny wektorowy obrys; +3.95',assumed=True,
    note='Nierozdzielony pas obwodowy; bez detali warstw attyki i obróbek. Nie rozstrzygnięto różnicy 3940/3950 mm w źródle.')

# STEP: rzeczywiste bryły BREP i powierzchnie, nie sama siatka trójkątów.
assy=cq.Assembly(name='DOM_MODEL_ROBOCZY')
for cat,label in GROUP_NAMES.items():
    group=cq.Assembly(name=label)
    for rec in parts:
        if rec['category']!=cat:
            continue
        c=rec['color']
        group.add(shapes[rec['name']],name=rec['name'],color=cq.Color(*c))
    assy.add(group)
assy.export(str(ROOT/'dom_model_CAD.step'),exportType='STEP',unit='MM',outputUnit='MM')

# glTF standard: metry, oś Y do góry. (X,Y,Z) w CAD -> (X,Z,-Y) w GLB.
Y_UP=np.array([[1,0,0,0],[0,0,1,0],[0,-1,0,0],[0,0,0,1]],dtype=float)


def export_glb(filename:str, include_roof:bool):
    scene=trimesh.Scene(base_frame='DOM')
    scene.metadata={'units':'m','source':'Projekt budowlany PZT_PAB_2024.02.01.pdf',
        'coordinate_transform':'glTF (x,y,z) = CAD (x,z,-y) / 1000',
        'model_status':'working reconstruction, see parametry_modelu.json and CZYTAJ_MNIE.md',
        'not_as_built':True}
    for rec in parts:
        if rec['category']=='sufity':
            continue
        if not include_roof and rec['category'] in ['dach','strop']:
            continue
        mesh=meshes[rec['name']].copy()
        mesh.unmerge_vertices() # płaskie normalne, bez wygładzania narożników murów
        color=np.array(rec['color'])*255
        material=trimesh.visual.material.PBRMaterial(name=rec['material'],baseColorFactor=color.astype(np.uint8),
            metallicFactor=0.0,roughnessFactor=0.82,
            alphaMode='BLEND' if rec['material']=='szklo' else 'OPAQUE',doubleSided=True)
        mesh.visual=trimesh.visual.TextureVisuals(material=material)
        mesh.apply_transform(Y_UP)
        metadata={k:v for k,v in rec.items() if k not in ['bbox_mm','color'] and v is not None}
        scene.add_geometry(mesh,node_name=rec['name'],geom_name=rec['name'],metadata=metadata)
    (ROOT/filename).write_bytes(trimesh.exchange.gltf.export_glb(scene,include_normals=True))
    loaded=trimesh.load(ROOT/filename,force='scene')
    return {'nodes':len(loaded.geometry),'bounds_m':loaded.bounds.tolist(),'size_bytes':(ROOT/filename).stat().st_size}

exports={}
exports['dom_wnetrze.glb']=export_glb('dom_wnetrze.glb',False)
exports['dom_bryla.glb']=export_glb('dom_bryla.glb',True)

# OBJ + MTL: osobne obiekty; współrzędne w metrach, oś Z w górę.
obj=['# Model roboczy domu. Units: meters. Z-up.','# Braki i uproszczenia: CZYTAJ_MNIE.md','mtllib dom_materialy.mtl']
offset=0
for rec in parts:
    if rec['category']=='sufity':
        continue
    m=meshes[rec['name']]
    obj += [f"o {rec['name']}",f"g {GROUP_NAMES[rec['category']]}",f"usemtl {rec['material']}"]
    obj += [f'v {a:.7f} {b:.7f} {c:.7f}' for a,b,c in m.vertices]
    obj += ['f '+' '.join(str(int(x)+offset+1) for x in f) for f in m.faces]
    offset+=len(m.vertices)
(ROOT/'dom_model.obj').write_text('\n'.join(obj)+'\n',encoding='utf-8')
mtl=['# Neutralne, robocze materialy; nie oznaczaja finalnego wykonczenia.']
for name,c in COLORS.items():
    mtl.extend([f'newmtl {name}',f'Kd {c[0]} {c[1]} {c[2]}',f'd {c[3]}','Ka 0.1 0.1 0.1','Ks 0.1 0.1 0.1','Ns 20',''])
(ROOT/'dom_materialy.mtl').write_text('\n'.join(mtl),encoding='utf-8')

# Neutralny format sceny dla lokalnego podglądu oraz skryptu Blendera.
scene_records=[]
for rec in parts:
    m=meshes[rec['name']]
    scene_records.append({**rec,'positions_m':np.round(m.vertices,7).tolist(),'faces':m.faces.tolist()})
(ROOT/'scena_modelu.json').write_text(json.dumps({'units':'m','up_axis':'Z','parts':scene_records},ensure_ascii=False,separators=(',',':')),encoding='utf-8')

# Sprawdzenie zapisanego STEP w niezależnym ponownym odczycie.
step_shape=cq.importers.importStep(str(ROOT/'dom_model_CAD.step')).val()
validation={
    'source_sha256':DATA['source_document']['sha256'],
    'model_objects':len(parts),'solid_objects':sum(r['geometry']=='solid' for r in parts),
    'surface_objects':sum(r['geometry']=='face' for r in parts),
    'all_brep_valid':all(r['valid_brep'] for r in parts),
    'all_solid_meshes_watertight':all(r['watertight_mesh'] for r in parts if r['geometry']=='solid'),
    'step_reimport_valid':step_shape.isValid(),
    'step_reimport_solids':len(step_shape.Solids()),
    'facade_outline_span_mm':[round(facade.bounds[2]-facade.bounds[0],3),round(facade.bounds[3]-facade.bounds[1],3)],
    'declared_source_span_mm':[DATA['building']['length_mm']['value'],DATA['building']['width_mm']['value']],
    'not_rescaled_to_declared_length':True,
    'roof_outer_span_mm':[round(roof_outer.bounds[2]-roof_outer.bounds[0],3),round(roof_outer.bounds[3]-roof_outer.bounds[1],3)],
    'room_count':len(DATA['rooms']),
    'assumptions_file':'parametry_modelu.json','source_issues':DATA['issues_and_missing_data'],
    'exports':exports,
    'status':'Model roboczy; test geometrii plików nie jest kontrolą budowlaną.',
}
(ROOT/'kontrola_modelu.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2),encoding='utf-8')
(ROOT/'lista_elementow.json').write_text(json.dumps(parts,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in validation.items() if k!='source_issues'},ensure_ascii=False,indent=2))
