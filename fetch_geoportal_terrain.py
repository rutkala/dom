#!/usr/bin/env python3
"""Pobiera rzeczywisty NMT i ortofotomapę z usług GUGiK / Geoportal.

Źródła:
- ULDK: granica i kontrola działki ewidencyjnej,
- WMS NMT "SkorowidzeUkladEVRF2007": linki do plików NMT PL-EVRF2007-NH,
- WMS ORTO: bieżąca ortofotomapa.

Wynik:
- geoportal_teren.json: mesh NMT + kafle ortofotomapy + granica działki,
- geoportal_ortho.jpg: podgląd ortofotomapy.

Model lokalny pozostaje w metrach / Z-up. Rzędna 0,00 modelu jest wiązana
z rzędną wejścia z PZT w układzie PL-EVRF2007-NH.
"""
from __future__ import annotations

import html
import io
import json
import math
import re
import tempfile
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import numpy as np
import rasterio
import requests
from PIL import Image
from pyproj import Transformer
from rasterio.merge import merge as raster_merge
from shapely import wkt
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parent
CFG = json.loads((ROOT / "geoportal_georef.json").read_text(encoding="utf-8"))

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Pobieracz-QGIS-Client/1.0 rutkala-dom-geoportal",
    "Accept": "*/*",
    "Connection": "close",
})


def local_name(tag: str) -> str:
    return tag.split("}")[-1].lower()


def request_get(url: str, *, params=None, timeout=60, attempts=4):
    errors = []
    for attempt in range(1, attempts + 1):
        try:
            r = SESSION.get(url, params=params, timeout=timeout)
            if r.status_code >= 500 and attempt < attempts:
                errors.append(f"HTTP {r.status_code}")
                time.sleep(1.2 * attempt)
                continue
            return r
        except requests.RequestException as exc:
            errors.append(repr(exc))
            if attempt >= attempts:
                raise
            time.sleep(1.2 * attempt)
    raise RuntimeError(f"Nie udało się pobrać {url}: {errors}")


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
    r = request_get(cfg["uldk_url"], params=params, timeout=45)
    r.raise_for_status()
    txt = r.text.strip()
    for line in txt.splitlines():
        upper = line.upper()
        if "POLYGON" not in upper:
            continue
        starts = [i for i in (upper.find("POLYGON"), upper.find("MULTIPOLYGON")) if i >= 0]
        if not starts:
            continue
        candidate = line[min(starts):].split("|")[0].strip()
        try:
            return wkt.loads(candidate), txt
        except Exception:
            pass
    m = re.search(r"((?:MULTI)?POLYGON\s*\(.+\))", txt, flags=re.I | re.S)
    if m:
        candidate = m.group(1).strip().split("|")[0].strip()
        try:
            return wkt.loads(candidate), txt
        except Exception:
            pass
    raise RuntimeError(f"ULDK nie zwrócił geometrii działki. Początek: {txt[:500]!r}")


def get_queryable_wms_layers(url: str) -> list[str]:
    r = request_get(url, params={"SERVICE": "WMS", "REQUEST": "GetCapabilities"}, timeout=60)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    queryable = []
    fallback = []
    for layer in root.iter():
        if local_name(layer.tag) != "layer":
            continue
        name = None
        for child in list(layer):
            if local_name(child.tag) == "name" and child.text:
                name = child.text.strip()
                break
        if not name:
            continue
        fallback.append(name)
        if str(layer.attrib.get("queryable", "0")) in ("1", "true", "True"):
            queryable.append(name)
    result = queryable or fallback
    return list(dict.fromkeys(result))


def parse_wms_objects(content: str) -> list[dict]:
    text = html.unescape(content)
    # Geoportal zwraca obiekty podobne do JSON: {"nazwa_pliku":"https://...", ...}
    chunks = re.findall(r"\{[^{}\r\n]*\}", text)
    objects = []
    for chunk in chunks:
        pairs = re.findall(r'"([^"]+)"\s*:\s*"([^"]*)"', chunk)
        if pairs:
            objects.append({k: v for k, v in pairs})
            continue
        attrs = {}
        raw = chunk.strip("{}")
        for item in raw.split(","):
            if ":" not in item:
                continue
            k, v = item.split(":", 1)
            attrs[k.strip().strip('"')] = v.strip().strip('"')
        if attrs:
            objects.append(attrs)
    # awaryjnie wyciągnij linki, jeżeli serwis zmieni format HTML
    if not objects:
        links = re.findall(r'https?://[^\s"\'<>]+', text)
        objects = [{"nazwa_pliku": u.rstrip(").,;")} for u in links]
    unique = []
    seen = set()
    for obj in objects:
        key = json.dumps(obj, sort_keys=True, ensure_ascii=False)
        if key not in seen:
            seen.add(key)
            unique.append(obj)
    return unique


def nmt_object_url(obj: dict) -> str:
    for key in ("nazwa_pliku", "url", "link", "LinkDoPobrania", "link_do_pobrania"):
        value = obj.get(key)
        if value and str(value).startswith(("http://", "https://")):
            return html.unescape(str(value))
    for value in obj.values():
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return html.unescape(value)
    return ""


def nmt_object_score(obj: dict) -> tuple:
    url = nmt_object_url(obj)
    fmt = str(obj.get("format", "")).upper()
    crs = str(obj.get("ukladWspolrzednych", obj.get("uklad_wspolrzednych_plaskich", ""))).upper()
    vertical = str(obj.get("ukladWysokosci", obj.get("uklad_wspolrzednych_wysokosciowych", ""))).upper()
    text_all = " ".join(str(v) for v in obj.values())
    years = [int(x) for x in re.findall(r"20\d{2}", text_all) if 2010 <= int(x) <= 2099]
    year = max(years) if years else 0
    is_asc = "ASC" in fmt or ".ASC" in url.upper() or "ASCII" in fmt
    is_1992 = "1992" in crs or "2180" in crs
    is_evrf = "EVRF" in vertical or "2007" in vertical or not vertical
    filled = str(obj.get("calyArkuszWyeplnionyTrescia", obj.get("caly_arkusz_wypelniony_trescia", ""))).lower()
    full_sheet = 1 if filled in ("1", "true", "tak", "yes") else 0
    return (1 if is_asc else 0, 1 if is_1992 else 0, 1 if is_evrf else 0, year, full_sheet)


def query_nmt_objects_at_point(service_url: str, e: float, n: float) -> tuple[list[dict], dict]:
    layers = get_queryable_wms_layers(service_url)
    if not layers:
        return [], {"layers": [], "response_chars": 0}
    # Geoportal 1.3.0 dla EPSG:2180 stosuje kolejność osi zgodną z oficjalnym klientem:
    # BBOX = northing,easting,northing,easting.
    bbox_axis = f"{n-50:.3f},{e-50:.3f},{n+50:.3f},{e+50:.3f}"
    params = {
        "SERVICE": "WMS",
        "request": "GetFeatureInfo",
        "version": "1.3.0",
        "styles": "",
        "crs": "EPSG:2180",
        "width": "101",
        "height": "101",
        "format": "image/png",
        "transparent": "true",
        "i": "50",
        "j": "50",
        "INFO_FORMAT": CFG["services"]["nmt_evrf_wms"].get("info_format", "text/html"),
        "layers": ",".join(layers),
        "query_layers": ",".join(layers),
        "bbox": bbox_axis,
    }
    r = request_get(service_url, params=params, timeout=75)
    r.raise_for_status()
    objs = parse_wms_objects(r.text)
    # Niektóre wdrożenia WMS tolerują/oczekują tradycyjnej kolejności XY.
    if not objs:
        params["bbox"] = f"{e-50:.3f},{n-50:.3f},{e+50:.3f},{n+50:.3f}"
        r = request_get(service_url, params=params, timeout=75)
        r.raise_for_status()
        objs = parse_wms_objects(r.text)
    return objs, {"layers": layers, "response_chars": len(r.text)}


def select_nmt_object(objects: list[dict]) -> dict | None:
    candidates = [o for o in objects if nmt_object_url(o)]
    if not candidates:
        return None
    candidates.sort(key=nmt_object_score, reverse=True)
    # Preferuj PL-1992 / EPSG:2180. Dane w innym układzie nie są mieszane z siatką modelu.
    best_2180 = [o for o in candidates if nmt_object_score(o)[1] == 1]
    return (best_2180 or candidates)[0]


def nmt_download_links_for_bbox(bbox) -> tuple[list[tuple[str, dict]], dict]:
    minx, miny, maxx, maxy = bbox
    # punkty wewnątrz obszaru; wystarczą do zebrania sąsiadujących arkuszy 1 km
    xs = [minx + 2, (minx + maxx) / 2, maxx - 2]
    ys = [miny + 2, (miny + maxy) / 2, maxy - 2]
    service_cfg = CFG["services"]["nmt_evrf_wms"]
    services = [
        ("1m", service_cfg["url"]),
        ("5m", service_cfg.get("fallback_5m_url")),
    ]
    diagnostics = {"queries": [], "service": None}
    for service_name, service_url in services:
        if not service_url:
            continue
        found = {}
        for e in xs:
            for n in ys:
                try:
                    objs, diag = query_nmt_objects_at_point(service_url, e, n)
                    selected = select_nmt_object(objs)
                    diagnostics["queries"].append({
                        "service": service_name,
                        "point": [round(e, 3), round(n, 3)],
                        "objects": len(objs),
                        "layers": diag.get("layers", []),
                        "selected": selected,
                    })
                    if selected:
                        url = nmt_object_url(selected)
                        found[url] = selected
                except Exception as exc:
                    diagnostics["queries"].append({
                        "service": service_name,
                        "point": [round(e, 3), round(n, 3)],
                        "error": repr(exc),
                    })
        if found:
            diagnostics["service"] = service_url
            diagnostics["resolution_family"] = service_name
            return list(found.items()), diagnostics
    raise RuntimeError("Nie znaleziono plików NMT PL-EVRF2007-NH dla zadanego obszaru.")


def save_downloaded_raster_files(url: str, temp_dir: Path) -> list[Path]:
    r = request_get(url, timeout=180, attempts=4)
    r.raise_for_status()
    content = r.content
    if len(content) < 500:
        raise RuntimeError(f"Za mały plik NMT z {url}: {len(content)} B")
    paths = []
    if content[:2] == b"PK" or url.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            for name in zf.namelist():
                lower = name.lower()
                if not lower.endswith((".asc", ".tif", ".tiff")):
                    continue
                target = temp_dir / Path(name).name
                target.write_bytes(zf.read(name))
                paths.append(target)
    else:
        suffix = Path(urlparse(url).path).suffix.lower()
        if suffix not in (".asc", ".tif", ".tiff"):
            if content[:4] in (b"II*\x00", b"MM\x00*"):
                suffix = ".tif"
            elif content[:32].lstrip().lower().startswith(b"ncols"):
                suffix = ".asc"
            else:
                suffix = ".dat"
        target = temp_dir / f"nmt_{abs(hash(url))}{suffix}"
        target.write_bytes(content)
        paths.append(target)
    if not paths:
        raise RuntimeError(f"Archiwum NMT nie zawiera ASC/TIFF: {url}")
    return paths


def fetch_nmt_evrf(bbox):
    selected, diagnostics = nmt_download_links_for_bbox(bbox)
    temp_dir_obj = tempfile.TemporaryDirectory(prefix="nmt_evrf_")
    temp_dir = Path(temp_dir_obj.name)
    raster_paths = []
    metadata = []
    for url, obj in selected:
        try:
            files = save_downloaded_raster_files(url, temp_dir)
            raster_paths.extend(files)
            metadata.append({"url": url, "object": obj, "files": [p.name for p in files]})
        except Exception as exc:
            metadata.append({"url": url, "object": obj, "error": repr(exc)})
    if not raster_paths:
        temp_dir_obj.cleanup()
        raise RuntimeError(f"Nie udało się pobrać żadnego arkusza NMT: {metadata}")

    datasets = []
    try:
        for path in raster_paths:
            ds = rasterio.open(path)
            # Arc/Info ASCII zwykle nie ma wpisanego CRS, ale skorowidz został przefiltrowany do PL-1992.
            datasets.append(ds)
        pixel_sizes = [max(abs(float(ds.transform.a)), abs(float(ds.transform.e))) for ds in datasets]
        source_res = min(pixel_sizes)
        nodata = -9999.0
        mosaic, transform = raster_merge(
            datasets,
            bounds=bbox,
            res=source_res,
            nodata=nodata,
            dtype="float32",
        )
        arr = mosaic[0]
        if not np.isfinite(arr).any():
            raise RuntimeError("Po scaleniu arkuszy NMT brak danych.")
        return arr, transform, nodata, {
            "service": diagnostics.get("service"),
            "resolution_family": diagnostics.get("resolution_family"),
            "source_resolution_m": round(float(source_res), 4),
            "vertical_system": "PL-EVRF2007-NH",
            "horizontal_system": "PL-1992 / EPSG:2180",
            "downloads": metadata,
            "diagnostics": diagnostics,
        }, temp_dir_obj
    except Exception:
        for ds in datasets:
            ds.close()
        temp_dir_obj.cleanup()
        raise
    finally:
        for ds in datasets:
            try:
                ds.close()
            except Exception:
                pass


def discover_wcs_coverages(url: str) -> list[tuple[str, str]]:
    params = {"SERVICE": "WCS", "VERSION": "1.0.0", "REQUEST": "GetCapabilities"}
    r = request_get(url, params=params, timeout=60, attempts=4)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    result = []
    for brief in root.iter():
        if local_name(brief.tag) != "coverageofferingbrief":
            continue
        name, label = "", ""
        for child in brief.iter():
            ln = local_name(child.tag)
            if ln == "name" and not name and child.text:
                name = child.text.strip()
            elif ln == "label" and not label and child.text:
                label = child.text.strip()
        if name:
            result.append((name, label))
    return result


def fetch_orthophoto_wcs(bbox: tuple[float, float, float, float]):
    cfg = CFG["services"].get("ortho_wcs", {})
    url = cfg.get("standard_resolution_url")
    if not url:
        raise RuntimeError("Brak ortho_wcs.standard_resolution_url w konfiguracji.")
    minx, miny, maxx, maxy = bbox
    width = int(CFG["services"]["ortho_wms"].get("width_px", 1800))
    height = max(256, int(round(width * (maxy - miny) / (maxx - minx))))

    coverages = discover_wcs_coverages(url)
    preferred = cfg.get("preferred_coverage", "Orthoimagery_StandardResolution")
    ordered = sorted(
        coverages,
        key=lambda x: (
            0 if x[0] == preferred else 1,
            0 if "standard" in (x[0] + " " + x[1]).lower() else 1,
            x[0],
        ),
    )
    if not ordered:
        ordered = [(preferred, "configured fallback")]

    attempts = []
    formats = [cfg.get("format", "GEOTIFF"), "GeoTIFF", "image/tiff", "TIFF"]
    for coverage, label in ordered:
        for fmt in dict.fromkeys(formats):
            params = {
                "SERVICE": "WCS",
                "VERSION": "1.0.0",
                "REQUEST": "GetCoverage",
                "COVERAGE": coverage,
                "CRS": "EPSG:2180",
                "RESPONSE_CRS": "EPSG:2180",
                "BBOX": ",".join(f"{v:.3f}" for v in bbox),
                "WIDTH": str(width),
                "HEIGHT": str(height),
                "FORMAT": fmt,
            }
            try:
                r = request_get(url, params=params, timeout=150, attempts=4)
                ctype = r.headers.get("content-type", "")
                head = r.content[:700].decode("utf-8", errors="ignore")
                attempts.append((url, coverage, fmt, r.status_code, ctype, len(r.content), head[:220]))
                if not r.ok or len(r.content) < 1024:
                    continue
                if "<ServiceException" in head or "ExceptionReport" in head:
                    continue
                try:
                    img = Image.open(io.BytesIO(r.content)).convert("RGB")
                    if float(np.asarray(img).std()) >= 2.0:
                        return img, f"{url} [{coverage}]", attempts
                except Exception:
                    pass
                try:
                    with rasterio.io.MemoryFile(r.content) as mem:
                        with mem.open() as ds:
                            bands = ds.read()
                            if bands.shape[0] >= 3:
                                rgb = np.moveaxis(bands[:3], 0, 2)
                            else:
                                band = bands[0].astype(float)
                                finite = np.isfinite(band)
                                if not finite.any():
                                    continue
                                lo, hi = np.nanpercentile(band[finite], [2, 98])
                                scaled = np.clip((band - lo) / max(float(hi - lo), 1e-6) * 255, 0, 255).astype(np.uint8)
                                rgb = np.dstack([scaled, scaled, scaled])
                            if rgb.dtype != np.uint8:
                                mx = float(np.nanmax(rgb)) if np.isfinite(rgb).any() else 255.0
                                if mx <= 1.5:
                                    rgb = (np.clip(rgb, 0, 1) * 255).astype(np.uint8)
                                else:
                                    rgb = np.clip(rgb, 0, 255).astype(np.uint8)
                            img = Image.fromarray(rgb).convert("RGB")
                            if float(np.asarray(img).std()) >= 2.0:
                                return img, f"{url} [{coverage}]", attempts
                except Exception:
                    continue
            except Exception as exc:
                attempts.append((url, coverage, fmt, "exception", repr(exc), 0, ""))
    raise RuntimeError(f"Nie udało się pobrać ortofotomapy WCS. Próby: {attempts}")


def fetch_orthophoto_wms(bbox: tuple[float, float, float, float]):
    cfg = CFG["services"]["ortho_wms"]
    minx, miny, maxx, maxy = bbox
    width = int(cfg.get("width_px", 1800))
    height = max(256, int(round(width * (maxy - miny) / (maxx - minx))))
    attempts_log = []
    specs = [
        {
            "url": cfg.get("standard_resolution_url"),
            "version": "1.3.0",
            "layers": "Raster",
            "format": "image/jpeg",
            "crs_key": "CRS",
        },
        {
            "url": cfg.get("high_resolution_url"),
            "version": "1.1.1",
            "layers": "3,2,1",
            "format": "image/png",
            "crs_key": "SRS",
        },
    ]
    for spec in specs:
        url = spec["url"]
        if not url:
            continue
        params = {
            "SERVICE": "WMS",
            "VERSION": spec["version"],
            "REQUEST": "GetMap",
            "LAYERS": spec["layers"],
            "STYLES": "" if spec["layers"] == "Raster" else ",,",
            spec["crs_key"]: "EPSG:2180",
            "BBOX": ",".join(f"{v:.3f}" for v in bbox),
            "WIDTH": str(width),
            "HEIGHT": str(height),
            "FORMAT": spec["format"],
            "TRANSPARENT": "FALSE",
            "EXCEPTIONS": "XML",
        }
        try:
            r = request_get(url, params=params, timeout=120, attempts=4)
            head = r.content[:700].decode("utf-8", errors="ignore")
            attempts_log.append((url, r.status_code, r.headers.get("content-type", ""), len(r.content), head[:220]))
            if not r.ok or len(r.content) < 1024:
                continue
            img = Image.open(io.BytesIO(r.content)).convert("RGB")
            if float(np.asarray(img).std()) < 2.0:
                continue
            return img, url, attempts_log
        except Exception as exc:
            attempts_log.append((url, "exception", repr(exc), 0, ""))
    raise RuntimeError(f"Nie udało się pobrać ortofotomapy WMS. Próby: {attempts_log}")


def fetch_orthophoto(bbox: tuple[float, float, float, float]):
    errors = []
    try:
        img, url, attempts = fetch_orthophoto_wcs(bbox)
        return img, url, {"primary": "WCS", "attempts": attempts}
    except Exception as exc:
        errors.append(("WCS", repr(exc)))
    try:
        img, url, attempts = fetch_orthophoto_wms(bbox)
        return img, url, {"primary": "WMS", "attempts": attempts, "wcs_error": errors}
    except Exception as exc:
        errors.append(("WMS", repr(exc)))
    raise RuntimeError(f"Nie udało się pobrać ortofotomapy z WCS ani WMS: {errors}")


def raster_value(arr, transform, nodata, e: float, n: float):
    row, col = rasterio.transform.rowcol(transform, e, n)
    if row < 0 or col < 0 or row >= arr.shape[0] or col >= arr.shape[1]:
        return None
    v = float(arr[row, col])
    if not math.isfinite(v):
        return None
    if nodata is not None and abs(v - float(nodata)) < 1e-5:
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
            valid = math.isfinite(h) and (nodata is None or abs(h - float(nodata)) > 1e-5) and 100 < h < 1000
            if not valid:
                continue
            e, n = rasterio.transform.xy(transform, row, col, offset="center")
            x_mm, y_mm = epsg2180_to_model(float(e), float(n))
            index[(ir, ic)] = len(vertices)
            vertices.append([x_mm / 1000.0, y_mm / 1000.0, h - zero_m])
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
        "source": "Geoportal / GUGiK NMT PL-EVRF2007-NH",
        "source_id": "GEO_NMT",
        "assumed": False,
        "note": f"Rzeczywisty NMT; Z=0 modelu odpowiada {zero_m:.2f} m n.p.m. (PL-EVRF2007-NH).",
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
            ec, nc = (e0 + e1) / 2, (n0 + n1) / 2
            color = sample_image_rgb(img_arr, bbox, ec, nc)
            verts = []
            ok = True
            for e, n in ((e0, n0), (e1, n0), (e1, n1), (e0, n1)):
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
            z0, z1 = h0 - zero_m + 0.08, h1 - zero_m + 0.08
            parts.append({
                "name": f"GEO_PARCEL_{seg_no:03d}",
                "category": "granica_dzialki",
                "material": "granica_dzialki",
                "color": [0.97, 0.48, 0.05, 1.0],
                "source": "GUGiK ULDK / EGiB",
                "source_id": "GEO_PARCEL",
                "assumed": False,
                "note": "Granica działki ewidencyjnej z ULDK.",
                "positions_m": [
                    [*(p0 - perp), z0], [*(p0 + perp), z0],
                    [*(p1 + perp), z1], [*(p1 - perp), z1],
                ],
                "faces": [[0, 1, 2], [0, 2, 3]],
                "reference_area_m2": round(L * width, 4),
            })
            seg_no += 1
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
    parcel_error = None
    try:
        parcel_geom, _ = get_parcel_geometry()
        print(f"ULDK parcel: {parcel_geom.geom_type}, area={parcel_geom.area:.1f} m²")
    except Exception as exc:
        parcel_error = str(exc)
        print(f"UWAGA: ULDK validation failed: {parcel_error}")

    arr, transform, nodata, nmt_meta, tmp_holder = fetch_nmt_evrf(bbox)
    try:
        print(
            f"NMT EVRF: {arr.shape[1]}x{arr.shape[0]}, "
            f"res={nmt_meta['source_resolution_m']} m, downloads={len(nmt_meta['downloads'])}"
        )
        terrain = build_terrain_part(arr, transform, nodata, zero_m)

        ortho_img, ortho_url, ortho_attempts = fetch_orthophoto(bbox)
        ortho_img.save(ROOT / "geoportal_ortho.jpg", format="JPEG", quality=90, optimize=True)
        ortho_parts = build_ortho_tiles(ortho_img, bbox, arr, transform, nodata, zero_m)

        parcel_parts = []
        validation = {}
        center_height = raster_value(arr, transform, nodata, cx, cy)
        validation["nmt_at_model_center_m"] = round(center_height, 3) if center_height is not None else None
        validation["nmt_center_relative_to_model_zero_m"] = (
            round(center_height - zero_m, 3) if center_height is not None else None
        )
        if parcel_geom is not None:
            parcel_parts = build_parcel_parts(parcel_geom, arr, transform, nodata, zero_m)
            house_center = Point(cx, cy)
            validation.update({
                "parcel_contains_fetch_center": bool(parcel_geom.contains(house_center) or parcel_geom.touches(house_center)),
                "distance_fetch_center_to_parcel_m": round(float(parcel_geom.distance(house_center)), 3),
                "parcel_area_m2": round(float(parcel_geom.area), 3),
            })

        result = {
            "status": "fetched",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "source": {
                "nmt": nmt_meta,
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
                "model_vertical_system": CFG["vertical"]["system"],
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
        tmp_holder.cleanup()


if __name__ == "__main__":
    main()
