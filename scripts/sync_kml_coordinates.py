#!/usr/bin/env python3
"""
Синхронізація координат ПЗФ з даними з файлу Zapov2.kml та створення повноцінної БД.

Цей скрипт:
1. Парсить KML файл з актуальними межами ПЗФ
2. Синхронізує координати з існуючою базою даних
3. Створює повноцінну базу даних з усіма ПЗФ

Запуск:
    python3 scripts/sync_kml_coordinates.py
"""
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'assets' / 'data'

def parse_kml_coordinates(coordinates_text: str) -> List[Tuple[float, float]]:
    """Парсить координати з KML формату."""
    coords = []
    for line in coordinates_text.strip().split():
        parts = line.split(',')
        if len(parts) >= 2:
            try:
                lon, lat = float(parts[0]), float(parts[1])
                coords.append((lon, lat))
            except ValueError:
                continue
    return coords

def parse_kml_description(description: str) -> Dict[str, str]:
    """Парсить опис ПЗФ з HTML формату."""
    data = {}
    # Видаляємо HTML теги та розбираємо рядки
    clean_desc = re.sub(r'<[^>]+>', '', description)
    lines = clean_desc.split('<br>')

    for line in lines:
        line = line.strip()
        if ':' in line:
            key, value = line.split(':', 1)
            key = key.strip()
            value = value.strip()

            # Мапінг ключів до стандартних назв
            key_mapping = {
                'СОБСТВЕН.НАЗВ.(ТЕКСТ ПОДПИСИ)': 'name',
                'Категорія об\'єкту': 'category',
                'Загальний реєстраційний №': 'reg_num',
                'Номер в категорії об\'єкта': 'category_num',
                'Площа, га': 'area_ha',
                'Код ПЗФ': 'pzf_code',
                'Код зв\'язку з базою даних': 'db_code'
            }

            if key in key_mapping:
                data[key_mapping[key]] = value

    return data

def calculate_centroid(coords: List[Tuple[float, float]]) -> Tuple[float, float]:
    """Обчислює центроїд полігону."""
    if not coords:
        return (0, 0)

    lon_sum = sum(lon for lon, lat in coords)
    lat_sum = sum(lat for lon, lat in coords)

    return (lon_sum / len(coords), lat_sum / len(coords))

def load_existing_data() -> Dict:
    """Завантажує існуючі дані з pzf.json."""
    pzf_file = DATA / 'pzf.json'
    if pzf_file.exists():
        with open(pzf_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'records': [], 'rayons': [], 'otgs': [], 'totals_official': {}}

def normalize_name(name: str) -> str:
    """Нормалізує назву для порівняння."""
    if not name:
        return ''
    # Видаляємо зайві символи, переводимо в нижній регістр
    name = re.sub(r'[^\w\s\u0400-\u04FF]', '', name.lower())
    return re.sub(r'\s+', ' ', name).strip()

def find_matching_record(kml_record: Dict, existing_records: List[Dict]) -> Optional[Dict]:
    """Шукає відповідний запис в існуючій базі даних."""
    kml_name = normalize_name(kml_record.get('name', ''))
    kml_code = kml_record.get('pzf_code')

    # Спочатку шукаємо за кодом ПЗФ
    if kml_code:
        for record in existing_records:
            if str(record.get('num', '')) == str(kml_code):
                return record

    # Потім шукаємо за назвою
    for record in existing_records:
        existing_name = normalize_name(record.get('name', ''))
        if existing_name == kml_name:
            return record

    return None

def parse_kml_file(kml_path: Path) -> List[Dict]:
    """Парсить KML файл та повертає список ПЗФ об'єктів."""
    tree = ET.parse(kml_path)
    root = tree.getroot()

    # Знаходимо namespace
    ns = {'kml': 'http://earth.google.com/kml/2.2'}

    # Спробуємо знайти Placemark елементи з namespace
    placemarks = root.findall('.//kml:Placemark', ns)
    if not placemarks:
        # Спробуємо без namespace
        ns = {}
        placemarks = root.findall('.//Placemark')

    print(f"Знайдено {len(placemarks)} Placemark елементів")

    pzf_objects = []

    for placemark in placemarks:
        name_elem = placemark.find('kml:name', ns)
        desc_elem = placemark.find('kml:description', ns)
        coords_elem = placemark.find('.//kml:coordinates', ns)

        name = name_elem.text.strip() if name_elem is not None and name_elem.text else ''
        description = desc_elem.text.strip() if desc_elem is not None and desc_elem.text else ''
        coordinates_text = coords_elem.text.strip() if coords_elem is not None and coords_elem.text else ''

        if not name or not coordinates_text:
            continue

        # Парсимо дані з опису
        desc_data = parse_kml_description(description)

        # Парсимо координати
        coords = parse_kml_coordinates(coordinates_text)
        if not coords:
            continue

        centroid = calculate_centroid(coords)

        # Створюємо запис ПЗФ
        pzf_record = {
            'name': name,
            'coordinates': coords,
            'centroid': centroid,
            'area_ha': desc_data.get('area_ha'),
            'category': desc_data.get('category'),
            'pzf_code': desc_data.get('pzf_code'),
            'reg_num': desc_data.get('reg_num'),
            'category_num': desc_data.get('category_num'),
            'db_code': desc_data.get('db_code'),
            'source': 'kml'
        }

        pzf_objects.append(pzf_record)

    return pzf_objects

def update_database_with_kml(existing_data: Dict, kml_records: List[Dict]) -> Dict:
    """Оновлює базу даних новими координатами з KML."""
    updated_records = []
    matched_count = 0
    new_records = []

    for kml_record in kml_records:
        existing_record = find_matching_record(kml_record, existing_data['records'])

        if existing_record:
            # Оновлюємо існуючий запис
            updated_record = existing_record.copy()
            updated_record['lon'] = kml_record['centroid'][0]
            updated_record['lat'] = kml_record['centroid'][1]
            updated_record['coord_source'] = 'kml-synchronized'
            updated_record['geometry'] = {
                'type': 'Polygon',
                'coordinates': [kml_record['coordinates']]
            }
            updated_records.append(updated_record)
            matched_count += 1
        else:
            # Створюємо новий запис
            new_record = {
                'name': kml_record['name'],
                'lon': kml_record['centroid'][0],
                'lat': kml_record['centroid'][1],
                'coord_source': 'kml-new',
                'geometry': {
                    'type': 'Polygon',
                    'coordinates': [kml_record['coordinates']]
                },
                'area': float(kml_record.get('area_ha', 0)) if kml_record.get('area_ha') else None,
                'category': kml_record.get('category'),
                'num': kml_record.get('pzf_code'),
                'significance': 'місцеве',  # За замовчуванням
                'type': kml_record.get('category', ''),
                'type_normalized': (kml_record.get('category') or '').lower(),
                'page': None,
                'location': '',
                'org': '',
                'decree': '',
                'otg_id': None,
                'otg_name': None,
                'rayon_id': None,
                'rayon_name': None
            }
            new_records.append(new_record)

    print(f"Синхронізовано {matched_count} існуючих записів")
    print(f"Додано {len(new_records)} нових записів")

    # Об'єднуємо всі записи
    all_records = updated_records + existing_data['records'] + new_records

    # Видаляємо дублікати (якщо такі є)
    seen = set()
    unique_records = []
    for record in all_records:
        record_id = (record.get('name', ''), record.get('num'))
        if record_id not in seen:
            seen.add(record_id)
            unique_records.append(record)

    # Оновлюємо загальну статистику
    total_area = sum(r.get('area', 0) for r in unique_records if r.get('area'))
    updated_data = existing_data.copy()
    updated_data['records'] = unique_records
    updated_data['totals_official']['objects'] = len(unique_records)
    updated_data['totals_official']['area_ha'] = total_area

    return updated_data

def main():
    print("Синхронізація координат ПЗФ з Zapov2.kml...")

    # Завантажуємо існуючі дані
    existing_data = load_existing_data()
    print(f"Завантажено {len(existing_data['records'])} існуючих записів")

    # Парсимо KML файл
    kml_path = ROOT / 'Zapov2.kml'
    if not kml_path.exists():
        print(f"Помилка: файл {kml_path} не знайдено")
        return

    kml_records = parse_kml_file(kml_path)
    print(f"Розпарсено {len(kml_records)} об'єктів з KML файлу")

    # Синхронізуємо дані
    updated_data = update_database_with_kml(existing_data, kml_records)

    # Зберігаємо оновлену базу даних
    DATA.mkdir(parents=True, exist_ok=True)
    output_file = DATA / 'pzf.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(updated_data, f, ensure_ascii=False, separators=(',', ':'))

    print(f"\nГотово! Створено базу даних з {len(updated_data['records'])} записів")
    print(f"Файл збережено: {output_file}")
    print(f"Розмір файлу: {output_file.stat().st_size} байт")

if __name__ == '__main__':
    main()