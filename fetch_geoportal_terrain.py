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
from rasterio.warp import reproject, Resampling
from rasterio.features import geometry_mask
from shapely import wkt
from shapely.geometry import Point, Polygon, MultiPolygon, mapping
import trimesh

ROOT = Path(__file__).resolve().parent
CFG = json.loads((ROOT / "geoportal_georef.json").read_text(encoding="utf-8"))
MODEL_DATA = json.loads((ROOT / "dane_zrodlowe.json").read_text(encoding="utf-8"))

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



def nmpt_download_links_for_bbox(bbox) -> tuple[list[tuple[str, dict]], dict]:
    minx, miny, maxx, maxy = bbox
    xs = [minx + 2, (minx + maxx) / 2, maxx - 2]
    ys = [miny + 2, (miny + maxy) / 2, maxy - 2]
    service_url = CFG["services"]["nmpt_evrf_wms"]["url"]
    diagnostics = {"queries": [], "service": service_url, "resolution_family": "NMPT"}
    found = {}
    for e in xs:
        for n in ys:
            try:
                objs, diag = query_nmt_objects_at_point(service_url, e, n)
                selected = select_nmt_object(objs)
                diagnostics["queries"].append({
                    "point": [round(e, 3), round(n, 3)],
                    "objects": len(objs),
                    "layers": diag.get("layers", []),
                    "selected": selected,
                })
                if selected:
                    found[nmt_object_url(selected)] = selected
            except Exception as exc:
                diagnostics["queries"].append({
                    "point": [round(e, 3), round(n, 3)],
                    "error": repr(exc),
                })
    if not found:
        raise RuntimeError("Nie znaleziono plików NMPT PL-EVRF2007-NH dla zadanego obszaru.")
    return list(found.items()), diagnostics


def fetch_nmpt_evrf(bbox):
    selected, diagnostics = nmpt_download_links_for_bbox(bbox)
    temp_dir_obj = tempfile.TemporaryDirectory(prefix="nmpt_evrf_")
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
        raise RuntimeError(f"Nie udało się pobrać żadnego arkusza NMPT: {metadata}")
    datasets = []
    try:
        for path in raster_paths:
            datasets.append(rasterio.open(path))
        pixel_sizes = [max(abs(float(ds.transform.a)), abs(float(ds.transform.e))) for ds in datasets]
        source_res = min(pixel_sizes)
        nodata = -9999.0
        mosaic, transform = raster_merge(
            datasets, bounds=bbox, res=source_res, nodata=nodata, dtype="float32"
        )
        arr = mosaic[0]
        if not np.isfinite(arr).any():
            raise RuntimeError("Po scaleniu arkuszy NMPT brak danych.")
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
        temp_dir_obj.cleanup()
        raise
    finally:
        for ds in datasets:
            try:
                ds.close()
            except Exception:
                pass


def align_raster_to_nmt(src_arr, src_transform, src_nodata, dst_shape, dst_transform):
    dst = np.full(dst_shape, np.nan, dtype=np.float32)
    source = np.asarray(src_arr, dtype=np.float32).copy()
    source[~np.isfinite(source)] = float(src_nodata if src_nodata is not None else -9999.0)
    reproject(
        source=source,
        destination=dst,
        src_transform=src_transform,
        src_crs="EPSG:2180",
        src_nodata=src_nodata,
        dst_transform=dst_transform,
        dst_crs="EPSG:2180",
        dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )
    return dst


def parse_egib_buildings_gml(content: bytes):
    root = ET.fromstring(content)
    buildings = []
    for member in root.iter():
        if local_name(member.tag) != "member":
            continue
        feature = next(iter(member), None)
        if feature is None or "budyn" not in local_name(feature.tag):
            continue
        polygons = []
        for poly_el in feature.iter():
            if local_name(poly_el.tag) != "polygon":
                continue
            exterior = None
            holes = []
            for child in poly_el.iter():
                ln = local_name(child.tag)
                if ln not in ("exterior", "interior"):
                    continue
                pos = next((x for x in child.iter() if local_name(x.tag) == "poslist" and x.text), None)
                if pos is None:
                    continue
                vals = [float(v) for v in pos.text.split()]
                if len(vals) < 6:
                    continue
                # WFS/GML 3.2 dla EPSG:2180 zwraca kolejność osi northing,easting.
                ring = [(vals[i+1], vals[i]) for i in range(0, len(vals)-1, 2)]
                if ring[0] != ring[-1]:
                    ring.append(ring[0])
                if ln == "exterior":
                    exterior = ring
                else:
                    holes.append(ring)
            if exterior:
                try:
                    p = Polygon(exterior, holes)
                    if p.is_valid and p.area > 3.0:
                        polygons.append(p)
                except Exception:
                    pass
        if not polygons:
            continue
        geom = polygons[0] if len(polygons) == 1 else MultiPolygon(polygons)
        bid = ""
        for k, v in feature.attrib.items():
            if k.endswith("}id"):
                bid = v
                break
        buildings.append({"id": bid, "geometry": geom})
    return buildings


def fetch_egib_buildings(bbox):
    cfg = CFG["services"]["egib_wfs"]
    minx, miny, maxx, maxy = bbox
    # Oficjalny klient GUGiK stosuje w GML 3.2 kolejność osi Y X dla EPSG:2180.
    filter_xml = (
        '<fes:Filter xmlns:fes="http://www.opengis.net/fes/2.0" '
        'xmlns:gml="http://www.opengis.net/gml/3.2">'
        '<fes:BBOX><fes:ValueReference>geom</fes:ValueReference>'
        '<gml:Envelope srsName="EPSG:2180">'
        f'<gml:lowerCorner>{miny:.3f} {minx:.3f}</gml:lowerCorner>'
        f'<gml:upperCorner>{maxy:.3f} {maxx:.3f}</gml:upperCorner>'
        '</gml:Envelope></fes:BBOX></fes:Filter>'
    )
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typenames": cfg.get("typename", "ms:budynki"),
        "filter": filter_xml,
        "count": str(int(CFG["fetch"].get("context_building_max_count", 250)) + 100),
    }
    r = request_get(cfg["url"], params=params, timeout=180, attempts=4)
    r.raise_for_status()
    buildings = parse_egib_buildings_gml(r.content)
    return buildings, {
        "service": cfg["url"],
        "typename": cfg.get("typename", "ms:budynki"),
        "features": len(buildings),
        "bytes": len(r.content),
    }


def house_footprint_epsg2180():
    pts = [model_to_epsg2180(float(x), float(y)) for x, y in MODEL_DATA["facade_reference_outline"]["polygon_mm"]]
    return Polygon(pts)


def polygon_grid_values(poly, arr, transform, nodata=None):
    mask = geometry_mask([mapping(poly)], out_shape=arr.shape, transform=transform, invert=True, all_touched=True)
    vals = np.asarray(arr)[mask].astype(float)
    valid = np.isfinite(vals)
    if nodata is not None:
        valid &= np.abs(vals - float(nodata)) > 1e-5
    return vals[valid]


def build_context_buildings(buildings, nmt_arr, nmpt_arr, transform, nmt_nodata, zero_m, center_en, ortho_img, ortho_bbox):
    house = house_footprint_epsg2180().buffer(1.0)
    candidates = []
    for rec in buildings:
        geom = rec["geometry"]
        if geom.is_empty or geom.area < 8:
            continue
        if geom.intersection(house).area > 4:
            continue
        c = geom.centroid
        dist = math.hypot(c.x - center_en[0], c.y - center_en[1])
        candidates.append((dist, rec))
    candidates.sort(key=lambda x: x[0])
    candidates = candidates[:int(CFG["fetch"].get("context_building_max_count", 250))]

    parts=[]; heights=[]; accepted_geoms=[]
    for bi,(_,rec) in enumerate(candidates,1):
        geom=rec["geometry"]
        pieces=[geom] if isinstance(geom,Polygon) else list(geom.geoms)
        nmt_vals=polygon_grid_values(geom,nmt_arr,transform,nmt_nodata)
        if len(nmt_vals)==0: continue
        base_abs=float(np.nanpercentile(nmt_vals,10))
        total_h=None
        if nmpt_arr is not None:
            nmpt_vals=polygon_grid_values(geom,nmpt_arr,transform,None)
            if len(nmpt_vals):
                roof_abs=float(np.nanpercentile(nmpt_vals,75))
                candidate_h=roof_abs-base_abs
                if 2.5 < candidate_h < 35:
                    total_h=candidate_h
        if total_h is None or not math.isfinite(total_h):
            total_h=6.0
        total_h=float(np.clip(total_h,3.0,30.0))
        eave_h=float(np.clip(total_h*0.64,2.8,max(total_h-1.0,2.8)))
        body_meshes=[]
        for p in pieces:
            ext=[epsg2180_to_model(float(e),float(n)) for e,n in p.exterior.coords]
            holes=[[epsg2180_to_model(float(e),float(n)) for e,n in ring.coords] for ring in p.interiors]
            lp=Polygon([(x/1000.0,y/1000.0) for x,y in ext],
                       [[(x/1000.0,y/1000.0) for x,y in ring] for ring in holes])
            if not lp.is_valid or lp.area<2: continue
            try:
                m=trimesh.creation.extrude_polygon(lp,height=eave_h,engine="earcut")
            except Exception:
                continue
            m.apply_translation([0,0,base_abs-zero_m])
            body_meshes.append(m)
        if body_meshes:
            bm=trimesh.util.concatenate(body_meshes)
            parts.append({"name":f"GEO_BUDYNEK_SCIANY_{bi:03d}","category":"budynki_otoczenia","material":"budynki_otoczenia",
                "color":[0.73,0.71,0.67,1.0],"source":"Geoportal / EGiB","source_id":"GEO_BUILDINGS","assumed":False,
                "note":"Ściany budynku sąsiedniego: obrys EGiB; wysokość okapu z NMPT-NMT lub fallback.",
                "positions_m":np.round(bm.vertices,6).tolist(),"faces":bm.faces.tolist(),"reference_area_m2":round(float(geom.area),2)})
            roof=make_gable_roof_part(geom,base_abs-zero_m,total_h,ortho_img,ortho_bbox,bi)
            if roof: parts.append(roof)
            accepted_geoms.append(geom); heights.append(total_h)

    return parts,accepted_geoms,{"count":len(accepted_geoms),
        "median_height_m":round(float(np.median(heights)),2) if heights else None,
        "max_height_m":round(float(max(heights)),2) if heights else None}


def make_tree_mesh(x, y, ground_z, h, crown_radius):
    trunk_h = min(max(h * 0.32, 1.5), 4.5)
    trunk_r = min(max(h * 0.022, 0.10), 0.32)
    trunk = trimesh.creation.cylinder(radius=trunk_r, height=trunk_h, sections=6)
    trunk.apply_translation([x, y, ground_z + trunk_h / 2])
    crown_h = max(h - trunk_h * 0.45, 2.0)
    crown = trimesh.creation.icosphere(subdivisions=1, radius=1.0)
    crown.apply_scale([crown_radius, crown_radius, crown_h * 0.5])
    crown.apply_translation([x, y, ground_z + h - crown_h * 0.5])
    return trunk, crown


def build_context_trees(nmt_arr, nmpt_arr, transform, nmt_nodata, building_geoms, zero_m):
    if nmpt_arr is None:
        return [], {"count":0, "reason":"brak NMPT"}
    chm = np.asarray(nmpt_arr, dtype=float) - np.asarray(nmt_arr, dtype=float)
    valid = np.isfinite(chm) & np.isfinite(nmt_arr) & (np.asarray(nmt_arr) > 100)
    threshold = float(CFG["fetch"].get("tree_min_height_m", 3.5))

    mask_buildings = np.zeros(chm.shape, dtype=bool)
    house = house_footprint_epsg2180()
    geoms = list(building_geoms) + [house]
    if geoms:
        mask_buildings = geometry_mask(
            [mapping(g) for g in geoms],
            out_shape=chm.shape,
            transform=transform,
            invert=True,
            all_touched=True,
        )
    candidate = valid & (chm >= threshold) & (~mask_buildings)

    candidates = []
    # local maxima in a 5x5 window on the NMT grid
    for r in range(2, chm.shape[0]-2):
        for c in range(2, chm.shape[1]-2):
            if not candidate[r,c]:
                continue
            h = float(chm[r,c])
            if h + 1e-6 < float(np.nanmax(chm[r-2:r+3,c-2:c+3])):
                continue
            e,n = rasterio.transform.xy(transform, r, c, offset="center")
            candidates.append((h,float(e),float(n),r,c))
    candidates.sort(reverse=True)

    spacing = float(CFG["fetch"].get("tree_min_spacing_m", 5.0))
    max_count = int(CFG["fetch"].get("tree_max_count", 180))
    selected = []
    for item in candidates:
        _,e,n,_,_ = item
        if any((e-e2)**2 + (n-n2)**2 < spacing**2 for _,e2,n2,_,_ in selected):
            continue
        selected.append(item)
        if len(selected) >= max_count:
            break

    trunks=[]; crowns=[]; heights=[]
    factor=float(CFG["fetch"].get("tree_crown_radius_factor",0.22))
    for h,e,n,r,c in selected:
        h=float(np.clip(h,threshold,24.0))
        ground=float(nmt_arr[r,c])-zero_m
        x_mm,y_mm=epsg2180_to_model(e,n)
        radius=float(np.clip(h*factor,1.1,4.2))
        trunk,crown=make_tree_mesh(x_mm/1000.0,y_mm/1000.0,ground,h,radius)
        trunks.append(trunk); crowns.append(crown); heights.append(h)

    parts=[]
    if trunks:
        tm=trimesh.util.concatenate(trunks)
        parts.append({
            "name":"GEO_DRZEWA_PNIE","category":"drzewa","material":"drzewa_pnie",
            "color":[0.28,0.18,0.10,1.0],"source":"Geoportal / NMPT-NMT",
            "source_id":"GEO_TREES","assumed":True,
            "note":"Pnie drzew są proceduralnym proxy; pozycje i wysokości koron wynikają z lokalnych maksimów NMPT-NMT.",
            "positions_m":np.round(tm.vertices,6).tolist(),"faces":tm.faces.tolist(),"reference_area_m2":None,
        })
        cm=trimesh.util.concatenate(crowns)
        parts.append({
            "name":"GEO_DRZEWA_KORONY","category":"drzewa","material":"drzewa_korony",
            "color":[0.22,0.43,0.16,1.0],"source":"Geoportal / NMPT-NMT",
            "source_id":"GEO_TREES","assumed":True,
            "note":"Korony drzew są niskopoligonową wizualizacją wysokościowego modelu pokrycia terenu.",
            "positions_m":np.round(cm.vertices,6).tolist(),"faces":cm.faces.tolist(),"reference_area_m2":None,
        })
    return parts, {
        "count":len(selected),
        "median_height_m":round(float(np.median(heights)),2) if heights else None,
        "max_height_m":round(float(max(heights)),2) if heights else None,
        "threshold_m":threshold,
    }


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



def build_ortho_surface(terrain):
    """Jedna powierzchnia ortofoto zgodna 1:1 z meshem NMT; tekstura jest nakładana w HTML."""
    verts = [[float(x), float(y), float(z) + 0.025] for x,y,z in terrain["positions_m"]]
    return [{
        "name":"GEO_ORTHO_TEXTURED",
        "category":"ortofoto",
        "material":"ortofoto",
        "color":[1.0,1.0,1.0,1.0],
        "source":"Geoportal / GUGiK ortofotomapa",
        "source_id":"GEO_ORTHO",
        "assumed":False,
        "note":"Rzeczywista ortofotomapa jest teksturowana na powierzchni NMT w podglądzie HTML.",
        "texture":"geoportal_ortho",
        "positions_m":verts,
        "faces":terrain["faces"],
        "reference_area_m2":terrain.get("reference_area_m2"),
    }]


def make_gable_roof_part(poly, base_abs, total_h, ortho_img, ortho_bbox, idx):
    rect = poly.minimum_rotated_rectangle
    coords = list(rect.exterior.coords)[:-1]
    if len(coords) != 4:
        return None
    q = [np.asarray(p, dtype=float) for p in coords]
    l01=float(np.linalg.norm(q[1]-q[0])); l12=float(np.linalg.norm(q[2]-q[1]))
    if l01 < l12:
        q=[q[1],q[2],q[3],q[0]]
    r0=(q[0]+q[3])/2; r1=(q[1]+q[2])/2
    eave_h=float(np.clip(total_h*0.64,2.8,max(total_h-1.0,2.8)))
    ridge_h=float(max(total_h,eave_h+1.0))
    pts_2180=[q[0],q[1],q[2],q[3],r0,r1]
    pts=[]
    for e,n in pts_2180:
        x_mm,y_mm=epsg2180_to_model(float(e),float(n))
        pts.append([x_mm/1000.0,y_mm/1000.0,0.0])
    for i in range(4): pts[i][2]=base_abs + eave_h
    pts[4][2]=base_abs + ridge_h; pts[5][2]=base_abs + ridge_h
    faces=[[0,1,5],[0,5,4],[3,4,5],[3,5,2],[0,4,3],[1,2,5]]
    c=poly.centroid
    col=sample_image_rgb(np.asarray(ortho_img),ortho_bbox,float(c.x),float(c.y))
    col=[round(min(max(v*0.95,0),1),4) for v in col[:3]]+[1.0]
    return {
        "name":f"GEO_BUDYNEK_DACH_{idx:03d}",
        "category":"budynki_otoczenia",
        "material":"budynki_dachy",
        "color":col,
        "source":"Geoportal / EGiB + ortofotomapa",
        "source_id":"GEO_BUILDINGS",
        "assumed":True,
        "note":"Uproszczony dach dwuspadowy; obrys z EGiB, kolor z ortofotomapy, wysokość z NMPT-NMT lub fallback.",
        "positions_m":pts,
        "faces":faces,
        "reference_area_m2":round(float(poly.area),2),
    }


def build_context_trees_from_ortho(img, bbox, nmt_arr, transform, nmt_nodata, building_geoms, zero_m):
    """Fallback, gdy NMPT nie jest dostępny: pozycje z ciemnozielonych skupisk ortofoto, wysokości orientacyjne."""
    minx,miny,maxx,maxy=bbox
    arr=np.asarray(img.resize((240,240),Image.BILINEAR)).astype(float)/255.0
    h,w=arr.shape[:2]
    score_grid=np.full((h,w),-999.0,dtype=float)
    for r in range(h):
        for c in range(w):
            rr,gg,bb=arr[r,c]
            bright=(rr+gg+bb)/3
            green=gg-0.5*(rr+bb)
            if gg>rr*1.03 and gg>bb*0.95 and green>0.035 and bright<0.62:
                score_grid[r,c]=green+(0.62-bright)*0.35
    candidates=[]
    for r in range(2,h-2):
        for c in range(2,w-2):
            sc=score_grid[r,c]
            if sc<0: continue
            if sc+1e-9 < np.max(score_grid[r-2:r+3,c-2:c+3]): continue
            e=minx+(c+0.5)/w*(maxx-minx)
            n=maxy-(r+0.5)/h*(maxy-miny)
            p=Point(e,n)
            if any(g.contains(p) for g in building_geoms):
                continue
            candidates.append((float(sc),e,n))
    candidates.sort(reverse=True)
    spacing=float(CFG["fetch"].get("tree_min_spacing_m",5.0))
    max_count=int(CFG["fetch"].get("tree_max_count",180))
    selected=[]
    for sc,e,n in candidates:
        if any((e-e2)**2+(n-n2)**2<spacing**2 for _,e2,n2 in selected): continue
        selected.append((sc,e,n))
        if len(selected)>=max_count: break

    trunks=[];crowns=[];heights=[]
    for sc,e,n in selected:
        ground=raster_value(nmt_arr,transform,nmt_nodata,e,n)
        if ground is None: continue
        height=float(np.clip(6.0+sc*18.0,5.0,14.0))
        x_mm,y_mm=epsg2180_to_model(e,n)
        radius=float(np.clip(height*0.24,1.2,3.8))
        trunk,crown=make_tree_mesh(x_mm/1000.0,y_mm/1000.0,ground-zero_m,height,radius)
        trunks.append(trunk);crowns.append(crown);heights.append(height)
    parts=[]
    if trunks:
        tm=trimesh.util.concatenate(trunks); cm=trimesh.util.concatenate(crowns)
        parts.append({"name":"GEO_DRZEWA_PNIE","category":"drzewa","material":"drzewa_pnie","color":[0.28,0.18,0.10,1.0],
            "source":"Geoportal / ortofotomapa + NMT","source_id":"GEO_TREES","assumed":True,
            "note":"Fallback: pozycje drzew estymowane z ciemnozielonych skupisk ortofotomapy; wysokości orientacyjne.",
            "positions_m":np.round(tm.vertices,6).tolist(),"faces":tm.faces.tolist(),"reference_area_m2":None})
        parts.append({"name":"GEO_DRZEWA_KORONY","category":"drzewa","material":"drzewa_korony","color":[0.20,0.40,0.14,1.0],
            "source":"Geoportal / ortofotomapa + NMT","source_id":"GEO_TREES","assumed":True,
            "note":"Fallback: uproszczone korony z ortofotomapy, nie inwentaryzacja dendrologiczna.",
            "positions_m":np.round(cm.vertices,6).tolist(),"faces":cm.faces.tolist(),"reference_area_m2":None})
    return parts,{"count":len(heights),"median_height_m":round(float(np.median(heights)),2) if heights else None,
                  "max_height_m":round(float(max(heights)),2) if heights else None,"source":"ortho_fallback"}


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
    nmpt_holder = None
    try:
        print(
            f"NMT EVRF: {arr.shape[1]}x{arr.shape[0]}, "
            f"res={nmt_meta['source_resolution_m']} m, downloads={len(nmt_meta['downloads'])}"
        )
        terrain = build_terrain_part(arr, transform, nodata, zero_m)

        nmpt_aligned = None
        nmpt_meta = None
        try:
            nmpt_arr, nmpt_transform, nmpt_nodata, nmpt_meta, nmpt_holder = fetch_nmpt_evrf(bbox)
            nmpt_aligned = align_raster_to_nmt(
                nmpt_arr, nmpt_transform, nmpt_nodata, arr.shape, transform
            )
            print(
                f"NMPT EVRF: {nmpt_arr.shape[1]}x{nmpt_arr.shape[0]}, "
                f"res={nmpt_meta['source_resolution_m']} m"
            )
        except Exception as exc:
            print(f"UWAGA: NMPT niedostępny, pomijam drzewa/wysokości kontekstu: {exc}")

        ortho_img, ortho_url, ortho_attempts = fetch_orthophoto(bbox)
        ortho_img.save(ROOT / "geoportal_ortho.jpg", format="JPEG", quality=92, optimize=True)
        ortho_parts = build_ortho_surface(terrain)

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

        building_records = []
        building_parts = []
        building_geoms = []
        building_stats = {"count":0}
        try:
            building_records, building_meta = fetch_egib_buildings(bbox)
            building_parts, building_geoms, building_stats = build_context_buildings(
                building_records, arr, nmpt_aligned, transform, nodata, zero_m, (cx,cy), ortho_img, bbox
            )
            building_meta["rendered"] = building_stats.get("count",0)
        except Exception as exc:
            building_meta = {"service":CFG["services"]["egib_wfs"]["url"],"error":repr(exc)}
            print(f"UWAGA: EGiB budynki niedostępne: {exc}")

        if nmpt_aligned is not None:
            tree_parts, tree_stats = build_context_trees(
                arr, nmpt_aligned, transform, nodata, building_geoms, zero_m
            )
        else:
            tree_parts, tree_stats = build_context_trees_from_ortho(
                ortho_img, bbox, arr, transform, nodata, building_geoms, zero_m
            )

        result = {
            "status": "fetched",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "source": {
                "nmt": nmt_meta,
                "nmpt": nmpt_meta,
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
                "buildings": building_meta,
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
                "context_buildings": building_stats.get("count",0),
                "context_building_median_height_m": building_stats.get("median_height_m"),
                "trees": tree_stats.get("count",0),
                "tree_median_height_m": tree_stats.get("median_height_m"),
                "tree_max_height_m": tree_stats.get("max_height_m"),
            },
            "parts": [terrain] + ortho_parts + parcel_parts + building_parts + tree_parts,
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
        if nmpt_holder is not None:
            nmpt_holder.cleanup()


if __name__ == "__main__":
    main()
