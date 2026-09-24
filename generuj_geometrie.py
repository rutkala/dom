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
import unicodedata
from pathlib import Path
from typing import Any

import numpy as np
import trimesh
from shapely.geometry import Polygon, MultiPolygon, GeometryCollection, box
from shapely.ops import unary_union

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

ROOT = Path(__file__).resolve().parent
DATA = json.loads((ROOT / 'dane_zrodlowe.json').read_text(encoding='utf-8'))
PARAM = json.loads((ROOT / 'parametry_modelu.json').read_text(encoding='utf-8'))
ROOF = json.loads((ROOT / 'obrys_dachu_z_pdf.json').read_text(encoding='utf-8'))
WINDOWS = json.loads((ROOT / 'okna_projektowe.json').read_text(encoding='utf-8'))
EXTERIOR_JOINERY = json.loads((ROOT / 'stolarka_zewnetrzna.json').read_text(encoding='utf-8'))

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
    'strop': [0.72, 0.73, 0.74, 1.0],
    'dach': [0.38, 0.41, 0.43, 1.0],
    'attyka': [0.91, 0.90, 0.86, 1.0],
    'sufity': [0.94, 0.94, 0.92, 1.0],
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

def main():
    print("Rozpoczynanie generowania geometrii z aktualnym zestawieniem okien...")
    facade = Polygon(DATA['facade_reference_outline']['polygon_mm'])
    H = float(PARAM['wall_top_mm'])  # 3100 mm do spodu stropu
    CEILING = float(PARAM['ceiling_level_mm'])  # 2850 mm
    openings = []

    # Zbierzmy wszystkie sciany bazy z rzutu + uzupelnienia starych przerw
    old_w04 = box(16760, 2660, 17760, 2960) # usuniete okno w lazience/pralni
    old_w11 = box(10223.6, 9360, 12223.6, 9660) # stara pozycja okna w kuchni
    all_walls_2d = unary_union([Polygon(p['polygon_mm']) for p in DATA['wall_cut_profiles']] + [old_w04, old_w11])

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
        z0 = float(rec['sill_mm'])
        z1 = float(rec['top_mm'])
        p = bbox(rec['core_opening_bbox_mm'])
        meta = dict(
            source=f"Okno {rec['id']} ({rec['nominal_width_mm']/10:.0f}×{(z1-z0)/10:.0f} cm)",
            assumed=False,
            source_id=rec['id'],
            note=rec.get('note', ''),
            extras={'sill_used_mm': z0, 'opening_top_used_mm': z1}
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
        height = float(spec['opening_height_mm'] if spec else PARAM['door_opening_height_overrides_mm'].get(rec['id'], PARAM['door_opening_height_mm']))
        source_name = spec['source_file'] if spec else 'Projekt budowlany / zalozenia robocze'
        add(
            rec['id'] + '_mur_nad_drzwiami',
            'uzupelnienia',
            'uzupelnienia',
            box(a, b, c, d),
            height,
            H,
            source=f'{source_name}: wysokosc otworu {height/1000:.2f} m',
            assumed=spec is None,
            source_id=rec['id'],
            note=(spec.get('note','') if spec else ''),
            extras={'nominal_height_mm': (spec.get('product_height_mm') if spec else rec['nominal_height_mm']),
                    'opening_height_used_mm': height,
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
            add(rec['id'] + '_brama_panel', 'stolarka', 'brama', box(x0, y0, x1, y1), 0, height, **common)
            sections = int(spec.get('section_count_model', 5))
            for j in range(1, sections):
                z = height * j / sections
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
                box(lx0, y0, lx1, y1), 0, height, **common)

            # Doswietle po lewej w widoku zewnetrznym: rama + matowe szklo.
            add(rec['id'] + '_doswietle_rama_dol', 'stolarka', 'drzwi_antracyt',
                box(sx0, y0, sx1, y1), 0, frame, **common)
            add(rec['id'] + '_doswietle_rama_gora', 'stolarka', 'drzwi_antracyt',
                box(sx0, y0, sx1, y1), height-frame, height, **common)
            add(rec['id'] + '_doswietle_rama_lewa', 'stolarka', 'drzwi_antracyt',
                box(sx0, y0, sx0+frame, y1), frame, height-frame, **common)
            add(rec['id'] + '_doswietle_rama_prawa', 'stolarka', 'drzwi_antracyt',
                box(sx1-frame, y0, sx1, y1), frame, height-frame, **common)
            glass_depth = 12.0
            gy0, gy1 = (b+d-glass_depth)/2, (b+d+glass_depth)/2
            add(rec['id'] + '_doswietle_szklo_matowe', 'stolarka', 'szklo_matowe',
                box(sx0+frame, gy0, sx1-frame, gy1), frame, height-frame, **common)

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
                box(x0, y0, x1, y1), 0, 35, **common)

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
                0,
                height,
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
            0,
            None,
            source='Poziom posadzki 0',
            source_id=rec['id']
        )
        if rec['id'] in ['DR01', 'DR02']:
            openings.append({'id': rec['id'], 'geometry': boundary_opening(rec, facade), 'bottom': 0, 'top': height, 'assumed': spec is None})

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
        add(nm + '_posadzka', 'podlogi', 'podlogi', p, 0, None, **meta)
        add(nm + f'_sufit_z_{int(CEILING)}', 'sufity', 'sufity', p, CEILING, None, **meta)

    # 7. Dach, strop i attyka
    roof_outer = Polygon(ROOF['outer_polygon_mm'])
    roof_inner = Polygon(ROOF['inner_polygon_mm'])
    add('STROP_plyta_180mm', 'strop', 'strop', core_envelope, H, H + PARAM['slab_thickness_mm'], source='Plyta zelbetowa 180 mm nad murem', assumed=True)
    add('STROP_izolacja_obwodowa', 'strop', 'izolacja', insulation, H, H + PARAM['slab_thickness_mm'], source='Izolacja obwodowa czola stropu', assumed=True)
    add('DACH_wypelnienie_BEZ_SPADKOW', 'dach', 'dach', roof_inner, H + PARAM['slab_thickness_mm'], PARAM['simplified_roof_surface_mm'], source='Polac dachu ze spadkiem', assumed=True)
    add('DACH_attyka', 'dach', 'attyka', roof_outer.difference(roof_inner), H + PARAM['slab_thickness_mm'], PARAM['parapet_top_mm'], source='Attyka nad plyta stropowa', assumed=True)

    print(f"Wygenerowano {len(parts)} elementow.")

    # GLB
    Y_UP = np.array([[1,0,0,0],[0,0,1,0],[0,-1,0,0],[0,0,0,1]], dtype=float)
    def export_glb(filename: str, include_roof: bool):
        scene = trimesh.Scene(base_frame='DOM')
        for rec in parts:
            if rec['category'] == 'sufity':
                continue
            if not include_roof and rec['category'] in ['dach', 'strop']:
                continue
            mesh = meshes[rec['name']].copy()
            mesh.unmerge_vertices()
            color = np.array(rec['color']) * 255
            material = trimesh.visual.material.PBRMaterial(
                name=rec['material'],
                baseColorFactor=color.astype(np.uint8),
                metallicFactor=0.0,
                roughnessFactor=0.82,
                alphaMode='BLEND' if rec['material'] == 'szklo' else 'OPAQUE',
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
        if rec['category'] == 'sufity':
            continue
        m = meshes[rec['name']]
        obj += [f"o {rec['name']}", f"g {GROUP_NAMES[rec['category']]}", f"usemtl {rec['material']}"]
        obj += [f'v {a:.7f} {b:.7f} {c:.7f}' for a, b, c in m.vertices]
        obj += ['f ' + ' '.join(str(int(x) + offset + 1) for x in f) for f in m.faces]
        offset += len(m.vertices)
    (ROOT / 'dom_model.obj').write_text('\n'.join(obj) + '\n', encoding='utf-8')
    print("Zapisano: dom_model.obj")

    # scena_modelu.json
    scene_records = []
    for rec in parts:
        m = meshes[rec['name']]
        scene_records.append({**rec, 'positions_m': np.round(m.vertices, 7).tolist(), 'faces': m.faces.tolist()})
    (ROOT / 'scena_modelu.json').write_text(
        json.dumps({'units': 'm', 'up_axis': 'Z', 'parts': scene_records}, ensure_ascii=False, separators=(',', ':')),
        encoding='utf-8'
    )
    print("Zapisano: scena_modelu.json")

    # Aktualizacja podgladu HTML
    import subprocess
    subprocess.run([sys.executable, str(ROOT / 'aktualizuj_podglad.py')], check=True)
    print("Sukces! Zaktualizowano okna oraz podglad_3d.html!")

if __name__ == '__main__':
    main()
