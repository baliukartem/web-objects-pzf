"""
Фінальне геокодування з кешем для точних координат ПЗФ.

Стратегія:
1. Використовуємо кеш з попередніх запусків
2. Nominatim тільки для нових об'єктів
3. Fallback на центроїди ОТГ

Запуск:
    python3 scripts/geocode_final.py
"""
import json
import re
import time
from pathlib import Path
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError, GeocoderRateLimited

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'assets' / 'data'

# Nominatim з більшими затримками
geocoder = Nominatim(
    user_agent='pzf_geocoder_vinnytsia_final',
    timeout=15
)

def load_cache():
    """Завантажуємо кеш координат."""
    cache_file = DATA / 'geocode_cache.json'
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding='utf-8'))
    return {}

def save_cache(cache):
    """Зберігаємо кеш."""
    cache_file = DATA / 'geocode_cache.json'
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, separators=(',', ':'))

def normalize(s):
    """Нормалізація тексту."""
    if not s:
        return ''
    s = s.lower()
    s = re.sub(r'[ьїєґ]', lambda m: {'ь': '', 'ї': 'и', 'є': 'e', 'ґ': 'г'}.get(m.group(0)), s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def geocode_place(name, location_hint='Вінницька область, Україна'):
    """
    Геокодування з Nominatim з кешем.
    """
    if not name:
        return None
    
    cache_key = normalize(name)
    cache = load_cache()
    
    if cache_key in cache:
        return cache[cache_key]
    
    query = f'{name}, {location_hint}'
    
    try:
        print(f"    → Nominatim: {query[:50]}…", end=' ', flush=True)
        loc = geocoder.geocode(query, language='uk', timeout=15)
        
        if loc:
            result = (round(loc.latitude, 5), round(loc.longitude, 5))
            print(f"OK")
            cache[cache_key] = result
            save_cache(cache)
            return result
        else:
            print(f"not found")
            
    except GeocoderRateLimited:
        print(f"rate limited, skipping")
        return None
    except (GeocoderTimedOut, GeocoderServiceError) as e:
        print(f"error: {e}")
    
    cache[cache_key] = None
    save_cache(cache)
    return None

def extract_main_location(location_str):
    """Витягнути главну географічну назву."""
    if not location_str:
        return None
    
    # Шукаємо назву села/міста/смт
    pat = r'(?:с\.|м\.|смт\.)\s*([А-ЯҐЄІЇа-яґєії][А-ЯҐЄІЇа-яґєії\'\-]+(?:\s[А-ЯҐЄІЇа-яґєії\'\-]+)?)'
    m = re.search(pat, location_str)
    if m:
        return m.group(1).strip()
    
    # Або перший капіталізований топонім
    parts = location_str.split(',')
    if parts:
        first = parts[0].strip()
        if first and first[0].isupper():
            return first
    
    return None

def main():
    print(f"Project root: {ROOT}\n")
    
    pzf_path = DATA / 'pzf.json'
    otg_path = DATA / 'otgs.geojson'
    
    if not pzf_path.exists():
        print(f"Error: {pzf_path} not found")
        return
    
    pzf = json.loads(pzf_path.read_text(encoding='utf-8'))
    
    # Завантажуємо центроїди ОТГ
    otg_centers = {}
    if otg_path.exists():
        otgs_gj = json.loads(otg_path.read_text(encoding='utf-8'))
        for feat in otgs_gj['features']:
            oid = feat['properties']['id']
            geom = feat['geometry']
            if geom['type'] == 'Polygon':
                coords = geom['coordinates'][0]
                avg_lon = sum(c[0] for c in coords) / len(coords)
                avg_lat = sum(c[1] for c in coords) / len(coords)
                otg_centers[oid] = (avg_lat, avg_lon)
    
    # Статистика
    already_precise = 0
    from_cache = 0
    nominatim_found = 0
    fallback_used = 0
    no_coords = 0
    
    print("[Final geocoding with cache]\n")
    
    cache = load_cache()
    
    for i, r in enumerate(pzf['records']):
        # Пропускаємо вже точні
        if r.get('coord_source', '').startswith('osm-'):
            already_precise += 1
            continue
        
        name = r.get('name', '')
        location = r.get('location', '')
        otg_id = r.get('otg_id')
        
        print(f"  {i+1:3d}. {name[:35]:35s}", end=' ', flush=True)
        
        coords = None
        
        # 1) Перевіряємо кеш
        if name in cache and cache[name]:
            coords = cache[name]
            print(f"✓ Cache")
            from_cache += 1
        
        # 2) Nominatim для нових
        if not coords:
            coords = geocode_place(name, 'Вінницька область')
            if coords:
                nominatim_found += 1
            else:
                # Спробуємо локацію
                main_loc = extract_main_location(location)
                if main_loc and main_loc != name:
                    coords = geocode_place(main_loc, 'Вінницька область')
                    if coords:
                        nominatim_found += 1
        
        # 3) Fallback на центроїд ОТГ
        if not coords and otg_id is not None and otg_id in otg_centers:
            coords = otg_centers[otg_id]
            print(f"→ OTG center")
            fallback_used += 1
        
        if coords:
            r['lat'], r['lon'] = coords
            if r.get('coord_source') != 'nominatim':
                r['coord_source'] = 'nominatim' if coords != otg_centers.get(otg_id) else 'otg-center'
        else:
            print(f"✗ No coords")
            no_coords += 1
        
        # Затримка між запитами
        if nominatim_found > 0 and nominatim_found % 5 == 0:
            time.sleep(2)
    
    print(f"\n[Results]")
    print(f"  Already precise (OSM):  {already_precise}")
    print(f"  From cache:             {from_cache}")
    print(f"  Nominatim found:        {nominatim_found}")
    print(f"  Fallback (OTG center):  {fallback_used}")
    print(f"  No coordinates:         {no_coords}")
    print(f"  Total precise:          {already_precise + from_cache + nominatim_found + fallback_used}")
    
    pzf_path.write_text(
        json.dumps(pzf, ensure_ascii=False, separators=(',', ':')),
        encoding='utf-8'
    )
    print(f"\nUpdated {pzf_path}")

if __name__ == '__main__':
    main()