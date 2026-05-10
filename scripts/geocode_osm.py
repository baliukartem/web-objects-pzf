import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import ssl
from pathlib import Path

# Вирішення проблеми з сертифікатами на macOS
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'assets' / 'data'

OVERPASS_ENDPOINTS = [
    os.environ.get('OVERPASS') or 'https://overpass-api.de/api/interpreter',
    'https://overpass.kumi.systems/api/interpreter',
    'https://overpass.openstreetmap.fr/api/interpreter',
]

# Вінницька область ISO-код 'UA-05'
PLACES_QUERY = """
[out:json][timeout:120];
area["ISO3166-2"="UA-05"]->.a;
(
  node["place"~"^(village|town|city|hamlet|suburb)$"](area.a);
);
out;
"""

# Для лісів теж важливо отримати геометрію
FOREST_QUERY = """
[out:json][timeout:120];
area["ISO3166-2"="UA-05"]->.a;
(
  way["landuse"="forest"]["name"](area.a);
  relation["landuse"="forest"]["name"](area.a);
  way["boundary"="forestry"]["name"](area.a);
  relation["boundary"="forestry"]["name"](area.a);
  node["landuse"="forest"]["name"](area.a);
);
out center tags;
"""

def fetch_overpass(query):
    """Спроба завантажити дані з декількох дзеркал Overpass API."""
    last_err = None
    # Обов'язкові заголовки для уникнення помилки 406
    headers = {
        'User-Agent': 'PZF_Geocoding_Script/1.1 (https://github.com/yourusername/pzf-vinnytsia)',
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    
    for url in OVERPASS_ENDPOINTS:
        if not url:
            continue
        try:
            print(f"  → {url}…", end=' ', flush=True)
            data = urllib.parse.urlencode({'data': query}).encode()
            req = urllib.request.Request(url, data=data, headers=headers, method='POST')
            
            with urllib.request.urlopen(req, timeout=180) as resp:
                payload = resp.read().decode('utf-8')
                print('OK')
                return json.loads(payload)
        except Exception as e:
            print(f'failed: {e}')
            last_err = e
            time.sleep(2)
    raise RuntimeError(f"All Overpass endpoints failed. Last error: {last_err}")

def fetch_settlements():
    print("Fetching settlements from OSM…")
    data = fetch_overpass(PLACES_QUERY)
    settlements = []
    for el in data.get('elements', []):
        tags = el.get('tags', {})
        name = tags.get('name')
        lat = el.get('lat')
        lon = el.get('lon')
        
        # Перевірка на наявність імені та координат (виправляє TypeError NoneType)
        if not name or lat is None or lon is None:
            continue
            
        settlements.append({
            'name': name,
            'name_alt': tags.get('alt_name') or tags.get('official_name'),
            'place': tags.get('place'),
            'lat': lat,
            'lon': lon,
        })
    print(f"  Got {len(settlements)} settlements")
    return settlements

def fetch_forests():
    print("Fetching forest names from OSM…")
    try:
        data = fetch_overpass(FOREST_QUERY)
    except Exception as e:
        print(f"  Forest fetch failed: {e}; skipping")
        return []
    forests = []
    for el in data.get('elements', []):
        tags = el.get('tags', {})
        name = tags.get('name')
        if not name:
            continue
            
        center = el.get('center') or {}
        lat = center.get('lat') or el.get('lat')
        lon = center.get('lon') or el.get('lon')
        
        if lat is not None and lon is not None:
            forests.append({'name': name, 'lat': lat, 'lon': lon})
            
    print(f"  Got {len(forests)} forests")
    return forests

def normalize(s):
    return re.sub(r'\s+', ' ', (s or '').lower()).strip()

def extract_villages(loc):
    if not loc: return []
    villages = []
    pat = r'(?:с\.|м\.|смт\.|сел\.)\s*([А-ЯҐЄІЇа-яґєії][А-ЯҐЄІЇа-яґєії\'\-]+(?:\s[А-ЯҐЄІЇа-яґєії\'\-]+)?)'
    for m in re.finditer(pat, loc):
        villages.append(m.group(1).strip(' ,;:.()"'))
    return villages

def extract_forest(loc):
    if not loc: return None
    m = re.search(r'([А-ЯҐЄІЇ][а-яґєії\'\-]+ське|[А-ЯҐЄІЇ][а-яґєії\'\-]+ьке)\s+лісництв', loc)
    if m:
        return m.group(1)
    return None

def point_in_ring(x, y, ring):
    inside, n, j = False, len(ring), len(ring) - 1
    for i in range(n):
        xi, yi = ring[i]; xj, yj = ring[j]
        # Додаткова безпека для координат
        if yi is None or y is None or yj is None: continue
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-15) + xi):
            inside = not inside
        j = i
    return inside

def point_in_geom(x, y, geom):
    if x is None or y is None: return False
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

def main():
    print(f"Project root: {ROOT}\n")

    # Перевірка наявності файлів перед завантаженням
    pzf_path = DATA / 'pzf.json'
    otg_path = DATA / 'otgs.geojson'
    
    if not pzf_path.exists() or not otg_path.exists():
        print(f"Error: Required data files not found in {DATA}")
        return

    pzf      = json.loads(pzf_path.read_text(encoding='utf-8'))
    otgs_gj  = json.loads(otg_path.read_text(encoding='utf-8'))
    otg_geom = {f['properties']['id']: f['geometry'] for f in otgs_gj['features']}

    # Завантаження OSM даних
    settlements = fetch_settlements()
    forests     = fetch_forests()

    # Збереження сирих даних
    (DATA / 'osm_settlements.json').write_text(
        json.dumps(settlements, ensure_ascii=False), encoding='utf-8')
    (DATA / 'osm_forests.json').write_text(
        json.dumps(forests, ensure_ascii=False), encoding='utf-8')

    # Індексація
    settle_idx = {}
    for s in settlements:
        for nm in (s['name'], s.get('name_alt')):
            if nm:
                settle_idx.setdefault(normalize(nm), []).append(s)
    
    forest_idx = {}
    for f in forests:
        forest_idx.setdefault(normalize(f['name']), []).append(f)

    matched_settlement = matched_forest = unchanged = 0
    
    for r in pzf['records']:
        loc = r.get('location') or ''
        otg_id = r.get('otg_id')
        bound = otg_geom.get(otg_id) if otg_id is not None else None
        chosen = None

        # 1) Лісництва
        forest_name = extract_forest(loc)
        if forest_name:
            norm_forest = normalize(forest_name)
            # Проходимо по всіх знайдених в OSM лісах і шукаємо частковий збіг назви
            for osm_name, cands in forest_idx.items():
                # Якщо назва з ПЗФ є в назві OSM (або навпаки)
                if norm_forest in osm_name or osm_name in norm_forest:
                    for c in cands:
                        if c.get('lat') is None: continue
                        if not bound or point_in_geom(c['lon'], c['lat'], bound):
                            chosen = (c['lat'], c['lon'], 'osm-forest')
                            break
                    if chosen: 
                        break

        # 2) Населені пункти
        if not chosen:
            for v in extract_villages(loc):
                cands = settle_idx.get(normalize(v), [])
                for c in cands:
                    if c.get('lat') is None: continue
                    if not bound or point_in_geom(c['lon'], c['lat'], bound):
                        chosen = (c['lat'], c['lon'], 'osm-settlement')
                        break
                if chosen:
                    break

        if chosen:
            r['lat'], r['lon'], r['coord_source'] = round(chosen[0], 5), round(chosen[1], 5), chosen[2]
            if chosen[2] == 'osm-forest':
                matched_forest += 1
            else:
                matched_settlement += 1
        else:
            unchanged += 1

    print(f"\nResults:")
    print(f"  Settlements matched: {matched_settlement}")
    print(f"  Forests matched:     {matched_forest}")
    print(f"  Unchanged (kept old): {unchanged}")

    pzf_path.write_text(
        json.dumps(pzf, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f"\nUpdated {pzf_path}")

if __name__ == '__main__':
    main()