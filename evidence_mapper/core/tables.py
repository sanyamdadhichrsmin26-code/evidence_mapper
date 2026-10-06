"""Read tabular input (CSV/TSV/TXT in pure Python; XLSX/ODS/GPKG/SHP/GeoJSON
through OGR; or any vector layer open in the QGIS project)."""
import csv
import io
import os

from qgis.core import (QgsVectorLayer, QgsProject, QgsCoordinateReferenceSystem,
                       QgsCoordinateTransform, QgsPointXY, QgsFeatureRequest)

TEXT_EXT = {".csv", ".tsv", ".txt"}
SEP = "!!::!!"


class Table:
    def __init__(self, fields, rows, points=None, name=""):
        self.fields = list(fields)
        self.rows = rows            # list[dict]
        self.points = points        # list[QgsPointXY|None] or None
        self.name = name

    def __len__(self):
        return len(self.rows)

    def numeric_fields(self):
        out = []
        for f in self.fields:
            vals = [r.get(f, "") for r in self.rows[:200] if str(r.get(f, "")).strip() != ""]
            if vals and all(to_float(v) is not None for v in vals):
                out.append(f)
        return out


def to_float(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("\u2212", "-")
    if not s:
        return None
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    s = s.replace(" ", "")
    try:
        return float(s)
    except ValueError:
        return None


def _clean(v):
    if v is None:
        return ""
    if hasattr(v, "isNull"):
        try:
            if v.isNull():
                return ""
        except Exception:
            pass
    if hasattr(v, "toString") and not isinstance(v, str):
        try:
            return v.toString()
        except Exception:
            pass
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def read_text_table(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    text = None
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect=dialect)
    rows_raw = [r for r in reader if any(c.strip() for c in r)]
    if not rows_raw:
        raise ValueError("The file is empty.")
    header = [h.strip() or "column_%d" % (i + 1) for i, h in enumerate(rows_raw[0])]
    seen, fields = {}, []
    for h in header:                         # make header names unique
        seen[h] = seen.get(h, 0) + 1
        fields.append(h if seen[h] == 1 else "%s_%d" % (h, seen[h]))
    rows = []
    for r in rows_raw[1:]:
        r = r + [""] * (len(fields) - len(r))
        rows.append({f: r[i].strip() for i, f in enumerate(fields)})
    return Table(fields, rows, name=os.path.basename(path))


def list_sublayers(path):
    """Worksheet / layer names for multi-layer sources (XLSX, ODS, GPKG)."""
    if os.path.splitext(path)[1].lower() in TEXT_EXT:
        return []
    lyr = QgsVectorLayer(path, "probe", "ogr")
    if not lyr.isValid():
        return []
    subs = lyr.dataProvider().subLayers()
    names = []
    for s in subs:
        parts = s.split(SEP)
        if len(parts) > 1:
            names.append(parts[1])
    return names if len(names) > 1 else []


def _layer_to_table(lyr, name):
    to4326 = None
    if lyr.isSpatial() and lyr.crs().isValid() and lyr.crs().authid() != "EPSG:4326":
        to4326 = QgsCoordinateTransform(lyr.crs(), QgsCoordinateReferenceSystem("EPSG:4326"),
                                        QgsProject.instance())
    fields = [f.name() for f in lyr.fields()]
    rows, pts = [], []
    for feat in lyr.getFeatures(QgsFeatureRequest()):
        rows.append({f: _clean(feat[f]) for f in fields})
        p = None
        if lyr.isSpatial() and feat.hasGeometry() and not feat.geometry().isNull():
            g = feat.geometry()
            c = g.centroid() if g.type() != 0 else g
            try:
                pt = c.asPoint()
                if to4326:
                    pt = to4326.transform(pt)
                p = QgsPointXY(pt)
            except Exception:
                p = None
        pts.append(p)
    return Table(fields, rows, pts if lyr.isSpatial() else None, name)


def load_table(source, sheet=""):
    """`source` is a file path or "layer:<id>" for an open project layer."""
    if source.startswith("layer:"):
        lyr = QgsProject.instance().mapLayer(source[6:])
        if lyr is None or not isinstance(lyr, QgsVectorLayer):
            raise ValueError("The selected project layer no longer exists.")
        return _layer_to_table(lyr, lyr.name())
    if not os.path.exists(source):
        raise ValueError("File not found: %s" % source)
    ext = os.path.splitext(source)[1].lower()
    if ext in TEXT_EXT:
        return read_text_table(source)
    uri = source + ("|layername=%s" % sheet if sheet else "")
    lyr = QgsVectorLayer(uri, "input", "ogr")
    if not lyr.isValid():
        raise ValueError("QGIS/OGR could not open this file. Supported: CSV, TSV, XLSX, ODS, "
                         "GeoPackage, Shapefile, GeoJSON.")
    return _layer_to_table(lyr, os.path.basename(source))
