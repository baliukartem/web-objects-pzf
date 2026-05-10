"""
Парсер офіційного переліку ПЗФ (PDF) → JSON.

Використовує pdfplumber для розбору таблиць з PDF. На сторінках PDF
кожен запис розкиданий по комірках таблиці; ми збираємо їх у плоский
список словників.

Запуск:
    pip install pdfplumber
    python3 pdf_parser.py ../source/'Perelik PZF 01.01.2025 .pdf' ../assets/data/pdf_records.json
"""
import json
import re
import sys
from collections import Counter

import pdfplumber  # type: ignore


def parse_pdf(path):
    """Витягнути всі записи з PDF та повернути список словників."""
    records = []
    significance = None  # 'загальнодержавне' | 'місцеве'
    category = None

    with pdfplumber.open(path) as pdf:
        for pi, page in enumerate(pdf.pages):
            for table in page.extract_tables():
                for row in table:
                    if not row or all(c is None or str(c).strip() == '' for c in row):
                        continue
                    cells = [(c.strip() if c else '') for c in row]
                    joined = re.sub(r'\s+', ' ', ' '.join(cells)).strip()
                    upper = joined.upper()

                    # Маркери значення
                    if 'ЗАГАЛЬНОДЕРЖАВНОГО' in upper and ('ТЕРИТОРІЇ' in upper or 'ОБ' in upper):
                        significance = 'загальнодержавне'
                        continue
                    if 'МІСЦЕВОГО' in upper and ('ТЕРИТОРІЇ' in upper or 'ОБ' in upper):
                        significance = 'місцеве'
                        continue

                    # Маркери категорії
                    cat = None
                    if 'НАЦІОНАЛЬН' in upper and 'ПАРК' in upper:
                        cat = 'Національний природний парк'
                    elif 'РЕГІОНАЛЬН' in upper and 'ПАРК' in upper:
                        cat = 'Регіональний ландшафтний парк'
                    elif 'ДЕНДРОЛОГ' in upper and 'ПАРК' in upper:
                        cat = 'Дендрологічний парк'
                    elif 'ЗООЛОГІЧН' in upper and 'ПАРК' in upper:
                        cat = 'Зоологічний парк'
                    elif 'БОТАНІЧН' in upper and ('САД' in upper or 'САДИ' in upper):
                        cat = 'Ботанічний сад'
                    elif (("ПАМ'ЯТК" in upper) or 'ПАМ’ЯТК' in upper) and (
                        'САДОВО' in upper or 'ПАРКОВО' in upper or 'ПАРКИ-' in upper or 'ПАРКИ -' in upper):
                        cat = "Парк-пам'ятка садово-паркового мистецтва"
                    elif (("ПАМ'ЯТК" in upper) or 'ПАМ’ЯТК' in upper) and 'ПРИРОДИ' in upper:
                        cat = "Пам'ятка природи"
                    elif 'ЗАКАЗНИК' in upper:
                        cat = 'Заказник'
                    if cat and len(joined) < 120 and not re.search(r'\d{2,}', joined):
                        category = cat
                        continue

                    # Підсумкові рядки
                    if upper.startswith('РАЗОМ') or 'ВСЬОГО' in upper or 'ВСЬОРГО' in upper:
                        continue

                    # Дані: №№ у першій комірці
                    num_str = cells[0] if cells else ''
                    m = re.match(r'^(\d+)\.?$', num_str)
                    if not m:
                        continue
                    name = re.sub(r'\s+', ' ', cells[1]).strip() if len(cells) > 1 else ''
                    if not name:
                        continue
                    typ = re.sub(r'\s+', ' ', cells[2]).strip() if len(cells) > 2 else ''
                    area_raw = cells[3].strip() if len(cells) > 3 else ''
                    am = re.search(r'(\d+(?:[.,]\d+)?)', area_raw.replace(' ', ''))
                    area = float(am.group(1).replace(',', '.')) if am else None
                    location = re.sub(r'\s+', ' ', cells[4]).strip() if len(cells) > 4 else ''
                    org = re.sub(r'\s+', ' ', cells[5]).strip() if len(cells) > 5 else ''
                    decree = re.sub(r'\s+', ' ', cells[6]).strip() if len(cells) > 6 else ''

                    records.append({
                        'num': int(m.group(1)),
                        'name': name,
                        'type': typ,
                        'area': area,
                        'area_raw': area_raw,
                        'location': location,
                        'org': org,
                        'decree': decree,
                        'category': category,
                        'significance': significance,
                        'page': pi + 1,
                    })
    return records


def refine_category(r):
    """Уточнити категорію на основі поля type, якщо section header не детектовано."""
    t = (r.get('type') or '').upper()
    cat = r.get('category')
    if cat is None and r.get('significance') == 'загальнодержавне' and 'НАЦІОНАЛЬН' in t and 'ПАРК' in t:
        return 'Національний природний парк'
    if 'ППСПМ' in t or ('ПАРК' in t and "ПАМ'ЯТК" in t):
        return "Парк-пам'ятка садово-паркового мистецтва"
    if 'ЗАПОВІДН' in t and 'УРОЧИЩ' in t:
        return 'Заповідне урочище'
    if 'ДЕНДРОЛОГ' in t and 'ПАРК' in t:
        return 'Дендрологічний парк'
    if 'РЕГІОНАЛЬН' in t and 'ПАРК' in t:
        return 'Регіональний ландшафтний парк'
    if 'НАЦІОНАЛЬН' in t and 'ПАРК' in t:
        return 'Національний природний парк'
    return cat


def normalize_type(t):
    if not t:
        return ''
    tl = t.lower()
    table = [
        ('ботан', 'ботанічний'), ('гідр', 'гідрологічний'),
        ('геолог', 'геологічний'), ('зоолог', 'зоологічний'),
        ('ландшафт', 'ландшафтний'), ('комплекс', 'комплексний'),
        ('лісов', 'лісовий'), ('орнітол', 'орнітологічний'),
        ('іхтіол', 'іхтіологічний'), ('дендр', 'дендрологічний'),
        ('заповідн', 'заповідне урочище'),
        ('нац', 'національний парк'), ('регіон', 'регіональний'),
    ]
    for needle, val in table:
        if needle in tl:
            return val
    if 'парк' in tl and "пам'ят" in tl:
        return "парк-пам'ятка"
    return tl.split()[0] if tl else ''


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 pdf_parser.py <input.pdf> <output.json>")
        sys.exit(1)
    pdf_path, out_path = sys.argv[1], sys.argv[2]
    print(f"Parsing {pdf_path}…")
    records = parse_pdf(pdf_path)
    for r in records:
        r['category'] = refine_category(r)
        r['type_normalized'] = normalize_type(r.get('type'))
    print(f"  → {len(records)} records")
    print("  By category:")
    for k, v in Counter((r['significance'], r['category']) for r in records).most_common():
        print(f"    {k}: {v}")
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump({'records': records}, f, ensure_ascii=False, separators=(',', ':'))
    print(f"  Wrote {out_path}")


if __name__ == '__main__':
    main()
