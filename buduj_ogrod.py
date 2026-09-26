"""
Generator kompletnego modelu 3D ogrodu na podstawie projektu Kōyō Landscape (A.1, A.2, A.3).
Georeferencja w układzie lokalnym EPSG:2180 dopasowana do modelu domu i działki 4/13.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import numpy as np

from geometria_pomocnicza import (
    make_box,
    make_cylinder,
    make_cone,
    make_sphere,
    make_quad,
)

ROOT = Path(__file__).resolve().parent

# 1. Wczytanie sceny bazowej
scena_file = ROOT / "scena_modelu.json"
scena = json.loads(scena_file.read_text(encoding="utf-8"))

# Usunięcie starych elementów ogrodu przed dodaniem nowych
scena["parts"] = [p for p in scena["parts"] if not p.get("name", "").startswith("OGROD_")]

# 2. Budowa interpolatora rzędnych terenu NMT
nmt_part = None
for p in scena["parts"]:
    if p.get("name") == "GEO_NMT_rzeczywisty":
        nmt_part = p
        break

if not nmt_part:
    raise RuntimeError("Nie znaleziono GEO_NMT_rzeczywisty w scenie")

nmt_pos = np.array(nmt_part["positions_m"])
nmt_xy = nmt_pos[:, :2]
nmt_z = nmt_pos[:, 2]

def get_terrain_z(x: float, y: float) -> float:
    dists = np.hypot(nmt_xy[:, 0] - x, nmt_xy[:, 1] - y)
    k = 4
    idx = np.argpartition(dists, k)[:k]
    d_k = dists[idx]
    w = 1.0 / np.maximum(d_k, 1e-4)
    w /= np.sum(w)
    return float(np.sum(nmt_z[idx] * w))

# 3. Układ współrzędnych ogrodu
p_stairs = np.array([11.156185, -6.667648])
u_len = np.array([0.190234, 0.981718])   # wzdłuż działki ku tyłowi
u_wid = np.array([0.981718, -0.190234])  # w poprzek w prawo (ku granicy płd-wsch)
DEFAULT_SOURCE = "Projekt KŌYŌ Landscape (A.1, A.2, A.3)"

def to_3d(L: float, W: float, z_offset: float = 0.0) -> list[float]:
    """Przelicza współrzędne ogrodu (L, W w metrach) na współrzędne modelu 3D (X, Y, Z)."""
    pt2d = p_stairs + L * u_len + W * u_wid
    z = get_terrain_z(pt2d[0], pt2d[1]) + z_offset
    return [round(float(pt2d[0]), 4), round(float(pt2d[1]), 4), round(float(z), 4)]

def make_garden_box(
    name: str,
    category: str,
    color: list[float],
    L_center: float,
    W_center: float,
    L_len: float,
    W_len: float,
    height: float,
    z_base_offset: float = 0.0,
    note: str = "",
) -> dict:
    center_pt = to_3d(L_center, W_center, z_base_offset)
    cx, cy, cz = center_pt
    half_L = L_len / 2.0
    half_W = W_len / 2.0

    corners_2d = [
        (-half_L, -half_W),
        (half_L, -half_W),
        (half_L, half_W),
        (-half_L, half_W),
    ]

    verts = []
    # Dół (z = cz)
    for dl, dw in corners_2d:
        p = center_pt[:2] + dl * u_len + dw * u_wid
        verts.append([round(float(p[0]), 4), round(float(p[1]), 4), round(float(cz), 4)])
    # Góra (z = cz + height)
    for dl, dw in corners_2d:
        p = center_pt[:2] + dl * u_len + dw * u_wid
        verts.append([round(float(p[0]), 4), round(float(p[1]), 4), round(float(cz + height), 4)])

    faces = [
        [0, 2, 1], [0, 3, 2], # dół
        [4, 5, 6], [4, 6, 7], # góra
        [0, 1, 5], [0, 5, 4], # bok 1
        [1, 2, 6], [1, 6, 5], # bok 2
        [2, 3, 7], [2, 7, 6], # bok 3
        [3, 0, 4], [3, 4, 7], # bok 4
    ]

    return {
        "name": name,
        "category": category,
        "material": category,
        "color": color,
        "positions_m": verts,
        "faces": faces,
        "geometry": "solid",
        "source": DEFAULT_SOURCE,
        "note": note,
        "default_visible": True,
        "geoportal_real": True,
    }

new_parts = []

# ==============================================================================
# A. TARAS I BASEN (L: 25.0 do 35.0 m, W: -4.87 do 2.13 m)
# ==============================================================================
c_gres = [0.78, 0.74, 0.70, 1.0]

# Plaża z gresu ZOYA Sandstone Grey 60x60 wokół basenu (10.0 x 7.0 m)
new_parts.append(make_garden_box(
    "OGROD_TARAS_BASEN_ZACHOD", "ogrod_nawierzchnie", c_gres,
    L_center=25.5, W_center=-1.37, L_len=1.0, W_len=7.0, height=0.08, z_base_offset=0.04,
    note="Plaża basenowa zachodnia: Gres ZOYA 2.0 Sandstone Grey 60×60×2 cm."
))
new_parts.append(make_garden_box(
    "OGROD_TARAS_BASEN_WSCHOD", "ogrod_nawierzchnie", c_gres,
    L_center=34.5, W_center=-1.37, L_len=1.0, W_len=7.0, height=0.08, z_base_offset=0.04,
    note="Plaża basenowa wschodnia: Gres ZOYA 2.0 Sandstone Grey 60×60×2 cm z miejscem na leżaki."
))
new_parts.append(make_garden_box(
    "OGROD_TARAS_BASEN_POLNOC", "ogrod_nawierzchnie", c_gres,
    L_center=30.0, W_center=-4.12, L_len=8.0, W_len=1.5, height=0.08, z_base_offset=0.04,
    note="Plaża basenowa północna: Gres ZOYA 2.0 Sandstone Grey 60×60×2 cm ze strefą wypoczynku."
))
new_parts.append(make_garden_box(
    "OGROD_TARAS_BASEN_POLUDNIE", "ogrod_nawierzchnie", c_gres,
    L_center=30.0, W_center=1.38, L_len=8.0, W_len=1.5, height=0.08, z_base_offset=0.04,
    note="Plaża basenowa południowa: Gres ZOYA 2.0 Sandstone Grey 60×60×2 cm."
))

# Niecka basenu Polystone (8.0 x 4.0 m, głębokość 1.50 m)
c_pool_shell = [0.08, 0.35, 0.65, 1.0]
new_parts.append(make_garden_box(
    "OGROD_BASEN_DNO", "ogrod_woda", c_pool_shell,
    L_center=30.0, W_center=-1.37, L_len=8.0, W_len=4.0, height=0.08, z_base_offset=-1.50,
    note="Dno basenu Polystone niebieskiego 4×8 m."
))
new_parts.append(make_garden_box(
    "OGROD_BASEN_SCIANA_ZACH", "ogrod_woda", c_pool_shell,
    L_center=26.05, W_center=-1.37, L_len=0.10, W_len=4.0, height=1.50, z_base_offset=-1.50,
    note="Ściana zachodnia niecki basenowej Polystone."
))
new_parts.append(make_garden_box(
    "OGROD_BASEN_SCIANA_WSCH", "ogrod_woda", c_pool_shell,
    L_center=33.95, W_center=-1.37, L_len=0.10, W_len=4.0, height=1.50, z_base_offset=-1.50,
    note="Ściana wschodnia niecki basenowej Polystone."
))
new_parts.append(make_garden_box(
    "OGROD_BASEN_SCIANA_POLN", "ogrod_woda", c_pool_shell,
    L_center=30.0, W_center=-3.32, L_len=8.0, W_len=0.10, height=1.50, z_base_offset=-1.50,
    note="Ściana północna niecki basenowej Polystone."
))
new_parts.append(make_garden_box(
    "OGROD_BASEN_SCIANA_POLD", "ogrod_woda", c_pool_shell,
    L_center=30.0, W_center=0.58, L_len=8.0, W_len=0.10, height=1.50, z_base_offset=-1.50,
    note="Ściana południowa niecki basenowej Polystone."
))

# Lustro wody w basenie (krystaliczny błękit, lekko transparentny)
c_water = [0.12, 0.60, 0.94, 0.82]
new_parts.append(make_garden_box(
    "OGROD_BASEN_WODA", "ogrod_woda", c_water,
    L_center=30.0, W_center=-1.37, L_len=7.90, W_len=3.90, height=0.04, z_base_offset=-0.12,
    note="Lustro wody w basenie kąpielowym (wymiary 4×8 m, rynna przelewowa)."
))

# Obrzeże basenu (biały kompozyt)
c_rim = [0.94, 0.94, 0.96, 1.0]
new_parts.append(make_garden_box(
    "OGROD_BASEN_OBRZEZE_ZACH", "ogrod_nawierzchnie", c_rim,
    L_center=25.95, W_center=-1.37, L_len=0.18, W_len=4.20, height=0.09, z_base_offset=0.04,
    note="Obrzeże przelewowe basenu."
))
new_parts.append(make_garden_box(
    "OGROD_BASEN_OBRZEZE_WSCH", "ogrod_nawierzchnie", c_rim,
    L_center=34.05, W_center=-1.37, L_len=0.18, W_len=4.20, height=0.09, z_base_offset=0.04,
    note="Obrzeże przelewowe basenu."
))
new_parts.append(make_garden_box(
    "OGROD_BASEN_OBRZEZE_POLN", "ogrod_nawierzchnie", c_rim,
    L_center=30.0, W_center=-3.42, L_len=8.0, W_len=0.18, height=0.09, z_base_offset=0.04,
    note="Obrzeże przelewowe basenu."
))
new_parts.append(make_garden_box(
    "OGROD_BASEN_OBRZEZE_POLD", "ogrod_nawierzchnie", c_rim,
    L_center=30.0, W_center=0.68, L_len=8.0, W_len=0.18, height=0.09, z_base_offset=0.04,
    note="Obrzeże przelewowe basenu."
))

# Meble basenowe: 2 nowoczesne leżaki na plaży tarasowej
c_lounger_frame = [0.24, 0.26, 0.28, 1.0]
c_lounger_pad = [0.92, 0.92, 0.90, 1.0]
for idx, w_pos in enumerate([1.2, -0.1]):
    new_parts.append(make_garden_box(
        f"OGROD_LEZAK_RAMA_{idx+1}", "ogrod_architektura", c_lounger_frame,
        L_center=34.5, W_center=w_pos, L_len=1.95, W_len=0.70, height=0.25, z_base_offset=0.10,
        note=f"Leżak basenowy {idx+1} z ramą antracytową."
    ))
    new_parts.append(make_garden_box(
        f"OGROD_LEZAK_MATERAC_{idx+1}", "ogrod_architektura", c_lounger_pad,
        L_center=34.5, W_center=w_pos, L_len=1.90, W_len=0.65, height=0.08, z_base_offset=0.35,
        note=f"Materac leżaka basenowego {idx+1} (tkanina hydrofobowa jasnoszara)."
    ))

# Stół ogrodowy i 4 krzesła na północnej części plaży basenowej
c_table = [0.35, 0.28, 0.22, 1.0]
new_parts.append(make_garden_box(
    "OGROD_STOL_TARAS", "ogrod_architektura", c_table,
    L_center=30.0, W_center=-4.1, L_len=1.80, W_len=0.90, height=0.74, z_base_offset=0.10,
    note="Stół ogrodowy obiadowy na tarasie basenowym."
))
for idx, (dl, dw) in enumerate([(-0.6, -0.65), (0.6, -0.65), (-0.6, 0.65), (0.6, 0.65)]):
    new_parts.append(make_garden_box(
        f"OGROD_KRZESLO_{idx+1}", "ogrod_architektura", c_lounger_frame,
        L_center=30.0 + dl, W_center=-4.1 + dw, L_len=0.45, W_len=0.45, height=0.45, z_base_offset=0.10,
        note=f"Krzesło ogrodowe {idx+1}."
    ))

# ==============================================================================
# B. PŁYTY GROSSETO I NAWIERZCHNIE UTWARDZONE (`ogrod_nawierzchnie`)
# ==============================================================================
c_grosseto = [0.74, 0.76, 0.75, 1.0]
c_frappe = [0.66, 0.62, 0.58, 1.0]
c_dakota = [0.26, 0.28, 0.30, 1.0]

# Pas z kostki Kalifornia mix Frappe wzdłuż schodów tarasu (szerokość 1.84m)
new_parts.append(make_garden_box(
    "OGROD_KOSTKA_FRAPPE_OPASKA", "ogrod_nawierzchnie", c_frappe,
    L_center=0.92, W_center=0.0, L_len=1.84, W_len=7.0, height=0.06, z_base_offset=0.01,
    note="Kostka Kalifornia producent Kost-Bet, kolor mix A12 Frappe (pow. 78 m²)."
))

# 79 Płyt Grosseto 90x60 cm
for col, dw in enumerate([-0.48, 0.48]):
    for row in range(7):
        l_pos = 2.3 + row * 0.95
        new_parts.append(make_garden_box(
            f"OGROD_GROSSETO_FRONT_{col}_{row}", "ogrod_nawierzchnie", c_grosseto,
            L_center=l_pos, W_center=dw, L_len=0.90, W_len=0.60, height=0.06, z_base_offset=0.02,
            note="Płyta Grosseto 90×60 cm producent Kost-Bet, standard szary — ścieżka w trawniku."
        ))

for col, dw in enumerate([-0.48, 0.48]):
    for row in range(2):
        l_pos = 23.2 + row * 0.95
        new_parts.append(make_garden_box(
            f"OGROD_GROSSETO_PRZED_BASENEM_{col}_{row}", "ogrod_nawierzchnie", c_grosseto,
            L_center=l_pos, W_center=dw, L_len=0.90, W_len=0.60, height=0.06, z_base_offset=0.02,
            note="Płyta Grosseto 90×60 cm — podejście do plaży basenowej."
        ))

for col, dw in enumerate([-0.48, 0.48]):
    for row in range(2):
        l_pos = 35.8 + row * 0.95
        new_parts.append(make_garden_box(
            f"OGROD_GROSSETO_ZA_BASENEM_{col}_{row}", "ogrod_nawierzchnie", c_grosseto,
            L_center=l_pos, W_center=dw, L_len=0.90, W_len=0.60, height=0.06, z_base_offset=0.02,
            note="Płyta Grosseto 90×60 cm — zejście z plaży basenowej do ogrodu."
        ))

for col, dw in enumerate([-3.98, -3.02]):
    for row in range(2):
        l_pos = 38.5 + row * 0.95
        new_parts.append(make_garden_box(
            f"OGROD_GROSSETO_SZKLARNIA_{col}_{row}", "ogrod_nawierzchnie", c_grosseto,
            L_center=l_pos, W_center=dw, L_len=0.90, W_len=0.60, height=0.06, z_base_offset=0.02,
            note="Płyta Grosseto 90×60 cm — dojście do szklarni."
        ))

for col, dw in enumerate([1.70, 2.65]):
    for row in range(4):
        l_pos = 52.5 + row * 0.95
        new_parts.append(make_garden_box(
            f"OGROD_GROSSETO_WARZYWA_{col}_{row}", "ogrod_nawierzchnie", c_grosseto,
            L_center=l_pos, W_center=dw, L_len=0.90, W_len=0.60, height=0.06, z_base_offset=0.02,
            note="Płyta Grosseto 90×60 cm — ścieżka przy strefie warzywnej."
        ))

# Kostka Dakota pod domek narzędziowy (4.14 x 3.43 m, L: 42.0 do 46.14 m, W: 1.5 do 4.93 m)
new_parts.append(make_garden_box(
    "OGROD_KOSTKA_DAKOTA_DOMEK", "ogrod_nawierzchnie", c_dakota,
    L_center=44.07, W_center=3.21, L_len=4.14, W_len=3.43, height=0.06, z_base_offset=0.02,
    note="Kostka Dakota producent Kost-Bet, kolor standard grafit (pow. 29,8 m²)."
))

# Nawierzchnia bezpieczna pod plac zabaw (5.64 x 4.00 m, zielone moduły 50x50)
c_safe = [0.28, 0.62, 0.30, 1.0]
new_parts.append(make_garden_box(
    "OGROD_NAWIERZCHNIA_BEZPIECZNA", "ogrod_nawierzchnie", c_safe,
    L_center=20.82, W_center=3.0, L_len=5.64, W_len=4.0, height=0.05, z_base_offset=0.01,
    note="Nawierzchnia bezpieczna moduły 50×50 cm, kolor zielony, 76 szt. (pow. 19 m²)."
))

# Grys ozdobny Biała Marianna w pasach bocznych i meandrze
c_grys = [0.91, 0.90, 0.88, 1.0]
new_parts.append(make_garden_box(
    "OGROD_GRYS_PAS_POLD", "ogrod_nawierzchnie", c_grys,
    L_center=27.0, W_center=5.5, L_len=54.0, W_len=1.4, height=0.04, z_base_offset=0.01,
    note="Grys jasny np. Biała Marianna wzdłuż południowej granicy (pow. 364,7 m²)."
))
new_parts.append(make_garden_box(
    "OGROD_GRYS_PAS_POLN", "ogrod_nawierzchnie", c_grys,
    L_center=27.0, W_center=-8.1, L_len=54.0, W_len=1.4, height=0.04, z_base_offset=0.01,
    note="Grys jasny np. Biała Marianna wzdłuż północnej granicy."
))
new_parts.append(make_garden_box(
    "OGROD_GRYS_LESNY_MEANDER", "ogrod_nawierzchnie", c_grys,
    L_center=86.2, W_center=-2.5, L_len=15.6, W_len=11.0, height=0.04, z_base_offset=0.01,
    note="Strefa leśna R1 z białym grysem Marianna i meandrującą ścieżką kwarcytową."
))

# 13 Płyt kwarcytowych na meandrującej ścieżce leśnej
c_kwarcyt = [0.64, 0.62, 0.58, 1.0]
meander_pts = [
    (79.5, -6.5), (80.8, -5.2), (82.0, -3.8), (83.2, -2.5),
    (84.5, -1.2), (85.8, -0.5), (87.0, -1.2), (88.2, -2.8),
    (89.5, -4.5), (90.8, -5.5), (92.0, -4.2), (93.0, -2.5), (93.8, -0.8)
]
for idx, (l_pt, w_pt) in enumerate(meander_pts):
    new_parts.append(make_garden_box(
        f"OGROD_KWARCYT_{idx+1:02d}", "ogrod_nawierzchnie", c_kwarcyt,
        L_center=l_pt, W_center=w_pt, L_len=0.75, W_len=0.55, height=0.05, z_base_offset=0.03,
        note=f"Ścieżka: Płyta Kwarcytowa Trawnikowa {idx+1}/13 (pow. 4 m²)."
    ))

# ==============================================================================
# C. STREFA GOSPODARCZO-UPRAWNA (`ogrod_architektura`)
# ==============================================================================
c_wood_shed = [0.58, 0.42, 0.28, 1.0]
c_shed_roof = [0.22, 0.24, 0.26, 1.0]

# Domek narzędziowy (2.50 x 3.00 m, wysokość 2.6 m, na L=44.0m, W=3.2m)
new_parts.append(make_garden_box(
    "OGROD_DOMEK_SCIANY", "ogrod_architektura", c_wood_shed,
    L_center=44.0, W_center=3.2, L_len=2.50, W_len=3.00, height=2.40, z_base_offset=0.08,
    note="Domek narzędziowy: wymiary 2,5×3,0 m, pionowe lamele drewniane."
))
new_parts.append(make_garden_box(
    "OGROD_DOMEK_DACH", "ogrod_architektura", c_shed_roof,
    L_center=44.0, W_center=3.2, L_len=2.70, W_len=3.20, height=0.15, z_base_offset=2.48,
    note="Dach jednospadowy domku narzędziowego w kolorze antracytowym."
))
new_parts.append(make_garden_box(
    "OGROD_DOMEK_DRZWI", "ogrod_architektura", [0.18, 0.20, 0.22, 1.0],
    L_center=42.74, W_center=3.2, L_len=0.06, W_len=0.90, height=2.00, z_base_offset=0.08,
    note="Drzwi wejściowe do domku narzędziowego."
))

# Szklarnia ogrodowa (1.80 x 3.00 m, wysokość 2.3 m na L=45.0m, W=-5.6m)
c_glass = [0.86, 0.94, 0.96, 0.45]
c_glass_frame = [0.18, 0.20, 0.22, 1.0]
new_parts.append(make_garden_box(
    "OGROD_SZKLARNIA_SZKLO", "ogrod_architektura", c_glass,
    L_center=45.0, W_center=-5.6, L_len=1.80, W_len=3.00, height=2.10, z_base_offset=0.04,
    note="Szklarnia ogrodowa: 1,8×3,0 m, bezpieczne szkło ogrodnicze."
))
new_parts.append(make_garden_box(
    "OGROD_SZKLARNIA_RAMA_COKOL", "ogrod_architektura", c_glass_frame,
    L_center=45.0, W_center=-5.6, L_len=1.84, W_len=3.04, height=0.10, z_base_offset=0.04,
    note="Aluminiowa podstawa cokołowa szklarni w kolorze antracytowym."
))
new_parts.append(make_garden_box(
    "OGROD_SZKLARNIA_KALENICA", "ogrod_architektura", c_glass_frame,
    L_center=45.0, W_center=-5.6, L_len=1.84, W_len=0.08, height=0.08, z_base_offset=2.14,
    note="Kalenica konstrukcyjna szklarni ogrodowej."
))

# 4 Skrzynie na warzywa (1.80 x 0.90 m, wysokość 0.60 m)
c_box_wood = [0.62, 0.46, 0.32, 1.0]
c_soil = [0.20, 0.16, 0.12, 1.0]
c_crops = [0.32, 0.68, 0.22, 1.0]

for idx, (dl, dw) in enumerate([
    (48.2, 2.3), (50.7, 2.3),
    (48.2, 3.9), (50.7, 3.9)
]):
    new_parts.append(make_garden_box(
        f"OGROD_SKRZYNIA_RAMA_{idx+1}", "ogrod_architektura", c_box_wood,
        L_center=dl, W_center=dw, L_len=1.80, W_len=0.90, height=0.60, z_base_offset=0.02,
        note=f"Skrzynia na warzywa {idx+1}/4: drewno impregnowane 180×90 cm, wys. 60 cm."
    ))
    new_parts.append(make_garden_box(
        f"OGROD_SKRZYNIA_ZIEMIA_{idx+1}", "ogrod_architektura", c_soil,
        L_center=dl, W_center=dw, L_len=1.60, W_len=0.70, height=0.10, z_base_offset=0.50,
        note=f"Podłoże próchnicze w skrzyni warzywnej {idx+1}."
    ))
    new_parts.append(make_garden_box(
        f"OGROD_SKRZYNIA_WARZYWA_{idx+1}", "ogrod_architektura", c_crops,
        L_center=dl, W_center=dw, L_len=1.50, W_len=0.60, height=0.20, z_base_offset=0.60,
        note=f"Uprawy ziół i warzyw w skrzyni {idx+1}."
    ))

# Plac zabaw Modulaki na nawierzchni bezpiecznej
c_play_wood = [0.68, 0.50, 0.32, 1.0]
c_slide = [0.96, 0.78, 0.12, 1.0]
new_parts.append(make_garden_box(
    "OGROD_PLAC_WIEZA", "ogrod_architektura", c_play_wood,
    L_center=20.0, W_center=2.6, L_len=1.40, W_len=1.40, height=2.80, z_base_offset=0.06,
    note="Wieża ze zjeżdżalnią — Plac zabaw producent: Modulaki."
))
new_parts.append(make_garden_box(
    "OGROD_PLAC_ZJEZDZALNIA", "ogrod_architektura", c_slide,
    L_center=21.8, W_center=2.6, L_len=2.20, W_len=0.55, height=0.80, z_base_offset=0.06,
    note="Zjeżdżalnia bezpieczna dla dzieci."
))
new_parts.append(make_garden_box(
    "OGROD_PLAC_HUSTAWKA", "ogrod_architektura", c_play_wood,
    L_center=20.0, W_center=4.2, L_len=0.15, W_len=2.20, height=2.20, z_base_offset=0.06,
    note="Belka podwójnej huśtawki na placu zabaw."
))

# Trampolina wpuszczana w ziemię (średnica 3.6m, na L=14.0m, W=-5.5m)
c_tramp_mat = [0.15, 0.16, 0.18, 1.0]
c_tramp_rim = [0.22, 0.55, 0.28, 1.0]
pt_tramp = to_3d(14.0, -5.5, 0.05)
new_parts.append(make_cylinder(
    "OGROD_TRAMPOLINA_MATA", "ogrod_architektura", c_tramp_mat,
    p_base=pt_tramp, p_top=[pt_tramp[0], pt_tramp[1], pt_tramp[2] + 0.04], radius=1.70, segments=16,
    note="Mata elastyczna trampoliny ogrodowej wpuszczanej w grunt."
))
new_parts.append(make_cylinder(
    "OGROD_TRAMPOLINA_KRAWEDZ", "ogrod_architektura", c_tramp_rim,
    p_base=[pt_tramp[0], pt_tramp[1], pt_tramp[2] + 0.04],
    p_top=[pt_tramp[0], pt_tramp[1], pt_tramp[2] + 0.10], radius=1.85, segments=16,
    note="Kołnierz ochronny trampoliny ogrodowej."
))

# ==============================================================================
# D. BOISKO WIELOFUNKCYJNE (`ogrod_nawierzchnie` & `ogrod_architektura`)
# ==============================================================================
c_pitch_turf = [0.40, 0.64, 0.24, 1.0]
new_parts.append(make_garden_box(
    "OGROD_BOISKO_MURAWA", "ogrod_nawierzchnie", c_pitch_turf,
    L_center=66.18, W_center=-2.25, L_len=24.36, W_len=14.50, height=0.04, z_base_offset=0.01,
    note="Boisko wielofunkcyjne: nawierzchnia trawiasta sportowa 24,36 × 18,00 m."
))

c_line = [0.96, 0.96, 0.96, 1.0]
new_parts.append(make_garden_box(
    "OGROD_BOISKO_LINIA_SRODKOWA", "ogrod_nawierzchnie", c_line,
    L_center=66.18, W_center=-2.25, L_len=0.10, W_len=14.0, height=0.05, z_base_offset=0.02,
    note="Linia środkowa boiska wielofunkcyjnego."
))

# Siatka do siatkówki na środku boiska (L=66.18m)
c_pole = [0.85, 0.85, 0.88, 1.0]
c_net = [0.95, 0.95, 0.95, 0.75]
p_pole1 = to_3d(66.18, -6.5, 0.0)
new_parts.append(make_cylinder(
    "OGROD_SIATKA_SLUPEK_1", "ogrod_architektura", c_pole,
    p_base=p_pole1, p_top=[p_pole1[0], p_pole1[1], p_pole1[2] + 2.50], radius=0.05, segments=8,
    note="Słupek siatki do siatkówki (stal ocynkowana)."
))
p_pole2 = to_3d(66.18, 2.0, 0.0)
new_parts.append(make_cylinder(
    "OGROD_SIATKA_SLUPEK_2", "ogrod_architektura", c_pole,
    p_base=p_pole2, p_top=[p_pole2[0], p_pole2[1], p_pole2[2] + 2.50], radius=0.05, segments=8,
    note="Słupek siatki do siatkówki (stal ocynkowana)."
))
new_parts.append(make_garden_box(
    "OGROD_SIATKA_POWIERZCHNIA", "ogrod_architektura", c_net,
    L_center=66.18, W_center=-2.25, L_len=0.02, W_len=8.5, height=1.00, z_base_offset=1.45,
    note="Siatka do siatkówki zawieszona na wysokości 2,43 m."
))

# Bramka do piłki nożnej na wschodnim końcu boiska (L=78.0m, W=-2.25m, 3.0 x 2.0 m)
c_goal = [0.95, 0.95, 0.95, 1.0]
p_g1 = to_3d(78.0, -3.75, 0.0)
new_parts.append(make_cylinder(
    "OGROD_BRAMKA_SLUPEK_L", "ogrod_architektura", c_goal,
    p_base=p_g1, p_top=[p_g1[0], p_g1[1], p_g1[2] + 2.00], radius=0.05, segments=8,
    note="Słupek lewy bramki do piłki nożnej (3×2 m)."
))
p_g2 = to_3d(78.0, -0.75, 0.0)
new_parts.append(make_cylinder(
    "OGROD_BRAMKA_SLUPEK_P", "ogrod_architektura", c_goal,
    p_base=p_g2, p_top=[p_g2[0], p_g2[1], p_g2[2] + 2.00], radius=0.05, segments=8,
    note="Słupek prawy bramki do piłki nożnej (3×2 m)."
))
new_parts.append(make_garden_box(
    "OGROD_BRAMKA_POPRZECZKA", "ogrod_architektura", c_goal,
    L_center=78.0, W_center=-2.25, L_len=0.10, W_len=3.00, height=0.10, z_base_offset=1.95,
    note="Poprzeczka bramki piłkarskiej."
))
new_parts.append(make_garden_box(
    "OGROD_BRAMKA_SIATKA", "ogrod_architektura", c_net,
    L_center=78.5, W_center=-2.25, L_len=1.00, W_len=3.00, height=2.00, z_base_offset=0.0,
    note="Siatka bramki piłkarskiej."
))

# Kosz do koszykówki nad bramką (wysokość 3.05 m, tablica 1.80 x 1.05 m)
p_bball = to_3d(78.7, -2.25, 0.0)
new_parts.append(make_cylinder(
    "OGROD_KOSZ_SLUP", "ogrod_architektura", [0.4, 0.4, 0.45, 1.0],
    p_base=p_bball, p_top=[p_bball[0], p_bball[1], p_bball[2] + 3.80], radius=0.08, segments=8,
    note="Słup stalowy kosza do koszykówki."
))
new_parts.append(make_garden_box(
    "OGROD_KOSZ_TABLICA", "ogrod_architektura", [0.92, 0.94, 0.96, 0.9],
    L_center=78.3, W_center=-2.25, L_len=0.05, W_len=1.80, height=1.05, z_base_offset=2.60,
    note="Tablica do koszykówki z plexiglasu 180×105 cm."
))
new_parts.append(make_garden_box(
    "OGROD_KOSZ_OBRECZ", "ogrod_architektura", [0.95, 0.45, 0.05, 1.0],
    L_center=78.05, W_center=-2.25, L_len=0.45, W_len=0.45, height=0.05, z_base_offset=3.05,
    note="Obręcz kosza z siatką na przepisowej wysokości 3,05 m."
))

# ==============================================================================
# E. NASADZENIA ROŚLINNE 3D (25 GATUNKÓW Z ARKUSZA A.3)
# ==============================================================================
c_bark = [0.32, 0.22, 0.14, 1.0]

def add_tree(
    name: str,
    L_pos: float,
    W_pos: float,
    trunk_h: float,
    trunk_r: float,
    crown_r: float,
    crown_color: list[float],
    shape: str = "sphere",
    crown_h: float = 3.0,
    note: str = "",
):
    pt_base = to_3d(L_pos, W_pos, 0.0)
    pt_top = [pt_base[0], pt_base[1], pt_base[2] + trunk_h]
    new_parts.append(make_cylinder(
        f"{name}_PIEN", "ogrod_rosliny", c_bark,
        p_base=pt_base, p_top=pt_top, radius=trunk_r, segments=8,
        note=f"Pień drzewa: {note}"
    ))
    if shape == "cone":
        new_parts.append(make_cone(
            f"{name}_KORONA", "ogrod_rosliny", crown_color,
            p_base=[pt_base[0], pt_base[1], pt_base[2] + trunk_h * 0.4],
            height=crown_h, radius=crown_r, segments=10,
            note=note
        ))
    elif shape == "bonsai":
        for c_idx, (dl, dw, dz, cr) in enumerate([
            (0.0, 0.0, 0.0, crown_r),
            (0.4, -0.3, 0.4, crown_r * 0.75),
            (-0.3, 0.4, 0.7, crown_r * 0.65),
            (0.2, 0.2, 1.1, crown_r * 0.5)
        ]):
            new_parts.append(make_sphere(
                f"{name}_CHMURA_{c_idx+1}", "ogrod_rosliny", crown_color,
                center=[pt_top[0] + dl, pt_top[1] + dw, pt_top[2] + dz],
                radius=cr, segments=8, rings=5,
                note=note
            ))
    else:
        new_parts.append(make_sphere(
            f"{name}_KORONA", "ogrod_rosliny", crown_color,
            center=[pt_top[0], pt_top[1], pt_top[2] + crown_r * 0.7],
            radius=crown_r, segments=8, rings=5,
            note=note
        ))

# 1. Klon palmowy 'Fireglow' (Acer palmatum)
add_tree(
    "OGROD_KLON_PALMOWY", L_pos=1.5, W_pos=-2.8, trunk_h=1.2, trunk_r=0.08, crown_r=1.5,
    crown_color=[0.74, 0.14, 0.18, 1.0],
    note="Poz. 4: Acer palmatum 'Fireglow' / 'Atropurpurea' — klon palmowy bordowy przy tarasie."
)

# 2. Magnolia Alexandrina
add_tree(
    "OGROD_MAGNOLIA", L_pos=14.0, W_pos=-2.5, trunk_h=1.4, trunk_r=0.12, crown_r=2.1,
    crown_color=[0.42, 0.58, 0.34, 1.0],
    note="Poz. 2: Magnolia Alexandrina — magnolia soulangeana, elegancki kwitnący soliter."
)

# 3. Tulipanowiec amerykański 'Edward Gursztyn'
add_tree(
    "OGROD_TULIPANOWIEC", L_pos=12.0, W_pos=-5.8, trunk_h=1.8, trunk_r=0.14, crown_r=2.4,
    crown_color=[0.35, 0.60, 0.24, 1.0],
    note="Poz. 1: Liriodendron tulipifera 'Edward Gursztyn' — tulipanowiec amerykański."
)

# 4. Sosna drobnokwiatowa 'Schon's Bonsai'
add_tree(
    "OGROD_SOSNA_BONSAI", L_pos=31.0, W_pos=-5.5, trunk_h=1.1, trunk_r=0.10, crown_r=1.1,
    crown_color=[0.18, 0.36, 0.18, 1.0], shape="bonsai",
    note="Poz. 7: Pinus parviflora 'Schon's Bonsai' — sosna drobnokwiatowa formowana niwaki."
)

# 5. Świdośliwa Lamarcka
add_tree(
    "OGROD_SWIDOSLIWA", L_pos=41.5, W_pos=-5.0, trunk_h=1.5, trunk_r=0.10, crown_r=1.8,
    crown_color=[0.38, 0.55, 0.25, 1.0],
    note="Poz. 3: Amelanchier lamarckii — świdośliwa Lamarcka przy strefie gospodarczej."
)

# 6. Sosny czarne 'Green Tower'
c_conifer_dark = [0.16, 0.32, 0.16, 1.0]
for idx, (l_p, w_p) in enumerate([(9.0, -6.5), (16.0, -6.5), (42.0, 1.5), (44.5, 1.5)]):
    add_tree(
        f"OGROD_SOSNA_CZARNA_{idx+1}", L_pos=l_p, W_pos=w_p, trunk_h=0.4, trunk_r=0.08,
        crown_r=0.7, crown_color=c_conifer_dark, shape="cone", crown_h=4.2,
        note="Poz. 8: Pinus nigra 'Green Tower' — sosna czarna kolumnowa."
    )

# 7. Sosny leśne w strefie tylnej
c_pine = [0.20, 0.38, 0.18, 1.0]
forest_trees = [
    (80.0, -8.0), (82.5, -6.5), (85.0, -8.2), (88.0, -7.0), (91.0, -8.5), (93.5, -7.0),
    (80.5, 3.5), (83.5, 2.5), (86.5, 3.8), (89.5, 2.8), (92.5, 3.5), (94.0, 1.0)
]
for idx, (l_p, w_p) in enumerate(forest_trees):
    add_tree(
        f"OGROD_DRZEWO_LESNE_{idx+1}", L_pos=l_p, W_pos=w_p, trunk_h=2.0, trunk_r=0.14,
        crown_r=2.2, crown_color=c_pine,
        note=f"Strefa leśna R1: drzewo {idx+1}/12 w meandrze krajobrazowym."
    )

# 8. Żywopłot z Żywotnika 'Smaragd'
c_hedge = [0.18, 0.44, 0.18, 1.0]
for step, l_p in enumerate(np.arange(2.0, 78.0, 0.85)):
    w_fence = 6.35 - (l_p / 90.0) * 1.91 - 0.40
    pt = to_3d(l_p, w_fence, 0.0)
    new_parts.append(make_cone(
        f"OGROD_SMARAGD_POLD_{step+1}", "ogrod_rosliny", c_hedge,
        p_base=pt, height=2.20, radius=0.38, segments=7,
        note="Poz. 5/6: Thuja occidentalis 'Smaragd' — żywopłot osłonowy granicy południowej."
    ))

for step, l_p in enumerate(np.arange(2.0, 78.0, 0.85)):
    w_fence = -8.47 - (l_p / 90.0) * 1.31 + 0.40
    pt = to_3d(l_p, w_fence, 0.0)
    new_parts.append(make_cone(
        f"OGROD_SMARAGD_POLN_{step+1}", "ogrod_rosliny", c_hedge,
        p_base=pt, height=2.20, radius=0.38, segments=7,
        note="Poz. 5/6: Thuja occidentalis 'Smaragd' — żywopłot osłonowy granicy północnej."
    ))

# 9. Formowane kule: Żywotnik 'Danica' i Cis pospolity (Taxus baccata)
c_topiary = [0.22, 0.48, 0.20, 1.0]
topiary_locs = [
    (1.0, 1.5), (3.0, 1.5), (5.0, 1.5), (7.0, 1.5),
    (24.5, -4.5), (24.5, 1.5), (35.5, -4.5), (35.5, 1.5),
    (38.0, 2.5), (40.0, 2.5), (53.0, -4.5), (53.0, 0.5)
]
for idx, (l_p, w_p) in enumerate(topiary_locs):
    pt = to_3d(l_p, w_p, 0.35)
    new_parts.append(make_sphere(
        f"OGROD_KULA_TOPIARY_{idx+1}", "ogrod_rosliny", c_topiary,
        center=pt, radius=0.35, segments=8, rings=5,
        note="Poz. 9/10: Thuja occidentalis 'Danica' / Cis w formie kuli (Taxus sp.)."
    ))

# 10. Hortensje kwitnące 'Strong Annabelle' / 'Skyfall'
c_hydrangea_white = [0.95, 0.95, 0.90, 1.0]
c_hydrangea_leaf = [0.28, 0.56, 0.24, 1.0]
hydrangea_locs = [
    (25.0, -3.8), (25.0, -2.5), (25.0, -1.2), (25.0, 0.1),
    (35.2, -3.8), (35.2, -2.5), (35.2, -1.2), (35.2, 0.1),
    (2.0, -3.5), (4.0, -3.5), (6.0, -3.5)
]
for idx, (l_p, w_p) in enumerate(hydrangea_locs):
    pt = to_3d(l_p, w_p, 0.30)
    new_parts.append(make_sphere(
        f"OGROD_HORTENSJA_LISCIE_{idx+1}", "ogrod_rosliny", c_hydrangea_leaf,
        center=pt, radius=0.45, segments=8, rings=4,
        note="Poz. 11/12: Hydrangea arborescens 'Strong Anabelle' / 'Skyfall' — liście krzewu."
    ))
    new_parts.append(make_sphere(
        f"OGROD_HORTENSJA_KWIAT_{idx+1}", "ogrod_rosliny", c_hydrangea_white,
        center=[pt[0], pt[1], pt[2] + 0.35], radius=0.32, segments=8, rings=4,
        note="Poz. 11/12: Hydrangea 'Strong Anabelle' — kremowo-białe kwiatostany kuliste."
    ))

# 11. Trawy ozdobne
c_grass_plume = [0.76, 0.70, 0.42, 1.0]
grass_locs = [
    (10.0, 0.8), (12.0, 0.8), (14.0, 0.8), (16.0, 0.8),
    (22.0, -3.5), (22.0, -2.0), (37.0, -3.5), (37.0, -2.0),
    (48.0, 0.5), (50.0, 0.5), (52.0, 0.5)
]
for idx, (l_p, w_p) in enumerate(grass_locs):
    pt = to_3d(l_p, w_p, 0.0)
    new_parts.append(make_cone(
        f"OGROD_TRAWA_PLUME_{idx+1}", "ogrod_rosliny", c_grass_plume,
        p_base=pt, height=1.35, radius=0.40, segments=7,
        note="Poz. 13/14/16: Trawy ozdobne (Calamagrostis 'Karl Foerster' / Rozplenica 'Hameln' / Stipa 'Pony Tails')."
    ))

# 12. Lawenda wąskolistna 'Hidcote'
c_lavender = [0.46, 0.36, 0.66, 1.0]
for idx in range(8):
    l_p = 1.0 + idx * 0.8
    pt = to_3d(l_p, -1.8, 0.18)
    new_parts.append(make_sphere(
        f"OGROD_LAWENDA_{idx+1}", "ogrod_rosliny", c_lavender,
        center=pt, radius=0.22, segments=7, rings=4,
        note="Poz. 19: Lavandula angustifolia 'Hidcote' — lawenda wąskolistna o fioletowych kwiatach."
    ))

# ==============================================================================
# F. OŚWIETLENIE OGRODOWE 3D (`ogrod_oswietlenie`)
# ==============================================================================
c_pirron_post = [0.20, 0.22, 0.24, 1.0]
c_pirron_glow = [1.00, 0.94, 0.78, 1.0]

# 15 Lamp cokołowych LED Pirron
pirron_locs = [
    (2.0, 1.1), (5.5, 1.1), (9.0, 1.1), (13.0, 1.1), (17.0, 1.1),
    (22.5, -4.5), (24.5, 1.8), (35.0, -4.5), (35.0, 1.8),
    (41.0, 1.2), (46.5, 1.2), (52.0, 1.2),
    (54.0, -7.0), (66.0, -7.0), (78.0, -7.0)
]
for idx, (l_p, w_p) in enumerate(pirron_locs):
    pt = to_3d(l_p, w_p, 0.0)
    new_parts.append(make_cylinder(
        f"OGROD_LAMPA_PIRRON_SLUPEK_{idx+1}", "ogrod_oswietlenie", c_pirron_post,
        p_base=pt, p_top=[pt[0], pt[1], pt[2] + 0.60], radius=0.06, segments=6,
        note=f"Lucande lampa cokołowa LED Pirron {idx+1}/15 (słupek antracytowy wys. 60 cm)."
    ))
    new_parts.append(make_sphere(
        f"OGROD_LAMPA_PIRRON_LED_{idx+1}", "ogrod_oswietlenie", c_pirron_glow,
        center=[pt[0], pt[1], pt[2] + 0.58], radius=0.05, segments=6, rings=4,
        note=f"Ciepłe źródło światła LED lampy Pirron {idx+1}."
    ))

# 6 Reflektorów gruntowych podświetlających solitery
for idx, (l_p, w_p) in enumerate([(1.2, -2.5), (13.5, -2.0), (30.5, -5.0), (11.5, -5.5), (81.0, -6.0), (84.0, 2.0)]):
    pt = to_3d(l_p, w_p, 0.0)
    new_parts.append(make_cylinder(
        f"OGROD_REFLEKTOR_PODSTAWA_{idx+1}", "ogrod_oswietlenie", [0.15, 0.15, 0.18, 1.0],
        p_base=pt, p_top=[pt[0], pt[1], pt[2] + 0.12], radius=0.09, segments=6,
        note=f"Reflektor podświetlający rośliny {idx+1}/6 (obudowa wodoszczelna IP67)."
    ))
    new_parts.append(make_sphere(
        f"OGROD_REFLEKTOR_SOCZEWKA_{idx+1}", "ogrod_oswietlenie", [1.00, 0.96, 0.85, 1.0],
        center=[pt[0], pt[1], pt[2] + 0.14], radius=0.08, segments=6, rings=4,
        note=f"Soczewka reflektora podświetlającego drzewo/soliter {idx+1}."
    ))

# Dołączenie nowych części do sceny
print(f"Wygenerowano {len(new_parts)} elementów ogrodu 3D.")
scena["parts"].extend(new_parts)

# Zapisanie zaktualizowanej sceny
scena_file.write_text(json.dumps(scena, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Zapisano {len(scena['parts'])} obiektów w scena_modelu.json.")
