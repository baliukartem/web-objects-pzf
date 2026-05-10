"""
Кінцевий пайплайн збірки даних:

  1. Конвертує Rayon.shp + OTG.shp у GeoJSON (WGS84)
  2. Парсить офіційний PDF переліку ПЗФ
  3. Привʼязує кожен обʼєкт до нового району та ОТГ
  4. Розкладає кожен обʼєкт на унікальну точку всередині свого ОТГ
     (детермінований seed: ім’я + №)
  5. Записує assets/data/{pzf.json, rayons.geojson, otgs.geojson}

Запуск:
    pip install pdfplumber
    python3 scripts/build_data.py
"""
import hashlib
import json
import os
import random
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

from shp_parser import shp_to_geojson, fix_latin_lookalikes  # noqa: E402
from pdf_parser import parse_pdf, refine_category, normalize_type  # noqa: E402

SOURCE = ROOT / 'source'
DATA   = ROOT / 'assets' / 'data'

PDF_FILE = SOURCE / 'Perelik PZF 01.01.2025 .pdf'


# ---------- Geometry helpers ----------
def point_in_ring(x, y, ring):
    inside, n, j = False, len(ring), len(ring) - 1
    for i in range(n):
        xi, yi = ring[i]; xj, yj = ring[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-15) + xi):
            inside = not inside
        j = i
    return inside


def point_in_geom(x, y, geom):
    if geom['type'] == 'Polygon':
        if not point_in_ring(x, y, geom['coordinates'][0]):
            return False
        for hole in geom['coordinates'][1:]:
            if point_in_ring(x, y, hole):
                return False
        return True
    elif geom['type'] == 'MultiPolygon':
        for poly in geom['coordinates']:
            if not point_in_ring(x, y, poly[0]):
                continue
            ok = True
            for hole in poly[1:]:
                if point_in_ring(x, y, hole):
                    ok = False; break
            if ok:
                return True
    return False


def bbox(geom):
    xs, ys = [], []
    polys = [geom['coordinates']] if geom['type'] == 'Polygon' else geom['coordinates']
    for poly in polys:
        for ring in poly:
            for p in ring:
                xs.append(p[0]); ys.append(p[1])
    return min(xs), min(ys), max(xs), max(ys)


def deterministic_point(geom, seed_str, max_tries=400):
    """Детермінована точка всередині полігону за хешем seed_str."""
    minx, miny, maxx, maxy = bbox(geom)
    seed = int(hashlib.md5(seed_str.encode('utf-8')).hexdigest(), 16) & 0xffffffff
    rng = random.Random(seed)
    for _ in range(max_tries):
        x, y = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
        if point_in_geom(x, y, geom):
            return [round(x, 5), round(y, 5)]
    polys = [geom['coordinates']] if geom['type'] == 'Polygon' else geom['coordinates']
    pts = [p for poly in polys for ring in poly for p in ring]
    return [round(sum(p[0] for p in pts) / len(pts), 5),
            round(sum(p[1] for p in pts) / len(pts), 5)]


# ---------- Matching ----------
def normalize(s):
    if not s: return ''
    s = s.lower()
    s = re.sub(r'\s*-\s*', '-', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def match_admin(records, rayons_gj, otgs_gj):
    """Привʼязати кожен запис до району та ОТГ за полем location."""
    # Rayon index
    rayons = [{'id': f['properties']['id'],
               'name': f['properties']['admin_ua'],
               'norm': normalize(f['properties']['admin_ua'].replace(' район', '').strip())}
              for f in rayons_gj['features']]
    rayons.sort(key=lambda x: -len(x['norm']))

    # OTG index — base = stem (drop trailing 'а' or 'я')
    otgs = []
    for f in otgs_gj['features']:
        p = f['properties']
        n = p['ADMIN_3']
        nn = normalize(n)
        base = nn[:-1] if nn[-1:] in 'ая' else nn
        otgs.append({'id': p['id'], 'name': n, 'norm': nn,
                     'base': base, 'rayon': p['ADMIN_2']})
    otgs.sort(key=lambda x: -len(x['base']))

    matched_r = matched_o = 0
    for r in records:
        loc = normalize(r.get('location') or '')

        # Район
        rid = rname = None
        for ry in rayons:
            if ry['norm'] in loc:
                rid, rname = ry['id'], ry['name']; break
        r['rayon_id'] = rid
        r['rayon_name'] = rname
        if rid is not None:
            matched_r += 1

        # ОТГ — пріоритет: повна форма (адʼєктив + 'територіальна громада')
        candidates = []
        for o in otgs:
            pat = rf'\b{re.escape(o["base"])}(а|у|ої|ого|ому|ою|ій|им|их|ім)?\s+(сільськ|селищн|міськ)'
            if re.search(pat, loc):
                candidates.append((len(o['base']), o))
        if not candidates:
            for o in otgs:
                if o['norm'] in loc:
                    candidates.append((len(o['norm']), o))
        if not candidates:
            for o in otgs:
                if len(o['base']) > 4 and o['base'] in loc:
                    candidates.append((len(o['base']), o))

        if candidates:
            in_rayon = [c for c in candidates if c[1]['rayon'] == rname] if rname else []
            chosen = (in_rayon or candidates)
            chosen.sort(key=lambda c: -c[0])
            r['otg_id']   = chosen[0][1]['id']
            r['otg_name'] = chosen[0][1]['name']
            matched_o += 1
        else:
            r['otg_id'] = None
            r['otg_name'] = None

    print(f"  Matched rayons: {matched_r}/{len(records)}")
    print(f"  Matched OTGs:   {matched_o}/{len(records)}")


def place_coords(records, rayons_gj, otgs_gj):
    otg_geom   = {f['properties']['id']: f['geometry'] for f in otgs_gj['features']}
    rayon_geom = {f['properties']['id']: f['geometry'] for f in rayons_gj['features']}

    for r in records:
        seed = f"{r['name']}_{r.get('num','')}_{r.get('category','')}"
        if r.get('otg_id') is not None and r['otg_id'] in otg_geom:
            pt = deterministic_point(otg_geom[r['otg_id']], seed)
            r['lon'], r['lat'] = pt
            r['coord_source'] = 'otg-distributed'
        elif r.get('rayon_id') is not None and r['rayon_id'] in rayon_geom:
            pt = deterministic_point(rayon_geom[r['rayon_id']], seed)
            r['lon'], r['lat'] = pt
            r['coord_source'] = 'rayon-distributed'
        else:
            r['lat'] = r['lon'] = None
            r['coord_source'] = None


def main():
    DATA.mkdir(parents=True, exist_ok=True)

    # 1) Shapefiles → GeoJSON
    print("[1/4] Converting shapefiles to GeoJSON…")
    rayons_gj = shp_to_geojson(SOURCE / 'Rayon.shp', SOURCE / 'Rayon.dbf')
    otgs_gj   = shp_to_geojson(SOURCE / 'OTG.shp',   SOURCE / 'OTG.dbf')

    # Clean up Latin lookalikes in OTG names; assign sequential IDs.
    for i, feat in enumerate(otgs_gj['features']):
        p = feat['properties']
        feat['id'] = i
        p['id'] = i
        p['ADMIN_1'] = fix_latin_lookalikes(p.get('ADMIN_1'))
        p['ADMIN_2'] = fix_latin_lookalikes(p.get('ADMIN_2'))
        p['ADMIN_3'] = fix_latin_lookalikes(p.get('ADMIN_3'))
        p['TYPE']    = fix_latin_lookalikes(p.get('TYPE'))

    with open(DATA / 'rayons.geojson', 'w', encoding='utf-8') as f:
        json.dump(rayons_gj, f, ensure_ascii=False, separators=(',', ':'))
    with open(DATA / 'otgs.geojson', 'w', encoding='utf-8') as f:
        json.dump(otgs_gj, f, ensure_ascii=False, separators=(',', ':'))
    print(f"  Wrote {len(rayons_gj['features'])} rayons, {len(otgs_gj['features'])} OTGs")

    # 2) Parse PDF
    print("[2/4] Parsing official PDF list…")
    records = parse_pdf(str(PDF_FILE))
    for r in records:
        r['category'] = refine_category(r)
        r['type_normalized'] = normalize_type(r.get('type'))
    print(f"  Got {len(records)} records")
    print("  By category:")
    for k, v in Counter((r['significance'], r['category']) for r in records).most_common():
        print(f"    {k}: {v}")

    # 3) Admin matching
    print("[3/4] Matching to new rayons + OTGs…")
    match_admin(records, rayons_gj, otgs_gj)

    # 4) Coordinate placement
    print("[4/4] Distributing coordinates inside polygons…")
    place_coords(records, rayons_gj, otgs_gj)

    # Compose final pzf.json
    out = {
        'records': records,
        'rayons': [{'id': f['properties']['id'],
                    'name': f['properties']['admin_ua'],
                    'koatuu': f['properties'].get('koatuu')} for f in rayons_gj['features']],
        'otgs': [{'id': f['properties']['id'],
                  'name': f['properties']['ADMIN_3'],
                  'type': f['properties']['TYPE'],
                  'rayon': f['properties']['ADMIN_2'],
                  'koatuu_old': f['properties'].get('KOATUU_old')}
                 for f in otgs_gj['features']],
        'totals_official': {'objects': 434, 'area_ha': 66807.2253, 'effective_area_ha': 60245.6753},
    }
    with open(DATA / 'pzf.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    print(f"\nDone. {len(records)} records → {DATA / 'pzf.json'}")
    print(f"     ({os.path.getsize(DATA / 'pzf.json')} bytes)")


if __name__ == '__main__':
    main()
