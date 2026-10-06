"""Symbology: palettes, area-proportional sizes, labels, choropleth, boundaries."""
import colorsys
import math

from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor, QFont
from qgis.core import (
    QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY, QgsField, QgsProperty,
    QgsMarkerSymbol, QgsFillSymbol, QgsCategorizedSymbolRenderer, QgsRendererCategory,
    QgsSingleSymbolRenderer, QgsRuleBasedRenderer, QgsGraduatedSymbolRenderer, QgsRendererRange,
    QgsFeatureRequest, QgsPalLayerSettings, QgsTextFormat, QgsTextBufferSettings,
    QgsVectorLayerSimpleLabeling, QgsPropertyCollection, QgsLineSymbol)

PALETTES = {
    "Okabe-Ito (colour-blind safe)": ["#E69F00", "#56B4E9", "#009E73", "#F0E442", "#0072B2",
                                      "#D55E00", "#CC79A7", "#999999"],
    "Tableau 10": ["#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F", "#EDC948",
                   "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC"],
    "ColorBrewer Set2": ["#66C2A5", "#FC8D62", "#8DA0CB", "#E78AC3", "#A6D854", "#FFD92F",
                         "#E5C494", "#B3B3B3"],
    "ColorBrewer Dark2": ["#1B9E77", "#D95F02", "#7570B3", "#E7298A", "#66A61E", "#E6AB02",
                          "#A6761D", "#666666"],
    "ColorBrewer Paired": ["#A6CEE3", "#1F78B4", "#B2DF8A", "#33A02C", "#FB9A99", "#E31A1C",
                           "#FDBF6F", "#FF7F00", "#CAB2D6", "#6A3D9A", "#FFFF99", "#B15928"],
    "Journal (as in the India example)": ["#756BB1", "#E6550D", "#31A354", "#FDAE6B", "#3182BD",
                                          "#6BAED6", "#FDD49E", "#C51B8A", "#636363"],
    "Greyscale (black & white print)": ["#252525", "#636363", "#969696", "#BDBDBD", "#D9D9D9",
                                        "#F0F0F0"],
}
OTHER_COLOR = "#BDBDBD"

RAMPS = {   # 9-stop sequential ramps (ColorBrewer / viridis)
    "Blues": ["#f7fbff", "#deebf7", "#c6dbef", "#9ecae1", "#6baed6", "#4292c6", "#2171b5", "#08519c", "#08306b"],
    "YlOrRd": ["#ffffcc", "#ffeda0", "#fed976", "#feb24c", "#fd8d3c", "#fc4e2a", "#e31a1c", "#bd0026", "#800026"],
    "Greens": ["#f7fcf5", "#e5f5e0", "#c7e9c0", "#a1d99b", "#74c476", "#41ab5d", "#238b45", "#006d2c", "#00441b"],
    "Purples": ["#fcfbfd", "#efedf5", "#dadaeb", "#bcbddc", "#9e9ac8", "#807dba", "#6a51a3", "#54278f", "#3f007d"],
    "YlGnBu": ["#ffffd9", "#edf8b1", "#c7e9b4", "#7fcdbb", "#41b6c4", "#1d91c0", "#225ea8", "#253494", "#081d58"],
    "Viridis": ["#fde725", "#b5de2b", "#6ece58", "#35b779", "#1f9e89", "#26828e", "#31688e", "#3e4989", "#440154"],
    "Greys": ["#ffffff", "#f0f0f0", "#d9d9d9", "#bdbdbd", "#969696", "#737373", "#525252", "#252525", "#000000"],
}


def group_colors(groups, palette_name, max_groups):
    """Maps ordered groups (largest first) to colours; tail merged into 'Other'."""
    base = PALETTES.get(palette_name) or PALETTES["Okabe-Ito (colour-blind safe)"]
    shown = list(groups[:max_groups]) if len(groups) > max_groups else list(groups)
    cols = {}
    len(shown)
    for i, g in enumerate(shown):
        if i < len(base):
            cols[g] = base[i]
        else:                                    # extend with evenly spaced hues
            h = ((i - len(base)) * 0.618033988749895) % 1.0
            r, gg, b = colorsys.hsv_to_rgb(h, 0.55, 0.85)
            cols[g] = "#%02x%02x%02x" % (int(r * 255), int(gg * 255), int(b * 255))
    return cols, [g for g in groups if g not in cols]


def ramp_colors(name, n):
    stops = RAMPS.get(name, RAMPS["Blues"])[2:]       # skip near-white stops (invisible on paper)
    out = []
    for i in range(n):
        t = (i / (n - 1) if n > 1 else 0.6) * (len(stops) - 1)
        lo, hi = int(math.floor(t)), int(math.ceil(t))
        a, b = QColor(stops[lo]), QColor(stops[hi])
        f = t - lo
        out.append(QColor(int(a.red() + (b.red() - a.red()) * f),
                          int(a.green() + (b.green() - a.green()) * f),
                          int(a.blue() + (b.blue() - a.blue()) * f)).name())
    return out


# ---------------------------------------------------------------- sizes
def size_for(value, vmax, max_mm, min_mm):
    """Circle DIAMETER (mm) such that circle AREA is proportional to value."""
    if vmax <= 0 or value <= 0:
        return min_mm
    return max(min_mm, max_mm * math.sqrt(value / vmax))


def _nice(x):
    if x <= 0:
        return 1
    e = 10 ** math.floor(math.log10(x))
    for m in (1, 2, 2.5, 5, 10):
        if x <= m * e + 1e-12:
            return m * e
    return 10 * e


def legend_values(vmax, vmin=None):
    """3-4 'nice' reference values spanning the data (max is always the real maximum)."""
    vmax_i = vmax
    cands = [vmax_i, vmax_i / 2.0, vmax_i / 5.0, vmax_i / 10.0]
    out = []
    for c in cands:
        if c < max(vmin or 0, 1e-9) and out:
            continue
        v = c if c == vmax_i else _nice(c)
        if abs(v - round(v)) < 1e-9:
            v = int(round(v))
        if v > 0 and v not in out and v <= vmax_i:
            out.append(v)
    if vmin and vmin not in out and vmin < min(out):
        out.append(int(vmin) if float(vmin).is_integer() else vmin)
    return sorted(out)


# ---------------------------------------------------------------- layers
def build_point_layer(locs, name="Evidence (bubbles)"):
    lyr = QgsVectorLayer("Point?crs=EPSG:4326", name, "memory")
    pr = lyr.dataProvider()
    pr.addAttributes([QgsField("ID", QVariant.Int), QgsField("Name", QVariant.String),
                      QgsField("Group", QVariant.String), QgsField("Value", QVariant.Double),
                      QgsField("N_rows", QVariant.Int), QgsField("Mixed", QVariant.Int),
                      QgsField("Size_mm", QVariant.Double),
                      QgsField("Lon", QVariant.Double), QgsField("Lat", QVariant.Double)])
    lyr.updateFields()
    feats = []
    for lc in locs:
        f = QgsFeature(lyr.fields())
        f.setAttributes([lc.id, lc.name, getattr(lc, "plot_group", lc.group), float(lc.value), lc.n_rows,
                         1 if lc.mixed else 0, float(getattr(lc, "size_mm", 3.0)), lc.lon, lc.lat])
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lc.lon, lc.lat)))
        feats.append(f)
    pr.addFeatures(feats)
    lyr.updateExtents()
    return lyr


def _marker(color, opacity):
    c = QColor(color)
    c.setAlphaF(opacity)
    return QgsMarkerSymbol.createSimple({
        "name": "circle", "color": "%d,%d,%d,%d" % (c.red(), c.green(), c.blue(), c.alpha()),
        "outline_color": "#2b2b2b", "outline_width": "0.2", "size": "4"})


def style_bubbles(layer, colors, other_groups, single_group, single_color, opacity):
    def sym(color):
        s = _marker(color, opacity)
        s.setDataDefinedSize(QgsProperty.fromField("Size_mm"))
        return s
    if single_group:
        renderer = QgsSingleSymbolRenderer(sym(single_color))
    else:
        cats = [QgsRendererCategory(g, sym(c), g) for g, c in colors.items()]
        if other_groups:
            cats.append(QgsRendererCategory("Other", sym(OTHER_COLOR), "Other"))
        cats.append(QgsRendererCategory("", sym("#888888"), ""))   # fallback
        renderer = QgsCategorizedSymbolRenderer("Group", cats)
    renderer.setOrderBy(QgsFeatureRequest.OrderBy([QgsFeatureRequest.OrderByClause("Value", False)]))
    renderer.setOrderByEnabled(True)           # large circles are drawn first, small ones on top
    layer.setRenderer(renderer)


def style_labels(layer, mode, size_pt, font="Arial"):
    if mode == "none":
        layer.setLabelsEnabled(False)
        return
    s = QgsPalLayerSettings()
    s.fieldName = "ID"
    s.isExpression = False
    tf = QgsTextFormat()
    f = QFont(font)
    f.setBold(True)
    tf.setFont(f)
    tf.setSize(size_pt)
    tf.setColor(QColor("#111111"))
    buf = QgsTextBufferSettings()
    buf.setEnabled(True)
    buf.setSize(0.7)
    buf.setColor(QColor("#ffffff"))
    tf.setBuffer(buf)
    s.setFormat(tf)
    if mode == "inside":
        s.placement = QgsPalLayerSettings.Placement.OverPoint
    else:
        s.placement = QgsPalLayerSettings.Placement.AroundPoint
        s.dist = 0.4
        props = QgsPropertyCollection()
        props.setProperty(QgsPalLayerSettings.Property.LabelDistance,
                          QgsProperty.fromExpression('"Size_mm" / 2.0 + 0.2'))
        s.setDataDefinedProperties(props)
    try:                                        # never silently drop a number
        from qgis.core import Qgis
        s.setOverlapHandling(Qgis.LabelOverlapHandling.AllowOverlapIfRequired)
    except Exception:
        s.displayAll = True
    layer.setLabeling(QgsVectorLayerSimpleLabeling(s))
    layer.setLabelsEnabled(True)


# ---------------------------------------------------------------- boundaries
def style_countries(layer, selected_a3, mask, has_basemap, ocean_fill=True):
    outline = "#555555"
    fill_none = "255,255,255,0"
    land = fill_none if has_basemap else "#f3f1ea"
    if selected_a3 and mask:
        inside = QgsFillSymbol.createSimple({"color": land, "outline_color": "#333333", "outline_width": "0.3"})
        outside = QgsFillSymbol.createSimple({"color": "255,255,255,150" if has_basemap else "#e9e9e9",
                                              "outline_color": "#9a9a9a", "outline_width": "0.12"})
        root = QgsRuleBasedRenderer.Rule(None)
        codes = ",".join("'%s'" % a for a in selected_a3)
        root.appendChild(QgsRuleBasedRenderer.Rule(inside, 0, 0, '"adm0_a3" IN (%s)' % codes, "Study area"))
        root.appendChild(QgsRuleBasedRenderer.Rule(outside, 0, 0, "ELSE", "Other"))
        layer.setRenderer(QgsRuleBasedRenderer(root))
    else:
        sym = QgsFillSymbol.createSimple({"color": land, "outline_color": outline, "outline_width": "0.15"})
        layer.setRenderer(QgsSingleSymbolRenderer(sym))


def style_admin1(layer):
    sym = QgsFillSymbol.createSimple({"color": "255,255,255,0", "outline_color": "#7a7a7a",
                                      "outline_width": "0.1", "outline_style": "solid"})
    layer.setRenderer(QgsSingleSymbolRenderer(sym))


def style_world_inset(layer):
    sym = QgsFillSymbol.createSimple({"color": "#e4e4e4", "outline_color": "#8c8c8c", "outline_width": "0.08"})
    layer.setRenderer(QgsSingleSymbolRenderer(sym))


# ---------------------------------------------------------------- choropleth
def class_breaks(values, n, method):
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return []
    lo, hi = vals[0], vals[-1]
    if lo == hi:
        return [(lo, hi)]
    n = max(1, min(n, len(set(vals))))
    if method == "equal":
        edges = [lo + (hi - lo) * i / n for i in range(n + 1)]
    else:
        edges = [vals[min(len(vals) - 1, int(round(i * (len(vals) - 1) / n)))] for i in range(n + 1)]
        edges[0], edges[-1] = lo, hi
    # drop duplicate edges
    clean = [edges[0]]
    for e in edges[1:]:
        if e > clean[-1]:
            clean.append(e)
    return list(zip(clean[:-1], clean[1:]))


def _fmt(v):
    return str(int(round(v))) if abs(v - round(v)) < 1e-9 else "%.1f" % v


def build_choropleth_layer(locs, gaz, ramp, n_classes, method, opacity=0.9):
    """Polygon layer (countries or admin-1) filled by Value. Returns (layer, legend_entries)."""
    lyr = QgsVectorLayer("MultiPolygon?crs=EPSG:4326", "Evidence (choropleth)", "memory")
    pr = lyr.dataProvider()
    pr.addAttributes([QgsField("Name", QVariant.String), QgsField("Value", QVariant.Double)])
    lyr.updateFields()
    feats = []
    for lc in locs:
        geom = None
        if lc.kind == "country" and lc.key in gaz.by_a3:
            geom = gaz.by_a3[lc.key]["geom"]
        elif lc.kind == "admin1":
            gaz._load_admin1()
            for r in gaz._admin1:
                if r["key"] == lc.key:
                    geom = r["geom"]
                    break
        if geom is None:
            continue
        f = QgsFeature(lyr.fields())
        f.setAttributes([lc.name, float(lc.value)])
        f.setGeometry(QgsGeometry(geom))
        feats.append(f)
    pr.addFeatures(feats)
    lyr.updateExtents()
    breaks = class_breaks([lc.value for lc in locs], n_classes, method)
    cols = ramp_colors(ramp, max(1, len(breaks)))
    ranges, legend = [], []
    for i, ((a, b), col) in enumerate(zip(breaks, cols)):
        c = QColor(col)
        c.setAlphaF(opacity)
        sym = QgsFillSymbol.createSimple({"color": "%d,%d,%d,%d" % (c.red(), c.green(), c.blue(), c.alpha()),
                                          "outline_color": "#555555", "outline_width": "0.15"})
        label = "%s" % _fmt(a) if a == b else ("%s – %s" % (_fmt(a), _fmt(b)))
        upper = b if i == len(breaks) - 1 else b - 1e-9
        ranges.append(QgsRendererRange(a, upper if i == len(breaks) - 1 else b, sym, label))
        legend.append((label, col))
    lyr.setRenderer(QgsGraduatedSymbolRenderer("Value", ranges))
    return lyr, legend


# ---------------------------------------------------------------- graticule layer
def build_graticule_layer(interval=30, lat_min=-90, lat_max=90):
    """Densified lat/lon lines as an ordinary vector layer. Used for world-scale maps,
    where QGIS' built-in layout grid cannot invert the projection at the map corners."""
    from qgis.core import QgsLineString, QgsPoint
    lyr = QgsVectorLayer("LineString?crs=EPSG:4326", "Graticule", "memory")
    pr = lyr.dataProvider()
    pr.addAttributes([QgsField("label", QVariant.String)])
    lyr.updateFields()
    feats = []

    def add(points, text):
        f = QgsFeature(lyr.fields())
        f.setGeometry(QgsGeometry(QgsLineString([QgsPoint(x, y) for x, y in points])))
        f.setAttributes([text])
        feats.append(f)

    lon = -180
    while lon <= 180:
        pts = [(lon, la) for la in range(int(lat_min), int(lat_max) + 1, 2)]
        suffix = "E" if lon > 0 else ("W" if lon < 0 else "")
        add(pts, "%d°%s" % (abs(lon), suffix))
        lon += interval
    lat = -90 + interval
    while lat < 90:
        if lat_min <= lat <= lat_max:
            pts = [(lo, lat) for lo in range(-180, 181, 2)]
            suffix = "N" if lat > 0 else ("S" if lat < 0 else "")
            add(pts, "%d°%s" % (abs(lat), suffix))
        lat += interval
    pr.addFeatures(feats)
    lyr.setRenderer(QgsSingleSymbolRenderer(QgsLineSymbol.createSimple(
        {"line_color": "120,120,120,120", "line_width": "0.12"})))
    s = QgsPalLayerSettings()
    s.fieldName = "label"
    tf = QgsTextFormat()
    f = QFont("Arial")
    tf.setFont(f)
    tf.setSize(6)
    tf.setColor(QColor("#666666"))
    buf = QgsTextBufferSettings()
    buf.setEnabled(True)
    buf.setSize(0.5)
    buf.setColor(QColor("#ffffff"))
    tf.setBuffer(buf)
    s.setFormat(tf)
    s.placement = QgsPalLayerSettings.Placement.Line
    lyr.setLabeling(QgsVectorLayerSimpleLabeling(s))
    lyr.setLabelsEnabled(True)
    return lyr
