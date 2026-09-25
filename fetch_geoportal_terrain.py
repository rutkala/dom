#!/usr/bin/env python3
"""Pobiera rzeczywisty NMT i ortofotomapę z usług GUGiK / Geoportal.

Źródła:
- ULDK: kontrola działki ewidencyjnej,
- WCS NMT GRID1 GeoTIFF: wysokości PL-EVRF2007-NH,
- WMS ORTO: ortofotomapa.

Wynik:
- geoportal_teren.json: mesh NMT + kolorowe kafle ortofotomapy + granica działki,
- geoportal_ortho.jpg: podgląd pobranej ortofotomapy.

Model lokalny pozostaje w metrach / Z-up. Rzędna 0,00 modelu jest wiązana
z rzędną wejścia z PZT.
"""
from __future__ import annotations

import io
import json
import math
import re
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
import requests
from PIL import Image
from pyproj import Transformer
from shapely import wkt
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parent
CFG = json.loads((ROOT / "geoportal_georef.json").read_text(encoding="utf-8"))

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "rutkala-dom-geoportal/1.0 (+https://github.com/rutkala/dom)",
    "Accept": "*/*",
})


def local_name(tag: str) -> str:
    return tag.split("}")[-1].lower()


def model_to_epsg2177(x_mm: float, y_mm: float) -> tuple[float, float]:
    m = CFG["model_to_epsg2177_affine"]
    e = m[0][0] * x_mm + m[0][1] * y_mm + m[0][2]
    n = m[1][0] * x_mm + m[1][1] * y_mm + m[1][2]
    return float(e), float(n)


M2177 = np.asarray(CFG["model_to_epsg2177_affine"], dtype=float)
M2177_INV = np.linalg.inv(M2177)
TO_2180 = Transformer.from_crs(2177, 2180, always_xy=True)
TO_2177 = Transformer.from_crs(2180, 2177, always_xy=True)


def model_to_epsg2180(x_mm: float, y_mm: float) -> tuple[float, float]:
    e, n = model_to_epsg2177(x_mm, y_mm)
    return TO_2180.transform(e, n)


def epsg2180_to_model(e: float, n: float) -> tuple[float, float]:
    e17, n17 = TO_2177.transform(e, n)
    v = M2177_INV @ np.asarray([e17, n17, 1.0], dtype=float)
    return float(v[0]), float(v[1])


def get_parcel_geometry():
    cfg = CFG["parcel"]
    params = {
        "request": "GetParcelById",
        "id": cfg["id"],
        "result": "geom_wkt,teryt,parcel,region,commune,county,voivodeship",
        "srid": "2180",
    }
    r = SESSION.get(cfg["uldk_url"], params=params, timeout=45)
    r.raise_for_status()
    txt = r.text.strip()
    wkt_text = None
    for line in txt.splitlines():
        if "POLYGON" in line.upper():
            positions = [line.upper().find("POLYGON"), line.upper().find("MULTIPOLYGON")]
            idx = min(i for i in positions if i >= 0)
            candidate = line[idx:].split("|")[0].strip()
            try:
                wkt.loads(candidate)
                wkt_text = candidate
                break
            except Exception:
                pass
    if not wkt_text:
        m = re.search(r"((?:MULTI)?POLYGON\s*\(.+\))", txt, flags=re.I | re.S)
        if m:
            candidate = m.group(1).strip().split("|")[0].strip()
            try:
                wkt.loads(candidate)
                wkt_text = candidate
            except Exception:
                pass
    if not wkt_text:
        raise RuntimeError(f"ULDK nie zwrócił geometrii działki. Początek odpowiedzi: {txt[:500]!r}")
    return wkt.loads(wkt_text), txt


def discover_wcs_coverage(url: str) -> tuple[str, str]:
    params = {"SERVICE": "WCS", "VERSION": "1.0.0", "REQUEST": "GetCapabilities"}
    r = SESSION.get(url, params=params, timeout=60)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    candidates = []
    for brief in root.iter():
        if local_name(brief.tag) != "coverageofferingbrief":
            continue
        name = ""
        label = ""
        for child in brief.iter():
            ln = local_name(child.tag)
            if ln == "name" and not name and child.text:
                name = child.text.strip()
            elif ln == "label" and not label and child.text:
                label = child.text.strip()
        if name:
            candidates.append((name, label))
    if not candidates:
        return "1", "fallback"
    preferred = []
    for name, label in candidates:
        key = (name + " " + label).lower()
        score = 0
        if "evrf" in key:
            score += 5
        if "dtm" in key or "terrain" in key:
            score += 4
        if "nmt" in key:
            score += 3
        preferred.append((score, name, label))
    preferred.sort(reverse=True)
    _, name, label = preferred[0]
    return name, label


def fetch_nmt(bbox: tuple[float, float, float, float]):
    cfg = CFG["services"]["nmt_wcs"]
    coverage, label = discover_wcs_coverage(cfg["url"])
    minx, miny, maxx, maxy = bbox
    resolution = float(cfg.get("request_resolution_m", 1.0))
    width = max(32, int(math.ceil((maxx - minx) / resolution)))
    height = max(32, int(math.ceil((maxy - miny) / resolution)))
    base_params = {
        "SERVICE": "WCS",
        "VERSION": "1.0.0",
        "REQUEST": "GetCoverage",
        "COVERAGE": coverage,
        "CRS": "EPSG:2180",
        "RESPONSE_CRS": "EPSG:2180",
        "BBOX": ",".join(f"{v:.3f}" for v in bbox),
        "WIDTH": str(width),
        "HEIGHT": str(height),
    }
    attempts = []
    content = None
    used_format = None
    for fmt in cfg.get("formats", ["GeoTIFF", "image/tiff", "TIFF"]):
        params = dict(base_params)
        params["FORMAT"] = fmt
        r = SESSION.get(cfg["url"], params=params, timeout=120)
        attempts.append((fmt, r.status_code, r.headers.get("content-type", ""), len(r.content)))
        if not r.ok or len(r.content) < 512:
            continue
        if r.content[:4] not in (b"II*\x00", b"MM\x00*"):
            head = r.content[:500].decode("utf-8", errors="ignore")
            if "Exception" in head or "<ServiceException" in head:
                continue
        try:
            with rasterio.io.MemoryFile(r.content) as mem:
                with mem.open() as ds:
                    _ = ds.read(1, out_shape=(1, min(ds.height, 4), min(ds.width, 4)))
            content = r.content
            used_format = fmt
            break
        except Exception:
            continue
    if content is None:
        raise RuntimeError(f"Nie udało się pobrać NMT WCS. Próby: {attempts}")
    with tempfile.NamedTemporaryFile(suffix=".tif", delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    ds = rasterio.open(tmp_path)
    return ds, tmp_path, coverage, label, used_format, attempts


def fetch_orthophoto(bbox: tuple[float, float, float, float]):
    cfg = CFG["services"]["ortho_wms"]
    minx, miny, maxx, maxy = bbox
    width = int(cfg.get("width_px", 1800))
    height = max(256, int(round(width * (maxy - miny) / (maxx - minx))))
    attempts = []
    endpoints = [cfg.get("high_resolution_url"), cfg.get("standard_resolution_url")]
    endpoints = [u for u in endpoints if u]
    for url in endpoints:
        params = {
            "SERVICE": "WMS",
            "VERSION": "1.3.0",
            "REQUEST": "GetMap",
            "LAYERS": cfg.get("layer", "Raster"),
            "STYLES": "",
            "CRS": "EPSG:2180",
            "BBOX": ",".join(f"{v:.3f}" for v in bbox),
            "WIDTH": str(width),
            "HEIGHT": str(height),
            "FORMAT": "image/jpeg",
            "TRANSPARENT": "FALSE",
            "EXCEPTIONS": "XML",
        }
        r = SESSION.get(url, params=params, timeout=120)
        attempts.append((url, r.status_code, r.headers.get("content-type", ""), len(r.content)))
        if not r.ok or len(r.content) < 1024:
            continue
        try:
            img = Image.open(io.BytesIO(r.content)).convert("RGB")
            arr = np.asarray(img)
            if float(arr.std()) < 2.0:
                continue
            return img, url, attempts
        except Exception:
            continue
    raise RuntimeError(f"Nie udało się pobrać ortofotomapy WMS. Próby: {attempts}")


def raster_value(arr, transform, nodata, e: float, n: float):
    row, col = rasterio.transform.rowcol(transform, e, n)
    if row < 0 or col < 0 or row >= arr.shape[0] or col >= arr.shape[1]:
        return None
    v = float(arr[row, col])
    if not math.isfinite(v):
        return None
    if nodata is not None and abs(v - float(nodata)) < 1e-6:
        return None
    if v < 100 or v > 1000:
        return None
    return v


def build_terrain_part(arr, transform, nodata, zero_m: float):
    cfg = CFG["fetch"]
    pixel_x = abs(float(transform.a))
    pixel_y = abs(float(transform.e))
    wanted = float(cfg.get("mesh_step_m", 2.0))
    row_stride = max(1, int(round(wanted / max(pixel_y, 1e-6))))
    col_stride = max(1, int(round(wanted / max(pixel_x, 1e-6))))
    rows = list(range(0, arr.shape[0], row_stride))
    cols = list(range(0, arr.shape[1], col_stride))
    if rows[-1] != arr.shape[0] - 1:
        rows.append(arr.shape[0] - 1)
    if cols[-1] != arr.shape[1] - 1:
        cols.append(arr.shape[1] - 1)

    vertices = []
    index = {}
    heights = []
    for ir, row in enumerate(rows):
        for ic, col in enumerate(cols):
            h = float(arr[row, col])
            valid = math.isfinite(h) and (nodata is None or abs(h - float(nodata)) > 1e-6) and 100 < h < 1000
            if not valid:
                continue
            e, n = rasterio.transform.xy(transform, row, col, offset="center")
            x_mm, y_mm = epsg2180_to_model(float(e), float(n))
            z = h - zero_m
            index[(ir, ic)] = len(vertices)
            vertices.append([x_mm / 1000.0, y_mm / 1000.0, z])
            heights.append(h)

    faces = []
    for ir in range(len(rows) - 1):
        for ic in range(len(cols) - 1):
            keys = [(ir, ic), (ir, ic + 1), (ir + 1, ic + 1), (ir + 1, ic)]
            if not all(k in index for k in keys):
                continue
            a, b, c, d = [index[k] for k in keys]
            faces.append([a, b, c])
            faces.append([a, c, d])

    if not faces:
        raise RuntimeError("NMT nie dał poprawnej siatki w zadanym obszarze.")

    return {
        "name": "GEO_NMT_rzeczywisty",
        "category": "teren_rzeczywisty",
        "material": "teren_rzeczywisty",
        "color": [0.40, 0.47, 0.34, 1.0],
        "source": "Geoportal / GUGiK NMT GRID1 WCS, PL-EVRF2007-NH",
        "source_id": "GEO_NMT",
        "assumed": False,
        "note": f"Rzeczywisty NMT; Z=0 modelu odpowiada {zero_m:.2f} m n.p.m.",
        "positions_m": vertices,
        "faces": faces,
        "reference_area_m2": None,
        "stats": {
            "min_elevation_m": round(min(heights), 3),
            "max_elevation_m": round(max(heights), 3),
            "vertices": len(vertices),
            "triangles": len(faces),
            "grid_stride_rows": row_stride,
            "grid_stride_cols": col_stride,
        },
    }


def sample_image_rgb(img_arr: np.ndarray, bbox, e: float, n: float):
    minx, miny, maxx, maxy = bbox
    h, w = img_arr.shape[:2]
    px = (e - minx) / (maxx - minx) * (w - 1)
    py = (maxy - n) / (maxy - miny) * (h - 1)
    ix = min(max(int(round(px)), 0), w - 1)
    iy = min(max(int(round(py)), 0), h - 1)
    x0, x1 = max(0, ix - 2), min(w, ix + 3)
    y0, y1 = max(0, iy - 2), min(h, iy + 3)
    rgb = img_arr[y0:y1, x0:x1].reshape(-1, 3).mean(axis=0)
    mean = float(rgb.mean())
    rgb = 0.88 * rgb + 0.12 * mean
    rgb = np.clip(rgb / 255.0 * 0.92 + 0.04, 0, 1)
    return [round(float(x), 4) for x in rgb] + [1.0]


def build_ortho_tiles(img: Image.Image, bbox, arr, transform, nodata, zero_m: float):
    img_arr = np.asarray(img)
    minx, miny, maxx, maxy = bbox
    tile = float(CFG["fetch"].get("ortho_tile_m", 6.0))
    nx = int(math.ceil((maxx - minx) / tile))
    ny = int(math.ceil((maxy - miny) / tile))
    parts = []
    for iy in range(ny):
        n0 = miny + iy * tile
        n1 = min(maxy, n0 + tile)
        for ix in range(nx):
            e0 = minx + ix * tile
            e1 = min(maxx, e0 + tile)
            ec = (e0 + e1) / 2
            nc = (n0 + n1) / 2
            color = sample_image_rgb(img_arr, bbox, ec, nc)
            corners_global = [(e0, n0), (e1, n0), (e1, n1), (e0, n1)]
            verts = []
            ok = True
            for e, n in corners_global:
                h = raster_value(arr, transform, nodata, e, n)
                if h is None:
                    ok = False
                    break
                x_mm, y_mm = epsg2180_to_model(e, n)
                verts.append([x_mm / 1000.0, y_mm / 1000.0, (h - zero_m) + 0.025])
            if not ok:
                continue
            parts.append({
                "name": f"GEO_ORTHO_{iy:02d}_{ix:02d}",
                "category": "ortofoto",
                "material": "ortofoto",
                "color": color,
                "source": "Geoportal / GUGiK ortofotomapa WMS",
                "source_id": "GEO_ORTHO",
                "assumed": False,
                "note": f"Kafelek ortofotomapy {tile:.1f} m, kolor uśredniony z obrazu WMS.",
                "positions_m": verts,
                "faces": [[0, 1, 2], [0, 2, 3]],
                "reference_area_m2": round((e1 - e0) * (n1 - n0), 3),
            })
    return parts


def build_parcel_parts(parcel_geom, arr, transform, nodata, zero_m: float):
    parts = []
    rings = [parcel_geom.exterior] if parcel_geom.geom_type == "Polygon" else [g.exterior for g in parcel_geom.geoms]
    width = float(CFG["fetch"].get("parcel_line_width_m", 0.12))
    seg_no = 0
    for ring in rings:
        coords = list(ring.coords)
        for (e0, n0), (e1, n1) in zip(coords, coords[1:]):
            h0 = raster_value(arr, transform, nodata, e0, n0)
            h1 = raster_value(arr, transform, nodata, e1, n1)
            if h0 is None or h1 is None:
                continue
            x0, y0 = epsg2180_to_model(e0, n0)
            x1, y1 = epsg2180_to_model(e1, n1)
            p0 = np.asarray([x0 / 1000.0, y0 / 1000.0], dtype=float)
            p1 = np.asarray([x1 / 1000.0, y1 / 1000.0], dtype=float)
            d = p1 - p0
            L = float(np.linalg.norm(d))
            if L < 1e-4:
                continue
            perp = np.asarray([-d[1], d[0]], dtype=float) / L * (width / 2)
            z0 = h0 - zero_m + 0.08
            z1 = h1 - zero_m + 0.08
            verts = [
                [*(p0 - perp), z0],
                [*(p0 + perp), z0],
                [*(p1 + perp), z1],
                [*(p1 - perp), z1],
            ]
            seg_no += 1
            parts.append({
                "name": f"GEO_PARCEL_{seg_no:03d}",
                "category": "granica_dzialki",
                "material": "granica_dzialki",
                "color": [0.97, 0.48, 0.05, 1.0],
                "source": "GUGiK ULDK / EGiB",
                "source_id": "GEO_PARCEL",
                "assumed": False,
                "note": "Granica działki ewidencyjnej z ULDK.",
                "positions_m": verts,
                "faces": [[0, 1, 2], [0, 2, 3]],
                "reference_area_m2": round(L * width, 4),
            })
    return parts


def main():
    fetch_cfg = CFG["fetch"]
    cx_mm, cy_mm = map(float, fetch_cfg["center_model_mm"])
    cx, cy = model_to_epsg2180(cx_mm, cy_mm)
    radius = float(fetch_cfg.get("radius_m", 90.0))
    bbox = (cx - radius, cy - radius, cx + radius, cy + radius)
    zero_m = float(CFG["vertical"]["model_zero_elevation_m"])

    print(f"Model center EPSG:2180: {cx:.3f}, {cy:.3f}")
    print(f"Geoportal bbox EPSG:2180: {bbox}")

    parcel_geom = None
    parcel_raw = ""
    parcel_error = None
    try:
        parcel_geom, parcel_raw = get_parcel_geometry()
        print(f"ULDK parcel: {parcel_geom.geom_type}, area={parcel_geom.area:.1f} m²")
    except Exception as exc:
        parcel_error = str(exc)
        print(f"UWAGA: ULDK validation failed: {parcel_error}")

    ds, tmp_path, coverage, coverage_label, fmt, nmt_attempts = fetch_nmt(bbox)
    try:
        arr = ds.read(1)
        transform = ds.transform
        nodata = ds.nodata
        print(f"NMT: {ds.width}x{ds.height}, CRS={ds.crs}, nodata={nodata}, coverage={coverage!r}")
        terrain = build_terrain_part(arr, transform, nodata, zero_m)

        ortho_img, ortho_url, ortho_attempts = fetch_orthophoto(bbox)
        ortho_img.save(ROOT / "geoportal_ortho.jpg", format="JPEG", quality=90, optimize=True)
        ortho_parts = build_ortho_tiles(ortho_img, bbox, arr, transform, nodata, zero_m)

        parcel_parts = []
        validation = {}
        if parcel_geom is not None:
            parcel_parts = build_parcel_parts(parcel_geom, arr, transform, nodata, zero_m)
            house_center = Point(cx, cy)
            validation = {
                "parcel_contains_fetch_center": bool(parcel_geom.contains(house_center) or parcel_geom.touches(house_center)),
                "distance_fetch_center_to_parcel_m": round(float(parcel_geom.distance(house_center)), 3),
                "parcel_area_m2": round(float(parcel_geom.area), 3),
            }

        result = {
            "status": "fetched",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "source": {
                "nmt": {
                    "service": CFG["services"]["nmt_wcs"]["url"],
                    "coverage": coverage,
                    "coverage_label": coverage_label,
                    "format": fmt,
                    "crs": str(ds.crs),
                    "vertical_system": CFG["vertical"]["system"],
                    "attempts": nmt_attempts,
                },
                "ortho": {
                    "service": ortho_url,
                    "crs": "EPSG:2180",
                    "attempts": ortho_attempts,
                },
                "parcel": {
                    "service": CFG["parcel"]["uldk_url"],
                    "id": CFG["parcel"]["id"],
                    "error": parcel_error,
                },
            },
            "alignment": {
                "model_zero_elevation_m": zero_m,
                "model_horizontal_source_crs": "EPSG:2177",
                "download_crs": "EPSG:2180",
                "bbox_epsg2180": [round(v, 3) for v in bbox],
                "center_epsg2180": [round(cx, 3), round(cy, 3)],
                "model_to_epsg2177_affine": CFG["model_to_epsg2177_affine"],
                "control": CFG["control"],
            },
            "validation": validation,
            "stats": {
                "terrain_min_elevation_m": terrain["stats"]["min_elevation_m"],
                "terrain_max_elevation_m": terrain["stats"]["max_elevation_m"],
                "terrain_vertices": terrain["stats"]["vertices"],
                "terrain_triangles": terrain["stats"]["triangles"],
                "ortho_tiles": len(ortho_parts),
                "parcel_segments": len(parcel_parts),
            },
            "parts": [terrain] + ortho_parts + parcel_parts,
        }
        (ROOT / "geoportal_teren.json").write_text(
            json.dumps(result, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        print("Zapisano geoportal_teren.json")
        print(json.dumps(result["stats"], ensure_ascii=False, indent=2))
        print(json.dumps(result["validation"], ensure_ascii=False, indent=2))
    finally:
        ds.close()
        try:
            tmp_path.unlink()
        except Exception:
            pass


if __name__ == "__main__":
    main()
