"""
Pure-Python ESRI Shapefile (Polygon) -> GeoJSON converter.
Не вимагає GDAL чи geopandas. Працює лише з полігональними шейпфайлами.
"""
import struct
import json


def parse_dbf(path):
    """Read a dBase III/IV .dbf file. Returns (fields, records)."""
    with open(path, 'rb') as f:
        header = f.read(32)
        num_records = struct.unpack('<I', header[4:8])[0]
        header_len  = struct.unpack('<H', header[8:10])[0]
        record_len  = struct.unpack('<H', header[10:12])[0]
        fields = []
        while True:
            fd = f.read(32)
            if fd[0] == 0x0D:
                break
            name  = fd[:11].split(b'\x00')[0].decode('ascii', errors='ignore').strip()
            ftype = chr(fd[11])
            flen  = fd[16]
            fields.append((name, ftype, flen))
        f.seek(header_len)
        records = []
        for _ in range(num_records):
            rec = f.read(record_len)
            if len(rec) < record_len:
                break
            if rec[0:1] == b'*':       # deleted
                continue
            offset, row = 1, {}
            for name, ftype, flen in fields:
                raw = rec[offset:offset + flen]
                offset += flen
                val = None
                for enc in ('utf-8', 'cp1251', 'cp866'):
                    try:
                        val = raw.decode(enc).strip()
                        break
                    except UnicodeDecodeError:
                        continue
                if val is None:
                    val = raw.decode('latin1', errors='replace').strip()
                if ftype in ('N', 'F'):
                    try:
                        val = float(val) if '.' in val else (int(val) if val else None)
                    except ValueError:
                        pass
                row[name] = val
            records.append(row)
        return fields, records


def parse_shp(path):
    """Return list of GeoJSON-style geometries (Polygon/MultiPolygon)."""
    with open(path, 'rb') as f:
        data = f.read()
    geoms = []
    pos = 100  # skip header
    while pos < len(data):
        if pos + 8 > len(data):
            break
        content_len = struct.unpack('>I', data[pos + 4:pos + 8])[0]
        rec_start, rec_end = pos + 8, pos + 8 + content_len * 2
        st = struct.unpack('<I', data[rec_start:rec_start + 4])[0]
        if st == 0:
            geoms.append(None); pos = rec_end; continue
        if st in (5, 15, 25):  # Polygon variants
            num_parts  = struct.unpack('<i', data[rec_start + 36:rec_start + 40])[0]
            num_points = struct.unpack('<i', data[rec_start + 40:rec_start + 44])[0]
            parts_off  = rec_start + 44
            parts = list(struct.unpack(f'<{num_parts}i', data[parts_off:parts_off + num_parts * 4]))
            pts_off = parts_off + num_parts * 4
            points = [
                list(struct.unpack('<dd', data[pts_off + i * 16:pts_off + i * 16 + 16]))
                for i in range(num_points)
            ]
            parts.append(num_points)
            rings = [points[parts[i]:parts[i + 1]] for i in range(num_parts)]

            def signed_area(ring):
                a = 0
                for i in range(len(ring) - 1):
                    a += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
                return a / 2.0

            polys, current = [], None
            for r in rings:
                if signed_area(r) < 0:        # outer ring (CW in shapefile)
                    if current is not None:
                        polys.append(current)
                    current = [r]
                else:                          # hole
                    if current is None:
                        current = [r]
                    else:
                        current.append(r)
            if current is not None:
                polys.append(current)

            if len(polys) == 1:
                geoms.append({'type': 'Polygon', 'coordinates': polys[0]})
            else:
                geoms.append({'type': 'MultiPolygon', 'coordinates': polys})
        else:
            geoms.append(None)
        pos = rec_end
    return geoms


def round_coords(geom, ndigits=5):
    if geom is None:
        return None
    if geom['type'] == 'Polygon':
        geom['coordinates'] = [
            [[round(p[0], ndigits), round(p[1], ndigits)] for p in ring]
            for ring in geom['coordinates']
        ]
    elif geom['type'] == 'MultiPolygon':
        geom['coordinates'] = [
            [[[round(p[0], ndigits), round(p[1], ndigits)] for p in ring] for ring in poly]
            for poly in geom['coordinates']
        ]
    return geom


def shp_to_geojson(shp_path, dbf_path, ndigits=5):
    """Combine .shp + .dbf into a GeoJSON FeatureCollection."""
    geoms = parse_shp(shp_path)
    _, records = parse_dbf(dbf_path)
    features = []
    for i, (geom, rec) in enumerate(zip(geoms, records)):
        if geom is None:
            continue
        features.append({
            'type': 'Feature',
            'id': rec.get('id', i) if 'id' in rec else i,
            'properties': dict(rec),
            'geometry': round_coords(geom, ndigits),
        })
    return {'type': 'FeatureCollection', 'features': features}


# Latin → Cyrillic map for cleaning OTG names where some chars look Latin
LATIN_TO_CYR = {
    'a': 'а', 'A': 'А', 'e': 'е', 'E': 'Е', 'o': 'о', 'O': 'О',
    'p': 'р', 'P': 'Р', 'c': 'с', 'C': 'С', 'x': 'х', 'X': 'Х',
    'i': 'і', 'I': 'І', 'y': 'у', 'Y': 'У',
    'H': 'Н', 'B': 'В', 'M': 'М', 'T': 'Т', 'K': 'К',
}


def fix_latin_lookalikes(s):
    return ''.join(LATIN_TO_CYR.get(c, c) for c in s) if s else s


if __name__ == '__main__':
    import sys
    if len(sys.argv) != 4:
        print("Usage: python3 shp_parser.py <input.shp> <input.dbf> <output.geojson>")
        sys.exit(1)
    gj = shp_to_geojson(sys.argv[1], sys.argv[2])
    with open(sys.argv[3], 'w', encoding='utf-8') as f:
        json.dump(gj, f, ensure_ascii=False, separators=(',', ':'))
    print(f"Wrote {len(gj['features'])} features to {sys.argv[3]}")
