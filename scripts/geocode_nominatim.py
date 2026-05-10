"""
Розширене геокодування для точних координат ПЗФ.

Стратегія:
1. OSM розселення + ліси (вже в pzf.json як 'osm-settlement', 'osm-forest')
2. Nominatim: пошук за повною назвою об'єкта у Вінницькій області
3. Nominatim: пошук за улюбленими населеними пунктами з локації
4. Fallback: центроїд ОТГ

Запуск:
    python3 scripts/geocode_nominatim.py
"""
import json
import re
import time
from pathlib import Path
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'assets' / 'data'

# Nominatim з затримкою для лімітів
geocoder = Nominatim(
    user_agent='pzf_geocoder_vinnytsia',
    timeout=10
)

# Кеш результатів
cache = {}

def normalize(s):
    """Нормалізація тексту для порівняння."""
    if not s:
        return ''
    s = s.lower()
    s = re.sub(r'[ьїєґ]', lambda m: {'ь': '', 'ї': 'и', 'є': 'e', 'ґ': 'г'}.get(m.group(0)), s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def geocode_place(name, location_hint='Вінницька область, Україна', attempt=1):
    """
    Геокодування з Nominatim.
    
    Args:
        name: назва об'єкта
        location_hint: регіон для звуження пошуку
        attempt: номер спроби (для retry)
    
    Returns:
        (lat, lon) або None
    """
    if not name:
        return None
    
    cache_key = normalize(name)
    if cache_key in cache:
        return cache[cache_key]
    
    # Спробуємо точний пошук у регіоні
    query = f'{name}, {location_hint}'
    
    try:
        print(f"    → Nominatim: {query[:60]}…", end=' ', flush=True)
        loc = geocoder.geocode(query, language='uk', timeout=10)
        
        if loc:
            result = (round(loc.latitude, 5), round(loc.longitude, 5))
            print(f"OK")
            cache[cache_key] = result
            return result
        else:
            print(f"not found")
            
    except (GeocoderTimedOut, GeocoderServiceError) as e:
        print(f"error: {e}")
        if attempt < 3:
            time.sleep(2)
            return geocode_place(name, location_hint, attempt + 1)
    
    cache[cache_key] = None
    return None

def extract_main_location(location_str):
    """
    Витягнути главну географічну назву з локації.
    
    Приклади:
    "Кармелюкове Поділля, смт Липовець" → "Липовець"
    "с. Кутузівка, Озерянське ОТГ" → "Кутузівка"
    """
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
    
    if otg_path.exists():
        otgs_gj = json.loads(otg_path.read_text(encoding='utf-8'))
        otg_centers = {}
        for feat in otgs_gj['features']:
            oid = feat['properties']['id']
            geom = feat['geometry']
            if geom['type'] == 'Polygon':
                coords = geom['coordinates'][0]
                avg_lon = sum(c[0] for c in coords) / len(coords)
                avg_lat = sum(c[1] for c in coords) / len(coords)
                otg_centers[oid] = (avg_lat, avg_lon)
    else:
        otg_centers = {}
    
    # Статистика
    already_precise = 0
    nominatim_found = 0
    fallback_used = 0
    no_coords = 0
    
    print("[Geocoding with Nominatim]\n")
    
    for i, r in enumerate(pzf['records']):
        # Пропускаємо вже точні
        if r.get('coord_source', '').startswith('osm-'):
            already_precise += 1
            continue
        
        name = r.get('name', '')
        location = r.get('location', '')
        otg_id = r.get('otg_id')
        
        print(f"  {i+1:3d}. {name[:40]:40s}", end=' ', flush=True)
        
        # 1) Пошук за повною назвою
        coords = geocode_place(name, 'Вінницька область')
        
        # 2) Пошук за локацією
        if not coords and location:
            main_loc = extract_main_location(location)
            if main_loc and main_loc != name:
                coords = geocode_place(main_loc, 'Вінницька область')
        
        if coords:
            r['lat'], r['lon'] = coords
            r['coord_source'] = 'nominatim'
            print(f"✓ Nominatim")
            nominatim_found += 1
            time.sleep(1)  # Throttle для Nominatim
        elif otg_id is not None and otg_id in otg_centers:
            r['lat'], r['lon'] = otg_centers[otg_id]
            r['coord_source'] = 'otg-center'
            print(f"→ OTG center")
            fallback_used += 1
        else:
            print(f"✗ No coords")
            no_coords += 1
    
    print(f"\n[Results]")
    print(f"  Already precise (OSM):  {already_precise}")
    print(f"  Nominatim found:        {nominatim_found}")
    print(f"  Fallback (OTG center):  {fallback_used}")
    print(f"  No coordinates:         {no_coords}")
    print(f"  Total precise:          {already_precise + nominatim_found + fallback_used}")
    
    pzf_path.write_text(
        json.dumps(pzf, ensure_ascii=False, separators=(',', ':')),
        encoding='utf-8'
    )
    print(f"\nUpdated {pzf_path}")

if __name__ == '__main__':
    main()
