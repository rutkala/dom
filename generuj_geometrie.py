#!/usr/bin/env python3
"""Generator geometrii 3D z uwzglednieniem rzeczywistych wysokosci i aktualnego zestawienia okien.

Generuje:
- scena_modelu.json
- dom_wnetrze.glb
- dom_bryla.glb
- dom_model.obj + dom_materialy.mtl
- podglad_3d.html (przez aktualizuj_podglad.py)
"""
from __future__ import annotations
import io
import json
import re
import sys
import math
import unicodedata
from pathlib import Path
from typing import Any

import numpy as np
import trimesh
from shapely.geometry import Polygon, MultiPolygon, GeometryCollection, LineString, box
from shapely.ops import unary_union

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parent
DATA = json.loads((ROOT / 'dane_zrodlowe.json').read_text(encoding='utf-8'))
PARAM = json.loads((ROOT / 'parametry_modelu.json').read_text(encoding='utf-8'))
ROOF = json.loads((ROOT / 'obrys_dachu_z_pdf.json').read_text(encoding='utf-8'))
WINDOWS = json.loads((ROOT / 'okna_projektowe.json').read_text(encoding='utf-8'))
EXTERIOR_JOINERY = json.loads((ROOT / 'stolarka_zewnetrzna.json').read_text(encoding='utf-8'))
SITE = json.loads((ROOT / 'pzt_zagospodarowanie.json').read_text(encoding='utf-8'))
ELEVATIONS = json.loads((ROOT / 'elewacje_materialy.json').read_text(encoding='utf-8'))
INTERIOR = json.loads((ROOT / 'wnetrze_projekt.json').read_text(encoding='utf-8'))
GEO_REAL_PATH = ROOT / 'geoportal_teren.json'
GEO_REAL = json.loads(GEO_REAL_PATH.read_text(encoding='utf-8')) if GEO_REAL_PATH.exists() else None

COLORS = {
    'sciany': [0.84, 0.83, 0.80, 1.0],
    'izolacja': [0.93, 0.92, 0.88, 1.0],
    'uzupelnienia': [0.84, 0.83, 0.80, 1.0],
    'podlogi': [0.66, 0.66, 0.64, 1.0],
    'progi': [0.66, 0.66, 0.64, 1.0],
    'stolarka': [0.22, 0.23, 0.25, 1.0], # czarny / antracyt stolarki jak na budowie
    'szklo': [0.58, 0.74, 0.79, 0.35],
    'drzwi': [0.59, 0.57, 0.53, 1.0],
    'drzwi_antracyt': [0.17, 0.19, 0.20, 1.0],
    'brama': [0.16, 0.18, 0.20, 1.0],
    'brama_linia': [0.07, 0.08, 0.09, 1.0],
    'szklo_matowe': [0.78, 0.82, 0.80, 0.72],
    'metal_czarny': [0.03, 0.03, 0.03, 1.0],
    'elewacja_biala': [0.99, 0.975, 0.93, 1.0],
    'elewacja_szara': [0.38, 0.39, 0.40, 1.0],
    'elewacja_drewno': [0.63, 0.43, 0.29, 1.0],
    'elewacja_drewno_fuga': [0.25, 0.17, 0.11, 1.0],
    'teren_trawa': [0.43, 0.55, 0.34, 1.0],
    'kostka': [0.58, 0.59, 0.59, 1.0],
    'ziemia': [0.34, 0.25, 0.18, 1.0],
    'taras': [0.62, 0.49, 0.39, 1.0],
    'schody': [0.67, 0.67, 0.65, 1.0],
    'daszek_beton': [0.70, 0.71, 0.70, 1.0],
    'strop': [0.72, 0.73, 0.74, 1.0],
    'dach': [0.38, 0.41, 0.43, 1.0],
    'attyka': [0.99, 0.975, 0.93, 1.0],
    'sufity': [0.94, 0.94, 0.92, 1.0],
    'interior_block': [0.28, 0.57, 0.72, 0.38],
    'interior_black': [0.055, 0.058, 0.06, 1.0],
    'interior_oak': [0.58, 0.39, 0.21, 1.0],
    'interior_concrete': [0.66, 0.64, 0.60, 1.0],
    'interior_cream': [0.84, 0.80, 0.74, 1.0],
    'interior_mustard': [0.86, 0.64, 0.08, 1.0],
    'interior_metal': [0.025, 0.025, 0.025, 1.0],
    'interior_glass': [0.62, 0.72, 0.75, 0.35],
    'interior_flame': [0.95, 0.42, 0.08, 0.9],
    'teren_rzeczywisty': [0.40, 0.47, 0.34, 1.0],
    'ortofoto': [0.62, 0.62, 0.62, 1.0],
    'granica_dzialki': [0.97, 0.48, 0.05, 1.0],
    'budynki_otoczenia': [0.73, 0.71, 0.67, 1.0],
    'budynki_dachy': [0.48, 0.38, 0.30, 1.0],
    'drzewa_korony': [0.22, 0.43, 0.16, 1.0],
    'drzewa_pnie': [0.28, 0.18, 0.10, 1.0],
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
    'elewacja': '09_ELEWACJA_WYKONCZENIE',
    'daszek': '10_DASZEK_WEJSCIOWY',
    'teren': '11_TEREN',
    'nawierzchnie': '12_NAWIERZCHNIE_I_TARAS',
    'schody': '13_SCHODY_ZEWNETRZNE',
    'wnetrze_bloki': '14_WNETRZE_BLOKI',
    'wnetrze_elementy': '15_WNETRZE_ELEMENTY',
    'teren_rzeczywisty': '16_GEO_NMT_RZECZYWISTY',
    'ortofoto': '17_GEO_ORTOFOTOMAPA',
    'granica_dzialki': '18_GEO_GRANICA_DZIALKI',
    'budynki_otoczenia': '19_GEO_BUDYNKI_OTOCZENIA',
    'drzewa': '20_GEO_DRZEWA',
    'dom_geo': '21_DOM_GEOREFERENCJONOWANY',
}

parts: list[dict[str, Any]] = []
meshes: dict[str, trimesh.Trimesh] = {}
used_names: set[str] = set()

def ascii_name(value: str) -> str:
    value = value.translate(str.maketrans({'ł':'l','Ł':'L'}))
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-zA-Z0-9_]+', '_', value).strip('_')

def polygons(geometry):
    if geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry] if geometry.area > 0.1 else []
    if isinstance(geometry, (MultiPolygon, GeometryCollection)):
        return [p for child in geometry.geoms for p in polygons(child)]
    return []

def mesh_from_polygon(p: Polygon, z0: float, z1: float | None) -> trimesh.Trimesh:
    """Tworzy siatke trimesh z wielokata Shapely."""
    from trimesh.creation import triangulate_polygon, extrude_polygon
    if z1 is None or abs(z1 - z0) < 1e-4:
        v2d, f = triangulate_polygon(p, engine='earcut')
        v3d = np.column_stack([v2d, np.full(len(v2d), z0)]) / 1000.0
        return trimesh.Trimesh(vertices=v3d, faces=f, process=True)
    else:
        height = float(z1 - z0)
        m = extrude_polygon(p, height=height, engine='earcut')
        m.vertices /= 1000.0
        m.apply_translation([0, 0, z0 / 1000.0])
        return m

def add(name: str, category: str, material: str, geometry, z0: float, z1: float | None,
        source: str, assumed: bool = False, note: str = '', source_id: str = '', extras: dict | None = None):
    polys = polygons(geometry)
    for number, p in enumerate(polys, 1):
        nm = ascii_name(name + (f'_{number:02}' if len(polys) > 1 else ''))
        if nm in used_names:
            raise ValueError(f'Powtorzona nazwa {nm}')
        used_names.add(nm)
        m = mesh_from_polygon(p, z0, z1)
        if z1 is not None and m.volume < 0:
            m.invert()
        record = {
            'name': nm,
            'category': category,
            'material': material,
            'color': COLORS[material],
            'source': source,
            'source_id': source_id,
            'assumed': assumed,
            'note': note,
            'z_bottom_mm': z0,
            'z_top_mm': z1,
            'plan_area_m2': round(p.area / 1e6, 6),
            'geometry': 'face' if z1 is None else 'solid',
            'valid_brep': True,
            'watertight_mesh': bool(m.is_watertight) if z1 is not None else False,
            'bbox_mm': [[round(float(v) * 1000, 3) for v in row] for row in m.bounds],
            'volume_m3': round(float(m.volume), 9) if z1 is not None else None,
            'vertices': len(m.vertices),
            'triangles': len(m.faces),
            'default_visible': category not in ['strop', 'dach', 'sufity']
        }
        if extras:
            record.update(extras)
        parts.append(record)
        meshes[nm] = m

def add_mesh_record(name: str, category: str, material: str, mesh: trimesh.Trimesh,
                    source: str, assumed: bool=False, note: str='', source_id: str='', extras: dict | None=None,
                    reference_area_m2: float | None=None):
    nm=ascii_name(name)
    if nm in used_names: raise ValueError(f'Powtorzona nazwa {nm}')
    used_names.add(nm); m=mesh.copy()
    record={'name':nm,'category':category,'material':material,'color':COLORS[material],
            'source':source,'source_id':source_id,'assumed':assumed,'note':note,
            'z_bottom_mm':round(float(m.bounds[0][2])*1000,3),'z_top_mm':round(float(m.bounds[1][2])*1000,3),
            'plan_area_m2':reference_area_m2,'geometry':'solid' if m.is_watertight else 'face',
            'valid_brep':True,'watertight_mesh':bool(m.is_watertight),
            'bbox_mm':[[round(float(v)*1000,3) for v in row] for row in m.bounds],
            'volume_m3':round(float(m.volume),9) if m.is_watertight else None,
            'vertices':len(m.vertices),'triangles':len(m.faces),'default_visible':category not in ['strop','dach','sufity']}
    if extras: record.update(extras)
    parts.append(record); meshes[nm]=m

def geometry_from_serial(items):
    geoms=[Polygon(item['exterior_mm'],item.get('holes_mm',[])) for item in items]
    return unary_union(geoms) if geoms else Polygon()

def add_surface(name, category, material, geometry, z_func, source, assumed=False, note='', source_id='', extras=None):
    from trimesh.creation import triangulate_polygon
    for number,poly in enumerate(polygons(geometry),1):
        v2d,faces=triangulate_polygon(poly,engine='earcut')
        z=np.array([float(z_func(float(x),float(y))) for x,y in v2d])
        mesh=trimesh.Trimesh(vertices=np.column_stack([v2d,z])/1000.0,faces=faces,process=True)
        nm=name+(f'_{number:02}' if len(polygons(geometry))>1 else '')
        add_mesh_record(nm,category,material,mesh,source,assumed,note,source_id,extras,round(poly.area/1e6,6))

def _facade_coord(facade, side, axis_value):
    big=1e6
    if side in ('east','west'):
        cross=facade.intersection(LineString([(axis_value,-big),(axis_value,big)]))
        if cross.is_empty: return None
        return cross.bounds[1] if side=='east' else cross.bounds[3]
    cross=facade.intersection(LineString([(-big,axis_value),(big,axis_value)]))
    if cross.is_empty: return None
    return cross.bounds[0] if side=='south' else cross.bounds[2]

def opening_elevation_masks(openings, facade):
    """Project current exterior openings to elevation side coordinates (s,z).

    The elevation drawings are used only for material zoning. Openings are always
    taken from the current measured/model geometry, so removed or relocated
    project windows cannot reappear in the finish layer.
    """
    masks={'east':[], 'west':[], 'south':[], 'north':[]}
    for op in openings:
        g=op['geometry']; minx,miny,maxx,maxy=g.bounds
        cx,cy=g.centroid.x,g.centroid.y
        if (maxx-minx) >= (maxy-miny):
            east=_facade_coord(facade,'east',cx); west=_facade_coord(facade,'west',cx)
            if east is None or west is None: continue
            side='east' if abs(cy-east) <= abs(cy-west) else 'west'
            s0,s1=minx,maxx
        else:
            south=_facade_coord(facade,'south',cy); north=_facade_coord(facade,'north',cy)
            if south is None or north is None: continue
            side='south' if abs(cx-south) <= abs(cx-north) else 'north'
            s0,s1=miny,maxy
        masks[side].append(box(float(s0),float(op['bottom']),float(s1),float(op['top'])))
    return {k:(unary_union(v) if v else Polygon()) for k,v in masks.items()}

def add_vertical_patch(name, material, side, patch_sz, facade, outward_mm, source, source_id='', extras=None):
    from trimesh.creation import triangulate_polygon
    vals=sorted(set((x if side in ('east','west') else y) for x,y in facade.exterior.coords))
    lo,_,hi,_=patch_sz.bounds; breaks=[lo]+[v for v in vals if lo+1e-6<v<hi-1e-6]+[hi]; piece=0
    for a,b in zip(breaks,breaks[1:]):
        for q in polygons(patch_sz.intersection(box(a,-1e6,b,1e6))):
            if q.area<1: continue
            wall=_facade_coord(facade,side,(a+b)/2)
            if wall is None: continue
            v2d,faces=triangulate_polygon(q,engine='earcut'); verts=[]
            for sval,zval in v2d:
                if side=='east': verts.append([sval,wall-outward_mm,zval])
                elif side=='west': verts.append([sval,wall+outward_mm,zval])
                elif side=='south': verts.append([wall-outward_mm,sval,zval])
                else: verts.append([wall+outward_mm,sval,zval])
            piece+=1
            mesh=trimesh.Trimesh(vertices=np.asarray(verts)/1000.0,faces=faces,process=True)
            add_mesh_record(f'{name}_{piece:02}','elewacja',material,mesh,source,False,'',source_id,extras,round(q.area/1e6,6))

def bbox(b):
    return box(*[float(x) for x in b])

def boundary_opening(rec: dict, facade: Polygon):
    a, b, c, d = map(float, rec['core_opening_bbox_mm'])
    center = ((a + c) / 2, (b + d) / 2)
    exterior_edges = list(facade.exterior.coords)
    candidates = []
    horiz = rec['orientation_in_plan'] == 'horizontal'
    for p, q in zip(exterior_edges, exterior_edges[1:]):
        if horiz and abs(p[1] - q[1]) < 1:
            if min(p[0], q[0]) - 1 <= center[0] <= max(p[0], q[0]) + 1:
                candidates.append((abs(center[1] - p[1]), p[1], True))
        elif not horiz and abs(p[0] - q[0]) < 1:
            if min(p[1], q[1]) - 1 <= center[1] <= max(p[1], q[1]) + 1:
                candidates.append((abs(center[0] - p[0]), p[0], False))
    distance, coord, horiz = min(candidates)
    if horiz:
        b, d = min(b, coord - 1), max(d, coord + 1)
    else:
        a, c = min(a, coord - 1), max(c, coord + 1)
    return box(a, b, c, d)

def make_window(rec: dict, z0: float, z1: float):
    a, b, c, d = map(float, rec['core_opening_bbox_mm'])
    h = z1 - z0
    edge = PARAM['symbolic_frame_width_mm']
    depth = PARAM['symbolic_frame_depth_mm']
    glass = PARAM['symbolic_glass_thickness_mm']
    horizontal = rec['orientation_in_plan'] == 'horizontal'
    if horizontal:
        b, d = (b + d - depth) / 2, (b + d + depth) / 2
    else:
        a, c = (a + c - depth) / 2, (a + c + depth) / 2
    opening = box(a, b, c, d)
    short_note = f"{rec.get('note', '')} (wymiary {rec['nominal_width_mm']/10:.0f}×{h/10:.0f} cm, dół +{z0/1000:.2f} m, góra +{z1/1000:.2f} m)."
    common = dict(
        source='okna.pdf - oferta 2024/510 v. 8 po pomiarze',
        assumed=False,
        note=short_note,
        source_id=rec['id'],
        extras={
            'source_tag': rec['source_tag'],
            'room_number': rec['room_number'],
            'sill_source_mm': rec['sill_mm'],
            'sill_used_mm': z0,
            'nominal_width_mm': rec['nominal_width_mm'],
            'nominal_height_mm': h,
            'offer_position': rec.get('offer_position'),
            'offer_position_candidates': rec.get('offer_position_candidates'),
            'product': rec.get('product'),
            'configuration': rec.get('configuration'),
            'joinery_color': rec.get('color'),
            'assembly_id': rec.get('assembly_id'),
            'assembly_width_mm': rec.get('assembly_width_mm'),
            'assembly_height_mm': rec.get('assembly_height_mm')
        }
    )
    nm = f"{rec['id']}_{rec['source_tag']}_pokoj_{rec['room_number']:02}"
    add(nm + '_rama_dol', 'stolarka', 'stolarka', opening, z0, z0 + edge, **common)
    add(nm + '_rama_gora', 'stolarka', 'stolarka', opening, z1 - edge, z1, **common)
    if horizontal:
        ends = [box(a, b, a + edge, d), box(c - edge, b, c, d)]
        pane = box(a + edge, (b + d - glass) / 2, c - edge, (b + d + glass) / 2)
    else:
        ends = [box(a, b, c, b + edge), box(a, d - edge, c, d)]
        pane = box((a + c - glass) / 2, b + edge, (a + c + glass) / 2, d - edge)
    for j, g in enumerate(ends):
        add(nm + f'_rama_bok_{j+1}', 'stolarka', 'stolarka', g, z0 + edge, z1 - edge, **common)
    # Schematic mullions from the measured order; not manufacturer profile sections.
    for j in range(int(rec.get('model_mullion_count', 0) or 0)):
        t=(j+1)/(int(rec.get('model_mullion_count',0))+1)
        if horizontal:
            x=(a+edge)+t*((c-edge)-(a+edge)); g=box(x-edge/2,b,x+edge/2,d)
        else:
            y=(b+edge)+t*((d-edge)-(b+edge)); g=box(a,y-edge/2,c,y+edge/2)
        add(nm + f'_slupek_{j+1}', 'stolarka', 'stolarka', g, z0 + edge, z1 - edge, **common)
    add(nm + '_szklo', 'stolarka', 'szklo', pane, z0 + edge, z1 - edge, **common)


def _interior_box(name, category, material, bbox_mm, source, room_number, layer, role='', source_pages=None, product=''):
    a,b=bbox_mm
    x0,y0,z0=map(float,a); x1,y1,z1=map(float,b)
    extras={'room_number':int(room_number),'interior_layer':layer,'role':role,'source_pages':source_pages or []}
    if product: extras['product']=product
    add(name,category,material,box(x0,y0,x1,y1),z0,z1,source,True,role,name,extras)

def _interior_cylinder(name, category, material, center_mm, radius_mm, height_mm, source, room_number, layer, role='', source_pages=None, product=''):
    cx,cy,cz=map(float,center_mm)
    h=float(height_mm); r=float(radius_mm)
    mesh=trimesh.creation.cylinder(radius=r/1000.0,height=h/1000.0,sections=32)
    mesh.apply_translation([cx/1000.0,cy/1000.0,cz/1000.0])
    extras={'room_number':int(room_number),'interior_layer':layer,'role':role,'source_pages':source_pages or []}
    if product: extras['product']=product
    add_mesh_record(name,category,material,mesh,source,True,role,name,extras)

def _block_material(block_id):
    oak={'KUCH_TALL_ZONE','SPI_TALL','SPI_SHELVES','HOL_CONSOLE','HOL_SLAT_WALL'}
    concrete={'SAL_TV_WALL','SAL_ART_WALL'}
    cream={'SAL_SOFA_LONG','SAL_SOFA_CHAISE','HOL_POUF'}
    mustard={'SAL_ARMCHAIR'}
    black={'KUCH_RUN_WINDOW','KUCH_LEFT_RUN','KUCH_OVEN_TOWER','KUCH_ISLAND','SPI_BASE','HOL_WARDROBE'}
    if block_id in oak: return 'interior_oak'
    if block_id in concrete: return 'interior_concrete'
    if block_id in cream: return 'interior_cream'
    if block_id in mustard: return 'interior_mustard'
    if block_id in black: return 'interior_black'
    return 'interior_black'

def add_interior_layers():
    source='Projekt wnętrza 20,10,2023.pdf'
    blocks=INTERIOR['layers']['blocks']
    block_map={b['id']:b for b in blocks}

    # Layer 1: dimension / collision blocks.
    for rec in blocks:
        pages=rec.get('source_pages',[])
        role=rec.get('role','')
        if rec['primitive']=='box':
            _interior_box('BLK_'+rec['id'],'wnetrze_bloki','interior_block',rec['bbox_mm'],source,rec['room'],'blocks',role,pages)
        elif rec['primitive']=='cylinder':
            _interior_cylinder('BLK_'+rec['id'],'wnetrze_bloki','interior_block',rec['center_mm'],rec['radius_mm'],rec['height_mm'],source,rec['room'],'blocks',role,pages)

    # Utility for selected-layer proxies based on a block.
    def clone_block(selected_id, block_id, material, product='', suffix=''):
        rec=block_map[block_id]
        name='SEL_'+selected_id+'_'+block_id+(('_'+suffix) if suffix else '')
        role=rec.get('role','')
        pages=rec.get('source_pages',[])
        if rec['primitive']=='box':
            _interior_box(name,'wnetrze_elementy',material,rec['bbox_mm'],source,rec['room'],'selected',role,pages,product)
        else:
            _interior_cylinder(name,'wnetrze_elementy',material,rec['center_mm'],rec['radius_mm'],rec['height_mm'],source,rec['room'],'selected',role,pages,product)

    # Custom cabinetry: same verified envelope, materialized instead of blue blocks.
    cabinet_materials={
        'KUCH_RUN_WINDOW':'interior_black','KUCH_TALL_ZONE':'interior_oak','KUCH_LEFT_RUN':'interior_black',
        'KUCH_OVEN_TOWER':'interior_black','KUCH_ISLAND':'interior_black',
        'SPI_BASE':'interior_black','SPI_TALL':'interior_oak',
        'HOL_WARDROBE':'interior_black','HOL_CONSOLE':'interior_oak'
    }
    for rec in INTERIOR['layers']['selected']:
        sid=rec['id']; product=rec.get('product',rec.get('product_type',''))
        proxy=rec.get('proxy',{})
        if sid in ('SEL_KITCHEN_CABINETRY','SEL_PANTRY_CABINETRY','SEL_ENTRY_WARDROBE','SEL_ENTRY_CONSOLE'):
            refs=rec.get('based_on',proxy.get('based_on',[]))
            for block_id in refs:
                if block_id in ('SPI_SHELVES','SPI_TALL'):
                    continue
                clone_block(sid,block_id,cabinet_materials.get(block_id,'interior_black'),product)

    # Kitchen wall elements grounded in the top plan / elevation drawings.
    clone_block('KITCHEN_CHALKBOARD','KUCH_CHALKBOARD','interior_black','farba tablicowa Jeger')
    clone_block('KITCHEN_SLIDING_DOOR','KUCH_SLIDING_DOOR','interior_oak','drzwi przesuwne drewniane')
    # The wine display from p.24 is the glazed SIDE of the 0.60 m-deep tall cabinet,
    # not a separate floor-standing cabinet. It is drawn on the east face of KUCH_TALL_ZONE.
    _interior_box('SEL_WINE_side_glass','wnetrze_elementy','interior_glass',
        [[12532,8760,100],[12560,9360,2500]],source,11,'selected',
        'przeszklony bok/winiarka 0,60 m',[24],'witryna / winiarka')
    for idx,z in enumerate((300,700,1100,1500,1900,2300),1):
        _interior_box(f'SEL_WINE_side_shelf_{idx}','wnetrze_elementy','interior_oak',
            [[12505,8785,z],[12560,9335,z+20]],source,11,'selected',
            'półka bocznej witryny',[24],'witryna / winiarka')

    # Kitchen worktops / sink make the selected layer visually different from plain blocks.
    _interior_box('SEL_KITCHEN_top_window','wnetrze_elementy','interior_oak',
        [[7610,8760,900],[11010,9360,960]],source,11,'selected','blat ciągu północnego 3,40 m',[21,22],'dąb craft złoty')
    _interior_box('SEL_KITCHEN_top_left','wnetrze_elementy','interior_oak',
        [[7010,7120,900],[7610,9360,960]],source,11,'selected','blat ciągu zachodniego 2,24 m',[21,23],'dąb craft złoty')
    _interior_box('SEL_KITCHEN_top_island','wnetrze_elementy','interior_oak',
        [[8880,6830,900],[11840,7790,960]],source,11,'selected','blat wyspy 2900×900',[21,25,26],'dąb craft złoty')
    sink_rec=next((x for x in INTERIOR['layers']['selected'] if x['id']=='SEL_KITCHEN_SINK'),None)
    if sink_rec:
        bb=sink_rec['proxy']['bbox_mm']
        _interior_box('SEL_KITCHEN_sink','wnetrze_elementy','interior_black',
            [[bb[0][0],bb[0][1],955],[bb[1][0],bb[1][1],985]],source,11,'selected','zlewozmywak',[21,25,26,50],sink_rec['product'])
        _interior_cylinder('SEL_KITCHEN_faucet','wnetrze_elementy','interior_metal',
            [9630,7040,1045],25,180,source,11,'selected','bateria kuchenna - proxy',[25,26,50],'bateria kuchenna')

    # Kitchen stools: recognizable seats + four slim legs.
    stool_rec=next((x for x in INTERIOR['layers']['selected'] if x['id']=='SEL_KITCHEN_STOOLS'),None)
    if stool_rec:
        for idx,(cx,cy) in enumerate(stool_rec['proxy']['centers_mm'],1):
            _interior_cylinder(f"SEL_HOKER_{idx}_seat",'wnetrze_elementy','interior_black',[cx,cy,695],190,70,source,11,'selected','siedzisko hokera',[50],stool_rec['product'])
            for dx,dy in ((-120,-100),(120,-100),(-120,100),(120,100)):
                _interior_box(f"SEL_HOKER_{idx}_leg_{dx}_{dy}",'wnetrze_elementy','interior_metal',
                    [[cx+dx-12,cy+dy-12,40],[cx+dx+12,cy+dy+12,660]],source,11,'selected','noga hokera',[50],stool_rec['product'])

    # Dining table: exact 0.90 × 2.76 m from p.49; XY registered to the building plan.
    clone_block('DINING','SAL_DINING_TABLE','interior_oak','stół - zamówienie indywidualne')
    tb=block_map['SAL_DINING_TABLE']['bbox_mm']
    tx0,ty0=map(float,tb[0][:2]); tx1,ty1=map(float,tb[1][:2])
    for idx,(lx,ly) in enumerate(((tx0+80,ty0+160),(tx1-80,ty0+160),(tx0+80,ty1-160),(tx1-80,ty1-160)),1):
        _interior_box(f'SEL_DINING_leg_{idx}','wnetrze_elementy','interior_metal',
            [[lx-25,ly-25,30],[lx+25,ly+25,720]],source,10,'selected','noga stołu',[49],'stół - zamówienie indywidualne')
    chair_y=[7070,7750,8440,9120]
    for side,cx in (('W',13950),('E',15610)):
        for idx,cy in enumerate(chair_y,1):
            _interior_box(f"SEL_CHAIR_{side}_{idx}_seat",'wnetrze_elementy','interior_cream',
                [[cx-230,cy-220,430],[cx+230,cy+220,510]],source,10,'selected','siedzisko krzesła',[49,51],'Alaska beżowe, nogi czarne')
            # back faces away from the table
            bx0,bx1=(cx-300,cx-210) if side=='W' else (cx+210,cx+300)
            _interior_box(f"SEL_CHAIR_{side}_{idx}_back",'wnetrze_elementy','interior_cream',
                [[bx0,cy-220,510],[bx1,cy+220,940]],source,10,'selected','oparcie krzesła',[49,51],'Alaska beżowe, nogi czarne')
            for dx,dy in ((-170,-150),(-170,150),(170,-150),(170,150)):
                _interior_box(f"SEL_CHAIR_{side}_{idx}_leg_{dx}_{dy}",'wnetrze_elementy','interior_metal',
                    [[cx+dx-15,cy+dy-15,30],[cx+dx+15,cy+dy+15,430]],source,10,'selected','noga krzesła',[51],'Alaska beżowe, nogi czarne')

    # Sofa Liquid / Soro 21 from p.49: 1.82 × 2.78 m, chaise arm depth 1.02 m.
    clone_block('SOFA','SAL_SOFA_LONG','interior_cream','Liquid / tkanina Soro 21')
    clone_block('SOFA','SAL_SOFA_CHAISE','interior_cream','Liquid / tkanina Soro 21')
    _interior_box('SEL_SOFA_back_long','wnetrze_elementy','interior_cream',
        [[16530,6660,400],[16730,9440,930]],source,10,'selected','oparcie długiego modułu',[11,14,15,49,51],'Liquid / Soro 21')
    _interior_box('SEL_SOFA_back_chaise','wnetrze_elementy','interior_cream',
        [[16530,6660,400],[18350,6860,830]],source,10,'selected','oparcie szezlonga',[11,14,15,49,51],'Liquid / Soro 21')
    _interior_box('SEL_SOFA_arm_end','wnetrze_elementy','interior_cream',
        [[17200,9200,420],[17430,9440,780]],source,10,'selected','podłokietnik',[11,14,15,49,51],'Liquid / Soro 21')
    for idx,(y0,y1) in enumerate(((6920,7650),(7750,8480),(8580,9310)),1):
        _interior_box(f'SEL_SOFA_seat_{idx}','wnetrze_elementy','interior_cream',
            [[16730,y0,545],[17360,y1,610]],source,10,'selected','poduszka siedziska',[14,15,49,51],'Liquid / Soro 21')
    _interior_box('SEL_SOFA_chaise_seat','wnetrze_elementy','interior_cream',
        [[17420,6880,545],[18280,7580,610]],source,10,'selected','poduszka szezlonga',[14,15,49,51],'Liquid / Soro 21')

    # Mustard accent armchair — position from p.49; rotation remains simplified in the proxy.
    _interior_box('SEL_ARMCHAIR_seat','wnetrze_elementy','interior_mustard',[[17720,9200,350],[18840,10020,550]],source,10,'selected','siedzisko fotela',[11,14,15,49,51],'Sensi / Soro 40')
    _interior_box('SEL_ARMCHAIR_back','wnetrze_elementy','interior_mustard',[[17820,9880,520],[18740,10220,1220]],source,10,'selected','oparcie fotela',[11,14,15,49,51],'Sensi / Soro 40')
    _interior_box('SEL_ARMCHAIR_arm_L','wnetrze_elementy','interior_mustard',[[17650,9240,500],[17920,9960,860]],source,10,'selected','podłokietnik',[11,14,15,49,51],'Sensi / Soro 40')
    _interior_box('SEL_ARMCHAIR_arm_R','wnetrze_elementy','interior_mustard',[[18620,9240,500],[18900,9960,860]],source,10,'selected','podłokietnik',[11,14,15,49,51],'Sensi / Soro 40')

    # Rug and coffee tables.
    clone_block('RUG','SAL_RUG','interior_cream','Hector 200×300 cm')
    for block_id in ('SAL_COFFEE_60','SAL_COFFEE_90'):
        clone_block('COFFEE',block_id,'interior_black','okrągły stolik kawowy 60/90 cm')

    # TV / fireplace wall from p.29. Whole composition = 4.710 m on east wall.
    # From north to south: 0.20 black wall + 0.75 cabinet + 2.30 concrete + 0.75 cabinet + 0.71 slats.
    x0,x1=20020.0,20060.0
    _interior_box('SEL_TV_black_return','wnetrze_elementy','interior_black',[[x0,10160,0],[x1,10360,2900]],source,10,'selected','ściana czarna 0,20 m',[29],'czarny mat')
    _interior_box('SEL_TV_cab_north','wnetrze_elementy','interior_black',[[x0,9410,0],[x1,10160,2900]],source,10,'selected','zabudowa meblowa 0,75 m',[29,30],'zabudowa meblowa')
    _interior_box('SEL_TV_concrete','wnetrze_elementy','interior_concrete',[[x0,7110,0],[x1,9410,2900]],source,10,'selected','beton architektoniczny 2,30 m',[29,30],'beton architektoniczny / SAFARI')
    _interior_box('SEL_TV_cab_south','wnetrze_elementy','interior_black',[[x0,6360,0],[x1,7110,2900]],source,10,'selected','zabudowa meblowa 0,75 m',[29,30],'zabudowa meblowa')
    _interior_box('SEL_TV_slats','wnetrze_elementy','interior_black',[[x0,5650,0],[x1,6360,2900]],source,10,'selected','lamele 0,71 m',[29,30],'czarny mat')
    # TV and 1.83 m fireplace centered in the 2.30 m concrete panel (0.235 m margins).
    _interior_box('SEL_TV_screen','wnetrze_elementy','interior_black',[[19915,7480,1250],[20015,9040,2050]],source,10,'selected','telewizor',[29,30],'TV')
    _interior_box('SEL_FIREPLACE_body','wnetrze_elementy','interior_black',[[19910,7345,250],[20015,9175,750]],source,10,'selected','kominek 1,83 m',[29,30,51],'Dimplex Sierra 72"')
    _interior_box('SEL_FIREPLACE_flame','wnetrze_elementy','interior_flame',[[19895,7440,390],[19910,9080,620]],source,10,'selected','płomień - proxy',[29,30,51],'Dimplex Sierra 72"')

    # South art wall p.31 = 4.10 m: concrete 2.75 m + wood slats 1.35 m.
    # Looking south, left side of the elevation is east in plan coordinates.
    _interior_box('SEL_ART_concrete','wnetrze_elementy','interior_concrete',[[17310,5920,0],[20060,5960,2900]],source,10,'selected','beton architektoniczny 2,75 m',[31],'beton architektoniczny / SAFARI')
    _interior_box('SEL_ART_slats','wnetrze_elementy','interior_oak',[[15960,5920,0],[17310,5960,2900]],source,10,'selected','lamele 1,35 m',[31],'dąb craft złoty')
    _interior_box('SEL_ART_picture','wnetrze_elementy','interior_black',[[17480,5895,700],[19480,5920,2200]],source,10,'selected','obraz 2,00 × 1,50 m',[31,51],'obraz 200×150 - zamówienie indywidualne')

    # Pantry p.33-p.36 — exact L-layout, NOT a U-layout.
    # South wall: 3.00 m base run, depth 0.60 m.
    # West wall: from south corner 0.71 m open shelves, then 0.70 m tall cabinet to the north.
    south=block_map['SPI_BASE']; side_open=block_map['SPI_SHELVES']; side_tall=block_map['SPI_TALL']
    clone_block('PANTRY_SOUTH','SPI_BASE','interior_black','zabudowa spiżarni - czarny mat')
    clone_block('PANTRY_TALL','SPI_TALL','interior_oak','wysoka szafa spiżarni - dąb craft złoty')
    sb=south['bbox_mm']
    _interior_box('SEL_PANTRY_countertop','wnetrze_elementy','interior_oak',
        [[sb[0][0],sb[0][1],900],[sb[1][0],sb[1][1],950]],source,14,'selected','blat 3,00 m',[33,34,36],'dąb craft złoty')

    # Open wall shelves above the 3.00 m south run, depth about 0.45 m per p.33.
    sx0,sy0=float(sb[0][0]),float(sb[0][1]); sx1=float(sb[1][0])
    for idx,z in enumerate((1500,1850,2200,2550,2875),1):
        _interior_box(f'SEL_PANTRY_south_shelf_{idx}','wnetrze_elementy','interior_black',
            [[sx0,sy0,z],[sx1,sy0+450,z+25]],source,14,'selected','otwarta półka nad ciągiem 3,00 m',[33,34,36],'zabudowa spiżarni')
    for idx,x in enumerate((sx0,sx0+600,sx0+1200,sx0+1800,sx0+2400,sx1-25),1):
        _interior_box(f'SEL_PANTRY_south_v_{idx}','wnetrze_elementy','interior_black',
            [[x,sy0,1450],[x+25,sy0+450,2900]],source,14,'selected','pion półek',[34,36],'zabudowa spiżarni')
    _interior_box('SEL_PANTRY_south_back','wnetrze_elementy','interior_oak',
        [[sx0,sy0,1450],[sx1,sy0+18,2900]],source,14,'selected','drewniany tył półek',[34,36],'dąb craft złoty')

    # West-side open shelves, 0.71 m long and approx. 0.35 m deep.
    ob=side_open['bbox_mm']; ox0,oy0,oz0=map(float,ob[0]); ox1,oy1,oz1=map(float,ob[1])
    for idx,z in enumerate((900,1300,1700,2100,2500,2875),1):
        _interior_box(f'SEL_PANTRY_west_shelf_{idx}','wnetrze_elementy','interior_black',
            [[ox0,oy0,z],[ox1,oy1,z+25]],source,14,'selected','półka zachodnia 0,71 m',[35,36],'zabudowa spiżarni')
    _interior_box('SEL_PANTRY_west_back','wnetrze_elementy','interior_oak',
        [[ox0,oy0,900],[ox0+18,oy1,2900]],source,14,'selected','drewniany tył półek zachodnich',[35,36],'dąb craft złoty')

    # Entry selected layer.
    clone_block('ENTRY_WARDROBE','HOL_WARDROBE','interior_black','zabudowa na wymiar')
    clone_block('ENTRY_CONSOLE','HOL_CONSOLE','interior_oak','konsola na wymiar')
    mirror=block_map['HOL_MIRROR']; _interior_box('SEL_ENTRY_MIRROR','wnetrze_elementy','interior_glass',
        mirror['bbox_mm'],source,1,'selected','lustro podświetlane 1,15 m',[39],'lustro podświetlane')
    pouf=block_map['HOL_POUF']; _interior_box('SEL_ENTRY_POUF','wnetrze_elementy','interior_cream',
        pouf['bbox_mm'],source,1,'selected','pufa 1,15 × 0,50 m',[17,18,49,51],'Pufa Puffy / podobna propozycja')

    # Full 1.5 m slatted wall with concealed door (drawing p.41), at the corrected wall segment.
    sl=block_map['HOL_SLAT_WALL']['bbox_mm']; y0,y1=float(sl[0][1]),float(sl[1][1]); count=24; step=(y1-y0)/count
    for i in range(count):
        sy=y0+i*step+step*0.18
        ey=y0+(i+1)*step-step*0.18
        _interior_box(f'SEL_ENTRY_SLAT_{i+1:02}','wnetrze_elementy','interior_oak',
            [[sl[0][0],sy,30],[sl[1][0],ey,2900]],source,1,'selected','lamela / drzwi ukryte',[40,41],'dąb craft złoty')

    # South entrance wall p.40: 0.65 m slatted return at the west end + vertical metal hangers.
    # Elevation is mirrored relative to plan coordinates, hence the west-side placement.
    x0=10310.0; south_y=2960.0
    slat_w=650.0; count2=12; step2=slat_w/count2
    for i in range(count2):
        sx=x0+i*step2+step2*0.18
        ex=x0+(i+1)*step2-step2*0.18
        _interior_box(f'SEL_ENTRY_SOUTH_SLAT_{i+1:02}','wnetrze_elementy','interior_oak',
            [[sx,south_y,30],[ex,south_y+45,2900]],source,1,'selected','lamele na ścianie wejściowej',[40],'dąb craft złoty')
    for idx,x in enumerate((11120,11380,11660,12020),1):
        _interior_box(f'SEL_ENTRY_HOOK_RAIL_{idx}','wnetrze_elementy','interior_metal',
            [[x,south_y,180],[x+28,south_y+35,2750]],source,1,'selected','pionowy wieszak metalowy',[40],'wieszak metalowy')


def add_georeferenced_house_overlay():
    """Tworzy kopię zewnętrznej bryły domu w aktualnej pozycji georeferencyjnej.

    Transformacja pochodzi z geoportal_teren.json. Preferowany jest obrys EGiB,
    a przy jego braku — dopasowanie do rzeczywistego dachu na ortofotomapie.
    """
    if not GEO_REAL or GEO_REAL.get('status') != 'fetched':
        return
    cal=((GEO_REAL.get('alignment') or {}).get('house_calibration') or {})
    M=cal.get('model_to_geo_local_affine_mm')
    if not M:
        print('Geo house: brak geodezyjnej macierzy domu - pomijam overlay.')
        return
    M=np.asarray(M,dtype=float)
    allowed={'sciany','uzupelnienia','stolarka','elewacja','daszek','strop','dach'}
    snapshot=[rec for rec in parts if rec.get('category') in allowed]
    count=0
    for rec in snapshot:
        src_mesh=meshes[rec['name']]
        m=src_mesh.copy()
        vv=np.asarray(m.vertices,dtype=float).copy()
        xy_mm=np.column_stack([vv[:,0]*1000.0,vv[:,1]*1000.0,np.ones(len(vv))])
        out=(M @ xy_mm.T).T
        vv[:,0]=out[:,0]/1000.0
        vv[:,1]=out[:,1]/1000.0
        m.vertices=vv
        add_mesh_record(
            'GEO_DOM_'+rec['name'],
            'dom_geo',
            rec['material'],
            m,
            'Geoportal / dopasowanie domu do danych rzeczywistych',
            False,
            'Georeferencjonowana kopia elementu domu; transformacja wg bieżącej kalibracji EGiB/ortofotomapy.',
            rec.get('source_id',''),
            {
                'geo_house':True,
                'geo_house_original_name':rec['name'],
                'geo_house_method':cal.get('method'),
                'geo_house_manual_rotation_deg':cal.get('manual_rotation_deg',0.0),
                'geo_house_manual_offset_m':cal.get('manual_offset_m',[0.0,0.0]),
                'geo_house_affine_error_mm':cal.get('affine_linearization_error_mm'),
            },
            rec.get('plan_area_m2')
        )
        parts[-1]['color']=list(rec['color'])
        count+=1
    print(f'Geo house: dodano {count} georeferencjonowanych elementow domu.')


def add_geoportal_real_layers():
    """Dodaje pobrany NMT, ortofotomapę i granicę działki do wspólnej sceny."""
    if not GEO_REAL or GEO_REAL.get('status') != 'fetched':
        print('Geoportal: brak geoportal_teren.json - pomijam warstwę rzeczywistą.')
        return
    count=0
    for item in GEO_REAL.get('parts',[]):
        vertices=np.asarray(item.get('positions_m',[]),dtype=float)
        faces=np.asarray(item.get('faces',[]),dtype=int)
        if len(vertices)<3 or len(faces)<1:
            continue
        mesh=trimesh.Trimesh(vertices=vertices,faces=faces,process=False)
        extras={
            'geoportal_real': True,
            'geoportal_generated_at_utc': GEO_REAL.get('generated_at_utc'),
            'geoportal_alignment': GEO_REAL.get('alignment'),
            'geoportal_validation': GEO_REAL.get('validation'),
        }
        add_mesh_record(
            item.get('name',f'GEO_{count:04d}'),
            item.get('category','teren_rzeczywisty'),
            item.get('material','teren_rzeczywisty'),
            mesh,
            item.get('source','Geoportal / GUGiK'),
            bool(item.get('assumed',False)),
            item.get('note',''),
            item.get('source_id','GEO'),
            extras,
            item.get('reference_area_m2')
        )
        # Kafle ortofoto mają własny kolor pobrany z rastra; GLB/HTML zachowują go per obiekt.
        if item.get('color'):
            parts[-1]['color']=[float(v) for v in item['color']]
        count+=1
    print(f'Geoportal: dodano {count} elementów rzeczywistego terenu / ortofoto.')


def main():
    print("Rozpoczynanie generowania geometrii z aktualnym zestawieniem okien...")
    facade = Polygon(DATA['facade_reference_outline']['polygon_mm'])
    H = float(PARAM['wall_top_mm'])  # 3100 mm do spodu stropu
    CEILING = float(PARAM['ceiling_level_mm'])  # 2850 mm
    GARAGE_OFFSET = float(PARAM.get('garage_floor_offset_mm', 0))
    openings = []

    # Profile scian z projektu zawieraja pierwotne szczeliny okienne.
    # Najpierw je wypelniamy, a dopiero potem wycinamy aktualna stolarke po pomiarze.
    old_window_gaps = [box(*w['core_opening_bbox_mm']) for w in DATA['windows']]
    all_walls_2d = unary_union([Polygon(p['polygon_mm']) for p in DATA['wall_cut_profiles']] + old_window_gaps)

    # Otwory we wszystkich scianach na poziomie rzutu (okna + drzwi + przejscia)
    all_window_openings_2d = unary_union([box(*w['core_opening_bbox_mm']) for w in WINDOWS])
    all_door_openings_2d = unary_union([box(*d['core_opening_bbox_mm']) for d in DATA['doors']])
    all_passage_openings_2d = unary_union([box(*p['core_opening_bbox_mm']) for p in DATA['unlabelled_passages']])
    all_cuts = unary_union([all_window_openings_2d, all_door_openings_2d, all_passage_openings_2d])

    wall_cores = all_walls_2d.difference(all_cuts)

    # 1. Sciany nośne i słupy
    add(
        'SCIANY_rdzenie',
        'sciany',
        'sciany',
        wall_cores,
        0,
        H,
        source=f'Sciany nosne parteru: wysokosc H = {H/1000:.2f} m (do spodu stropu)',
        note=f'Wysokosc muru do spodu stropu od gotowej posadzki: {H/1000:.2f} m.'
    )

    # 2. Okna wg okna_projektowe.json
    for rec in WINDOWS:
        level_offset = GARAGE_OFFSET if int(rec.get('room_number', -1)) == 13 else 0.0
        z0 = float(rec['sill_mm']) + level_offset
        z1 = float(rec['top_mm']) + level_offset
        p = bbox(rec['core_opening_bbox_mm'])
        meta = dict(
            source=f"Okno {rec['id']} ({rec['nominal_width_mm']/10:.0f}×{(z1-z0)/10:.0f} cm)",
            assumed=False,
            source_id=rec['id'],
            note=rec.get('note', ''),
            extras={'sill_used_mm': z0, 'opening_top_used_mm': z1, 'level_offset_mm': level_offset}
        )
        if z0 > 0:
            add(rec['id'] + '_mur_pod_oknem', 'uzupelnienia', 'uzupelnienia', p, 0, z0, **meta)
        if z1 < H:
            add(rec['id'] + '_mur_nad_oknem', 'uzupelnienia', 'uzupelnienia', p, z1, H, **meta)
        op = {'id': rec['id'], 'geometry': boundary_opening(rec, facade), 'bottom': z0, 'top': z1}
        openings.append(op)
        make_window(rec, z0, z1)

    # 3. Drzwi i brama
    for rec in DATA['doors']:
        a, b, c, d = map(float, rec['core_opening_bbox_mm'])
        spec = EXTERIOR_JOINERY.get(rec['id'])
        base_z = GARAGE_OFFSET if rec['id'] == 'DR01' else 0.0
        height = float(spec['opening_height_mm'] if spec else PARAM['door_opening_height_overrides_mm'].get(rec['id'], PARAM['door_opening_height_mm']))
        opening_top = base_z + height
        source_name = spec['source_file'] if spec else 'Projekt budowlany / zalozenia robocze'
        add(
            rec['id'] + '_mur_nad_drzwiami',
            'uzupelnienia',
            'uzupelnienia',
            box(a, b, c, d),
            opening_top,
            H,
            source=f'{source_name}: otwor od +{base_z/1000:.2f} do +{opening_top/1000:.2f} m',
            assumed=spec is None,
            source_id=rec['id'],
            note=(spec.get('note','') if spec else ''),
            extras={'nominal_height_mm': (spec.get('product_height_mm') if spec else rec['nominal_height_mm']),
                    'opening_height_used_mm': height, 'opening_bottom_used_mm': base_z, 'opening_top_used_mm': opening_top,
                    'offer_number': (spec.get('offer_number') if spec else None)}
        )

        thick = float(PARAM['symbolic_door_leaf_thickness_mm'])
        if spec and spec['kind'] == 'garage_gate':
            width = float(spec['product_width_mm'])
            x0 = (a + c - width) / 2
            x1 = x0 + width
            y0 = (b + d - thick) / 2
            y1 = (b + d + thick) / 2
            common = dict(
                source=spec['source_file'],
                assumed=False,
                source_id=rec['id'],
                note=spec['note'],
                extras={
                    'offer_number': spec['offer_number'],
                    'manufacturer': spec['manufacturer'],
                    'product': spec['product'],
                    'product_width_mm': width,
                    'product_height_mm': spec['product_height_mm'],
                    'panel_type': spec['panel_type'],
                    'panel_thickness_mm': spec['panel_thickness_mm'],
                    'exterior_color': spec['exterior_color'],
                    'interior_color': spec['interior_color'],
                    'drive': spec['drive'],
                    'uw_w_m2k': spec['uw_w_m2k']
                }
            )
            add(rec['id'] + '_brama_panel', 'stolarka', 'brama', box(x0, y0, x1, y1), base_z, opening_top, **common)
            sections = int(spec.get('section_count_model', 5))
            for j in range(1, sections):
                z = base_z + height * j / sections
                add(rec['id'] + f'_brama_linia_{j}', 'stolarka', 'brama_linia',
                    box(x0 + 20, y0 - 3, x1 - 20, y1 + 3), z - 5, z + 5, **common)

        elif spec and spec['kind'] == 'entrance_door':
            width = float(spec['product_width_mm'])
            x0 = (a + c - width) / 2
            x1 = x0 + width
            y0 = (b + d - thick) / 2
            y1 = (b + d + thick) / 2
            side_w = float(spec['sidelight_width_mm'])
            leaf_w = float(spec['leaf_width_mm'])
            sx0, sx1 = x0, x0 + side_w
            lx0, lx1 = sx1, x1
            frame = 65.0
            common = dict(
                source=spec['source_file'],
                assumed=False,
                source_id=rec['id'],
                note=spec['note'],
                extras={
                    'offer_number': spec['offer_number'],
                    'manufacturer': spec['manufacturer'],
                    'system': spec['system'],
                    'product_width_mm': width,
                    'product_height_mm': spec['product_height_mm'],
                    'leaf_width_mm': leaf_w,
                    'sidelight_width_mm': side_w,
                    'opening_direction': spec['opening_direction'],
                    'leaf_color': spec['leaf_color'],
                    'sidelight_glass': spec['sidelight_glass'],
                    'pull_handle': spec['pull_handle'],
                    'under_threshold_support_mm': spec['under_threshold_support_mm']
                }
            )
            # Skrzydlo drzwiowe.
            add(rec['id'] + '_skrzydlo_ALTUS', 'stolarka', 'drzwi_antracyt',
                box(lx0, y0, lx1, y1), base_z, opening_top, **common)

            # Doswietle po lewej w widoku zewnetrznym: rama + matowe szklo.
            add(rec['id'] + '_doswietle_rama_dol', 'stolarka', 'drzwi_antracyt',
                box(sx0, y0, sx1, y1), base_z, base_z+frame, **common)
            add(rec['id'] + '_doswietle_rama_gora', 'stolarka', 'drzwi_antracyt',
                box(sx0, y0, sx1, y1), opening_top-frame, opening_top, **common)
            add(rec['id'] + '_doswietle_rama_lewa', 'stolarka', 'drzwi_antracyt',
                box(sx0, y0, sx0+frame, y1), base_z+frame, opening_top-frame, **common)
            add(rec['id'] + '_doswietle_rama_prawa', 'stolarka', 'drzwi_antracyt',
                box(sx1-frame, y0, sx1, y1), base_z+frame, opening_top-frame, **common)
            glass_depth = 12.0
            gy0, gy1 = (b+d-glass_depth)/2, (b+d+glass_depth)/2
            add(rec['id'] + '_doswietle_szklo_matowe', 'stolarka', 'szklo_matowe',
                box(sx0+frame, gy0, sx1-frame, gy1), base_z+frame, opening_top-frame, **common)

            # Trzy poziome frezy z widoku zewnetrznego - jako subtelne ciemne linie.
            exterior_y0 = y0 - 5
            exterior_y1 = y0 + 5
            for j, z in enumerate((620.0, 1090.0, 1560.0), 1):
                add(rec['id'] + f'_frez_{j}', 'stolarka', 'metal_czarny',
                    box(lx0+300, exterior_y0, lx1-110, exterior_y1), z-4, z+4, **common)

            # Pochwyt Amsterdam 1800 mm przy lewej krawedzi skrzydla (widok zewnetrzny).
            hx = lx0 + 145
            add(rec['id'] + '_pochwyt_Amsterdam_1800', 'stolarka', 'metal_czarny',
                box(hx-14, y0-28, hx+14, y0-8), 150, 1950, **common)
            add(rec['id'] + '_prog', 'stolarka', 'metal_czarny',
                box(x0, y0, x1, y1), base_z, base_z+35, **common)

        else:
            width = rec['nominal_width_mm']
            if rec['orientation_in_plan'] == 'horizontal':
                g = box((a + c - width) / 2, (b + d - thick) / 2, (a + c + width) / 2, (b + d + thick) / 2)
            else:
                g = box((a + c - thick) / 2, (b + d - width) / 2, (a + c + thick) / 2, (b + d + width) / 2)
            add(
                rec['id'] + '_' + rec['source_tag'] + '_symbol',
                'stolarka',
                'drzwi',
                g,
                base_z,
                opening_top,
                source='Skrzydlo drzwiowe na gotowo',
                assumed=True,
                source_id=rec['id'],
                extras={'nominal_width_mm': width, 'nominal_height_mm': height}
            )

        add(
            rec['id'] + '_powierzchnia_w_przejsciu',
            'podlogi',
            'progi',
            box(a, b, c, d),
            base_z,
            None,
            source=f'Poziom posadzki +{base_z/1000:.2f} m',
            source_id=rec['id']
        )
        if rec['id'] in ['DR01', 'DR02']:
            openings.append({'id': rec['id'], 'geometry': boundary_opening(rec, facade), 'bottom': base_z, 'top': opening_top, 'assumed': spec is None})

    # 4. Przejscia otwarte
    for rec in DATA['unlabelled_passages']:
        h_pass = float(PARAM.get('unlabelled_passage_height_mm', CEILING))
        add(
            rec['id'] + '_mur_nad_przejsciem',
            'uzupelnienia',
            'uzupelnienia',
            bbox(rec['core_opening_bbox_mm']),
            h_pass,
            H,
            source='Przejscie otwarte do sufitu',
            assumed=True,
            source_id=rec['id']
        )
        add(
            rec['id'] + '_powierzchnia_w_przejsciu',
            'podlogi',
            'progi',
            bbox(rec['core_opening_bbox_mm']),
            0,
            None,
            source='Poziom posadzki 0',
            source_id=rec['id']
        )

    # 5. Izolacja zewnetrzna
    core_envelope = facade.buffer(-PARAM['external_insulation_mm'], join_style='mitre')
    insulation = facade.difference(core_envelope)
    heights = sorted(set([0, H] + [o[k] for o in openings for k in ['bottom', 'top']]))
    for i, (lo, hi) in enumerate(zip(heights, heights[1:]), 1):
        mid = (lo + hi) / 2
        cut = unary_union([o['geometry'] for o in openings if o['bottom'] <= mid < o['top']])
        layer = insulation.difference(cut)
        add(f'IZ_{i:02}_z_{int(lo)}_{int(hi)}', 'izolacja', 'izolacja', layer, lo, hi, source='Izolacja elewacji 260 mm', assumed=True)

    # 6. Pomieszczenia: podlogi i sufity
    for room in DATA['rooms']:
        p = Polygon(room['floor_reference_polygon_mm'])
        nm = f"{room['id']}_{ascii_name(room['name'])}"
        meta = dict(
            source=f"Rzut pomieszczenia; sufit podwieszany na gotowo: +{CEILING/1000:.2f} m",
            source_id=room['id'],
            extras={'room_number': room['number'], 'room_name': room['name'], 'reported_area_m2': room['reported_area_m2']}
        )
        floor_z = GARAGE_OFFSET if int(room['number']) == 13 else 0.0
        meta['extras']['floor_level_mm'] = floor_z
        add(nm + '_posadzka', 'podlogi', 'podlogi', p, floor_z, None, **meta)
        add(nm + f'_sufit_z_{int(CEILING)}', 'sufity', 'sufity', p, CEILING, None, **meta)

    # 7. Dach, strop i attyka
    roof_outer = Polygon(ROOF['outer_polygon_mm'])
    roof_inner = Polygon(ROOF['inner_polygon_mm'])
    add('STROP_plyta_180mm', 'strop', 'strop', core_envelope, H, H + PARAM['slab_thickness_mm'], source='Plyta zelbetowa 180 mm nad murem', assumed=True)
    add('STROP_izolacja_obwodowa', 'strop', 'izolacja', insulation, H, H + PARAM['slab_thickness_mm'], source='Izolacja obwodowa czola stropu', assumed=True)
    add('DACH_wypelnienie_BEZ_SPADKOW', 'dach', 'dach', roof_inner, H + PARAM['slab_thickness_mm'], PARAM['simplified_roof_surface_mm'], source='Polac dachu ze spadkiem', assumed=True)
    add('DACH_attyka', 'dach', 'attyka', roof_outer.difference(roof_inner), H + PARAM['slab_thickness_mm'], PARAM['parapet_top_mm'], source='Attyka nad plyta stropowa', assumed=True)

    # 8. Daszek nad wejsciem glownym wg zdjecia z budowy i slupa P01.
    canopy=PARAM.get('entrance_canopy',{})
    if canopy:
        add('DASZEK_wejscie_beton','daszek','daszek_beton',
            box(float(canopy['x_min_mm']),float(canopy['y_min_mm']),float(canopy['x_max_mm']),float(canopy['y_max_mm'])),
            float(canopy['z_bottom_mm']),float(canopy['z_top_mm']),source='daszek.jpg + rzut parteru (slup P01)',
            assumed=False,note=canopy.get('note',''),source_id='DASZEK_WEJSCIE')
        col=canopy.get('column')
        if col:
            half=float(col['size_mm'])/2
            add('DASZEK_slup_beton','daszek','daszek_beton',
                box(float(col['x_mm'])-half,float(col['y_mm'])-half,float(col['x_mm'])+half,float(col['y_mm'])+half),
                float(col['z_bottom_mm']),float(canopy['z_bottom_mm']),source='daszek.jpg - zewnetrzny slup zelbetowy',
                assumed=False,note='Slup pod zewnetrznym naroznikiem daszku odwzorowany ze zdjecia z budowy.',source_id='DASZEK_SLUP')

    # 9. Elewacja: rysunki projektowe definiuja TYLKO strefy materialowe.
    # Otwory bierzemy wylacznie z aktualnej geometrii (okna po pomiarze + drzwi/brama),
    # aby stare okna z elewacji PDF nie wracaly jako dziury w wykonczeniu.
    project_top=float(ELEVATIONS.get('project_top_mm',3940.0)); actual_top=float(PARAM.get('parapet_top_mm',project_top))
    def lift(coords):
        return [(float(a),actual_top if float(z)>=project_top-12 else float(z)) for a,z in coords]
    current_openings=opening_elevation_masks(openings,facade)
    side_shapes={k:[] for k in ('east','west','south','north')}
    lifted_patches=[]
    for patch in ELEVATIONS.get('patches',[]):
        # Intentionally ignore holes stored in the old elevation artwork.
        # They represent the historic/project joinery, not the current measured model.
        poly_sz=Polygon(lift(patch['polygon_sz_mm']['exterior']))
        if not poly_sz.is_valid: poly_sz=poly_sz.buffer(0)
        lifted_patches.append((patch,poly_sz))
        side_shapes[patch['side']].append(poly_sz)

    # One continuous warm ecru base per facade side. This avoids the visual effect
    # of many separate wall layers and keeps the parapet finish continuous.
    for side,shapes in side_shapes.items():
        if not shapes: continue
        silhouette=unary_union(shapes).difference(current_openings[side])
        src='DWK_2021-001-PZT_PAB.pdf s.26-27 - bazowa elewacja ecru'
        add_vertical_patch('ELEW_BAZA_'+side,'elewacja_biala',side,silhouette,facade,0.35,src,'ELEW_BASE_'+side,{'facade_side':side})

    # Add only accent zones (gray and wood) over the ecru base, also cut by the
    # current openings. Tiny sub-millimetre offsets are only to avoid z-fighting.
    for patch,poly_sz in lifted_patches:
        if patch['material']=='elewacja_biala':
            continue
        poly_sz=poly_sz.difference(current_openings[patch['side']])
        if poly_sz.is_empty: continue
        src=f"DWK_2021-001-PZT_PAB.pdf s.{patch['source']['pdf_page']} - elewacja {patch['side']}"
        extras={'facade_side':patch['side'],'source_page':patch['source']['pdf_page'],'source_drawing_index':patch['source']['drawing_index_0based']}
        outward=0.60
        add_vertical_patch('ELEW_'+patch['id'],patch['material'],patch['side'],poly_sz,facade,outward,src,patch['id'],extras)
        if patch.get('wood_horizontal_slats'):
            minz,maxz=poly_sz.bounds[1],poly_sz.bounds[3]; zline=math.ceil((minz+40)/200.0)*200.0; n=0
            while zline<maxz-25:
                band=poly_sz.intersection(box(-1e6,zline-3,1e6,zline+3))
                if not band.is_empty:
                    n+=1; add_vertical_patch('ELEW_'+patch['id']+f'_fuga_{n:02}','elewacja_drewno_fuga',patch['side'],band,facade,0.85,src,patch['id'],extras)
                zline+=200.0

    # 10. PZT / podworko / teren. Obrysy sa wektorowe, wysokosc terenu jest uproszczona plaszczyzna.
    tc=SITE['terrain_model']; ref_x=float(tc['reference_x_mm']); ref_z=float(tc['reference_z_mm']); sx=float(tc['slope_x_mm_per_mm']); sy=float(tc.get('slope_y_mm_per_mm',0.0))
    terrain_min=float(tc.get('min_z_mm',-1e9)); terrain_max=float(tc.get('max_z_mm',1e9))
    def terrain_z(x,y):
        raw=ref_z+sx*(x-ref_x)+sy*y
        return max(terrain_min,min(terrain_max,raw))
    lawn=geometry_from_serial(SITE['areas']['lawn']); paving=geometry_from_serial(SITE['areas']['paving']); terrace=geometry_from_serial(SITE['areas']['terrace'])
    add_surface('TEREN_trawnik_PZT','teren','teren_trawa',lawn,terrain_z,'DWK_2021-001-PZT_PAB.pdf s.15 - nawierzchnia biologicznie czynna',True,tc.get('basis',''),'PZT_LAWN')
    poff=float(tc.get('paving_offset_from_natural_mm',-100.0))
    add_surface('PODWORKO_kostka_PZT','nawierzchnie','kostka',paving,lambda x,y:terrain_z(x,y)+poff,'DWK_2021-001-PZT_PAB.pdf s.15 - utwardzenie z kostki betonowej',True,'Obrys z wektorow PZT; pion wg uogolnionego spadku terenu.','PZT_PAVING')
    planter=0
    for pp in polygons(paving):
        for ring in pp.interiors:
            planter+=1
            add_surface(f'DONICA_PZT_{planter:02}','nawierzchnie','ziemia',Polygon(ring),lambda x,y:terrain_z(x,y)+poff+35.0,'DWK_2021-001-PZT_PAB.pdf s.15 - donice / przerwy w utwardzeniu',True,'','PZT_PLANTER')
    ttop=float(tc.get('terrace_top_z_mm',-20.0)); tth=float(tc.get('terrace_slab_thickness_mm',180.0))
    add('TARAS_PZT','nawierzchnie','taras',terrace,ttop-tth,ttop,'DWK_2021-001-PZT_PAB.pdf s.15 - projektowany taras',True,'Obrys tarasu z PZT; poziom gorny roboczo 20 mm ponizej posadzki.','PZT_TERRACE')
    st=SITE.get('stairs',{}).get('north_terrace')
    if st:
        count=int(st['count']); rise=float(st['rise_mm']); run=float(st['run_mm']); width=float(st['width_mm']); cy=float(st['center_y_mm']); start=float(st['start_x_mm']); base=ttop-count*rise-180.0
        for i in range(1,count+1):
            top=ttop-i*rise; x0=start+(i-1)*run; x1=start+i*run
            add(f'SCHODY_tarasu_{i:02}','schody','schody',box(x0,cy-width/2,x1,cy+width/2),base,top,'DWK_2021-001-PZT_PAB.pdf s.26-27 - schody przy tarasie',True,st.get('note',''),'STAIRS_NORTH')

    # 11. Geodezyjna kopia bryły domu na bazie siatki PZT.
    add_georeferenced_house_overlay()

    # 12. Geoportal / rzeczywisty NMT + ortofotomapa.
    add_geoportal_real_layers()

    # 13. Wnętrze z projektu — dwie niezależne warstwy: bloki i elementy.
    add_interior_layers()

    print(f"Wygenerowano {len(parts)} elementow.")

    # GLB
    Y_UP = np.array([[1,0,0,0],[0,0,1,0],[0,-1,0,0],[0,0,0,1]], dtype=float)
    def export_glb(filename: str, include_roof: bool):
        scene = trimesh.Scene(base_frame='DOM')
        for rec in parts:
            if rec['category'] in ['sufity','dom_geo']:
                continue
            if not include_roof and rec['category'] in ['dach','strop','elewacja','daszek','teren','nawierzchnie','schody','teren_rzeczywisty','ortofoto','granica_dzialki','budynki_otoczenia','drzewa']:
                continue
            mesh = meshes[rec['name']].copy()
            mesh.unmerge_vertices()
            color = np.array(rec['color']) * 255
            material = trimesh.visual.material.PBRMaterial(
                name=rec['material'],
                baseColorFactor=color.astype(np.uint8),
                metallicFactor=0.0,
                roughnessFactor=0.82,
                alphaMode='BLEND' if float(rec['color'][3]) < 0.999 else 'OPAQUE',
                doubleSided=True
            )
            mesh.visual = trimesh.visual.TextureVisuals(material=material)
            mesh.apply_transform(Y_UP)
            metadata = {k: v for k, v in rec.items() if k not in ['bbox_mm', 'color'] and v is not None}
            scene.add_geometry(mesh, node_name=rec['name'], geom_name=rec['name'], metadata=metadata)
        (ROOT / filename).write_bytes(trimesh.exchange.gltf.export_glb(scene, include_normals=True))
        print(f"Zapisano: {filename}")

    export_glb('dom_wnetrze.glb', False)
    export_glb('dom_bryla.glb', True)

    # OBJ + MTL
    obj = ['# Model roboczy domu z aktualnymi oknami. Units: meters. Z-up.', 'mtllib dom_materialy.mtl']
    offset = 0
    for rec in parts:
        if rec['category'] in ['sufity','dom_geo']:
            continue
        m = meshes[rec['name']]
        obj += [f"o {rec['name']}", f"g {GROUP_NAMES[rec['category']]}", f"usemtl {rec['material']}"]
        obj += [f'v {a:.7f} {b:.7f} {c:.7f}' for a, b, c in m.vertices]
        obj += ['f ' + ' '.join(str(int(x) + offset + 1) for x in f) for f in m.faces]
        offset += len(m.vertices)
    (ROOT / 'dom_model.obj').write_text('\n'.join(obj) + '\n', encoding='utf-8')
    mtl=['# Materialy modelu domu i otoczenia.']
    for mat,c in COLORS.items():
        mtl.extend([f'newmtl {mat}',f'Kd {c[0]} {c[1]} {c[2]}',f'd {c[3]}','Ka 0.08 0.08 0.08','Ks 0.06 0.06 0.06','Ns 16',''])
    (ROOT / 'dom_materialy.mtl').write_text('\n'.join(mtl).rstrip()+'\n',encoding='utf-8')
    print("Zapisano: dom_model.obj + dom_materialy.mtl")

    # scena_modelu.json
    scene_records = []
    for rec in parts:
        m = meshes[rec['name']]
        scene_records.append({**rec, 'positions_m': np.round(m.vertices, 7).tolist(), 'faces': m.faces.tolist()})
    (ROOT / 'scena_modelu.json').write_text(
        json.dumps({'units': 'm', 'up_axis': 'Z', 'geo_alignment': (GEO_REAL or {}).get('alignment'), 'geo_validation': (GEO_REAL or {}).get('validation'), 'parts': scene_records}, ensure_ascii=False, separators=(',', ':')),
        encoding='utf-8'
    )
    print("Zapisano: scena_modelu.json")

    # Aktualizacja podgladu HTML
    import subprocess
    subprocess.run([sys.executable, str(ROOT / 'aktualizuj_podglad.py')], check=True)
    print("Sukces! Zaktualizowano okna oraz podglad_3d.html!")

if __name__ == '__main__':
    main()
