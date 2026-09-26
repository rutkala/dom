"""
Proceduralne generowanie geometrii 3D dla projektu ogrodu Kōyō.
"""
from __future__ import annotations

import math
import numpy as np

DEFAULT_SOURCE = "Projekt zagospodarowania terenu KŌYŌ Landscape"

def make_box(
    name: str,
    category: str,
    color: list[float],
    min_pt: list[float],
    max_pt: list[float],
    rot_angle_rad: float = 0.0,
    rot_center: list[float] | None = None,
    note: str = "",
    source: str = DEFAULT_SOURCE,
) -> dict:
    x0, y0, z0 = min_pt
    x1, y1, z1 = max_pt
    raw_verts = [
        [x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0], # dół 0,1,2,3
        [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1], # góra 4,5,6,7
    ]
    if abs(rot_angle_rad) > 1e-6:
        cx = rot_center[0] if rot_center else (x0 + x1) / 2.0
        cy = rot_center[1] if rot_center else (y0 + y1) / 2.0
        cos_a = math.cos(rot_angle_rad)
        sin_a = math.sin(rot_angle_rad)
        rot_verts = []
        for v in raw_verts:
            dx = v[0] - cx
            dy = v[1] - cy
            rx = cx + dx * cos_a - dy * sin_a
            ry = cy + dx * sin_a + dy * cos_a
            rot_verts.append([round(rx, 4), round(ry, 4), round(v[2], 4)])
        verts = rot_verts
    else:
        verts = [[round(v[0], 4), round(v[1], 4), round(v[2], 4)] for v in raw_verts]

    faces = [
        [0, 2, 1], [0, 3, 2],
        [4, 5, 6], [4, 6, 7],
        [0, 1, 5], [0, 5, 4],
        [1, 2, 6], [1, 6, 5],
        [2, 3, 7], [2, 7, 6],
        [3, 0, 4], [3, 4, 7],
    ]
    return {
        "name": name,
        "category": category,
        "material": category,
        "color": color,
        "positions_m": verts,
        "faces": faces,
        "geometry": "solid",
        "source": source,
        "note": note,
        "default_visible": True,
        "geoportal_real": True,
    }


def make_cylinder(
    name: str,
    category: str,
    color: list[float],
    p_base: list[float],
    p_top: list[float],
    radius: float,
    segments: int = 8,
    note: str = "",
    source: str = DEFAULT_SOURCE,
) -> dict:
    bx, by, bz = p_base
    tx, ty, tz = p_top
    verts = []
    for i in range(segments):
        a = 2.0 * math.pi * i / segments
        verts.append([round(bx + radius * math.cos(a), 4), round(by + radius * math.sin(a), 4), round(bz, 4)])
    for i in range(segments):
        a = 2.0 * math.pi * i / segments
        verts.append([round(tx + radius * math.cos(a), 4), round(ty + radius * math.sin(a), 4), round(tz, 4)])
    c_bot = len(verts)
    verts.append([round(bx, 4), round(by, 4), round(bz, 4)])
    c_top = len(verts)
    verts.append([round(tx, 4), round(ty, 4), round(tz, 4)])

    faces = []
    for i in range(segments):
        i_next = (i + 1) % segments
        faces.append([i, i_next, i + segments])
        faces.append([i_next, i_next + segments, i + segments])
        faces.append([c_bot, i_next, i])
        faces.append([c_top, i + segments, i_next + segments])

    return {
        "name": name,
        "category": category,
        "material": category,
        "color": color,
        "positions_m": verts,
        "faces": faces,
        "geometry": "solid",
        "source": source,
        "note": note,
        "default_visible": True,
        "geoportal_real": True,
    }


def make_cone(
    name: str,
    category: str,
    color: list[float],
    p_base: list[float],
    height: float,
    radius: float,
    segments: int = 8,
    note: str = "",
    source: str = DEFAULT_SOURCE,
) -> dict:
    bx, by, bz = p_base
    tz = bz + height
    verts = []
    for i in range(segments):
        a = 2.0 * math.pi * i / segments
        verts.append([round(bx + radius * math.cos(a), 4), round(by + radius * math.sin(a), 4), round(bz, 4)])
    c_bot = len(verts)
    verts.append([round(bx, 4), round(by, 4), round(bz, 4)])
    apex = len(verts)
    verts.append([round(bx, 4), round(by, 4), round(tz, 4)])

    faces = []
    for i in range(segments):
        i_next = (i + 1) % segments
        faces.append([i, i_next, apex])
        faces.append([c_bot, i_next, i])

    return {
        "name": name,
        "category": category,
        "material": category,
        "color": color,
        "positions_m": verts,
        "faces": faces,
        "geometry": "solid",
        "source": source,
        "note": note,
        "default_visible": True,
        "geoportal_real": True,
    }


def make_sphere(
    name: str,
    category: str,
    color: list[float],
    center: list[float],
    radius: float,
    segments: int = 8,
    rings: int = 5,
    note: str = "",
    source: str = DEFAULT_SOURCE,
) -> dict:
    cx, cy, cz = center
    verts = []
    verts.append([round(cx, 4), round(cy, 4), round(cz - radius, 4)])

    for r in range(1, rings):
        phi = -math.pi / 2.0 + math.pi * r / rings
        cos_phi = math.cos(phi)
        sin_phi = math.sin(phi)
        for s in range(segments):
            theta = 2.0 * math.pi * s / segments
            x = cx + radius * cos_phi * math.cos(theta)
            y = cy + radius * cos_phi * math.sin(theta)
            z = cz + radius * sin_phi
            verts.append([round(x, 4), round(y, 4), round(z, 4)])

    verts.append([round(cx, 4), round(cy, 4), round(cz + radius, 4)])
    north_pole = len(verts) - 1

    faces = []
    for s in range(segments):
        s_next = (s + 1) % segments
        faces.append([0, 1 + s_next, 1 + s])

    for r in range(rings - 2):
        row_curr = 1 + r * segments
        row_next = row_curr + segments
        for s in range(segments):
            s_next = (s + 1) % segments
            faces.append([row_curr + s, row_curr + s_next, row_next + s])
            faces.append([row_curr + s_next, row_next + s_next, row_next + s])

    last_row = 1 + (rings - 2) * segments
    for s in range(segments):
        s_next = (s + 1) % segments
        faces.append([north_pole, last_row + s, last_row + s_next])

    return {
        "name": name,
        "category": category,
        "material": category,
        "color": color,
        "positions_m": verts,
        "faces": faces,
        "geometry": "solid",
        "source": source,
        "note": note,
        "default_visible": True,
        "geoportal_real": True,
    }


def make_quad(
    name: str,
    category: str,
    color: list[float],
    p0: list[float],
    p1: list[float],
    p2: list[float],
    p3: list[float],
    note: str = "",
    source: str = DEFAULT_SOURCE,
) -> dict:
    verts = [
        [round(p[0], 4), round(p[1], 4), round(p[2], 4)] for p in [p0, p1, p2, p3]
    ]
    faces = [[0, 1, 2], [0, 2, 3]]
    return {
        "name": name,
        "category": category,
        "material": category,
        "color": color,
        "positions_m": verts,
        "faces": faces,
        "geometry": "solid",
        "source": source,
        "note": note,
        "default_visible": True,
        "geoportal_real": True,
    }
