"""Orchestrates a complete build: data -> layers -> layout -> export."""
import os
import re
import traceback

from qgis.PyQt.QtCore import QSize
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsRectangle, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsLayoutExporter, QgsVectorFileWriter, QgsRasterLayer, QgsPointXY, QgsCoordinateTransformContext)

from . import styling
from .aggregate import aggregate, format_unmapped_note
from .basemaps import BASEMAPS, make_basemap_layer
from .gazetteer import Gazetteer, REGIONS, COUNTRIES_PATH, ADMIN1_PATH, WORLD_PATH
from .layout_builder import Ctx, build_layout
from .tables import load_table

_GAZ = None


def get_gazetteer():
    global _GAZ
    if _GAZ is None:
        _GAZ = Gazetteer()
    return _GAZ


WGS84 = "EPSG:4326"


class BuildResult:
    def __init__(self):
        self.layout = None
        self.layout_name = ""
        self.warnings = []
        self.files = []
        self.caption = ""
        self.agg = None
        self.group = None


# ------------------------------------------------------------------ area & CRS
def resolve_area(area, gaz, locs):
    """Returns (extent in EPSG:4326, selected ADM0 codes, is_global)."""
    sel = []
    if area.mode == "global":
        b = (-180, -58, 180, 84) if area.exclude_antarctica else (-180, -90, 180, 90)
        return QgsRectangle(*b), sel, True
    if area.mode == "region":
        return QgsRectangle(*REGIONS[area.region]), sel, area.region.startswith("World")
    if area.mode == "countries":
        if not area.countries:
            raise ValueError("Choose at least one country (or switch the study area to Global).")
        rect = gaz.area_extent(area.countries, area.include_territories)
        pad = 0.04
        rect.grow(max(rect.width(), rect.height()) * pad)
        return rect, list(area.countries), False
    if area.mode == "data":
        xs = [l.lon for l in locs]
        ys = [l.lat for l in locs]
        rect = QgsRectangle(min(xs), min(ys), max(xs), max(ys))
        span = max(rect.width(), rect.height(), 4.0)
        rect.grow(span * 0.14 + (2.0 if max(rect.width(), rect.height()) < 4 else 0))
        return rect, sel, False
    b = area.bbox
    rect = QgsRectangle(b[0], b[1], b[2], b[3])
    rect.grow(max(rect.width(), rect.height()) * 0.02)
    return rect, sel, False


def pick_crs(area, ext4326, is_global):
    cx, cy = ext4326.center().x(), ext4326.center().y()
    mode = area.crs_mode
    if mode == "auto":
        mode = "robinson" if (is_global or ext4326.width() > 200) else "laea"
    if mode == "epsg:4326":
        return QgsCoordinateReferenceSystem("EPSG:4326")
    if mode == "epsg:3857":
        return QgsCoordinateReferenceSystem("EPSG:3857")
    if mode == "robinson":
        return QgsCoordinateReferenceSystem("ESRI:54030")
    if mode == "equal_earth":
        return QgsCoordinateReferenceSystem("EPSG:8857")
    if mode == "custom" and area.crs_custom:
        c = QgsCoordinateReferenceSystem(area.crs_custom)
        if c.isValid():
            return c
    proj = "+proj=laea +lat_0=%.4f +lon_0=%.4f +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs" % (cy, cx)
    crs = QgsCoordinateReferenceSystem()
    if hasattr(crs, "createFromProj"):
        crs.createFromProj(proj)
    else:
        crs.createFromProj4(proj)
    return crs


def _slug(s):
    return re.sub(r"[^A-Za-z0-9_\-]+", "_", s).strip("_") or "evidence_map"


def _write_gpkg(layer, path, name):
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = "GPKG"
    opts.layerName = name
    if os.path.exists(path):
        opts.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
    res = QgsVectorFileWriter.writeAsVectorFormatV3(layer, path, QgsProject.instance().transformContext(), opts)
    if res[0] != QgsVectorFileWriter.NoError:
        raise RuntimeError("Could not write %s: %s" % (path, res[1]))
    return QgsVectorLayer("%s|layername=%s" % (path, name), layer.name(), "ogr")


def default_subtitle(cfg, agg, shown=None):
    if cfg.layout.subtitle.strip():
        return cfg.layout.subtitle.strip()
    unit = "studies"
    if cfg.style.map_style == "choropleth":
        return "Shading shows the number of included %s per %s (n = %d of %d mapped)" % (
            unit, "state / province" if cfg.data.loc_mode == "admin1" else "country", agg.rows_mapped,
            agg.total_rows)
    if shown is not None and shown < agg.rows_mapped:
        return "Circle area is proportional to the number of included %s (%d of %d shown in this area)" % (
            unit, shown, agg.total_rows)
    return "Circle area is proportional to the number of included %s (%d of %d mapped)" % (
        unit, agg.rows_mapped, agg.total_rows)


def export_layout(layout, out_dir, base, formats, dpi):
    files, errors = [], []
    exp = QgsLayoutExporter(layout)
    for fmt in formats:
        path = os.path.join(out_dir, "%s.%s" % (base, fmt))
        if fmt in ("png", "jpg", "tif"):
            s = QgsLayoutExporter.ImageExportSettings()
            s.dpi = dpi
            code = exp.exportToImage(path, s)
        elif fmt == "pdf":
            s = QgsLayoutExporter.PdfExportSettings()
            s.dpi = dpi
            code = exp.exportToPdf(path, s)
        elif fmt == "svg":
            s = QgsLayoutExporter.SvgExportSettings()
            s.dpi = dpi
            code = exp.exportToSvg(path, s)
        else:
            continue
        if code == QgsLayoutExporter.Success:
            files.append(path)
        else:
            errors.append("Export to %s failed (code %s)." % (fmt.upper(), code))
    return files, errors


# ------------------------------------------------------------------ main
def build_map(cfg, table=None, agg=None, geocoder=None, progress=None, is_canceled=None):
    res = BuildResult()
    gaz = get_gazetteer()
    project = QgsProject.instance()
    if table is None:
        table = load_table(cfg.data.source, cfg.data.sheet)
    if agg is None:
        agg = aggregate(table, cfg.data, gaz, geocoder, progress, is_canceled)
    res.agg = agg
    locs = agg.locs
    if not locs:
        raise ValueError("No row could be placed on the map. Check the location column and its "
                         "format (use 'Check mapping' on the previous page).")
    st, lo, ex = cfg.style, cfg.layout, cfg.export
    choropleth = st.map_style == "choropleth"
    if choropleth and cfg.data.loc_mode not in ("country", "admin1"):
        res.warnings.append("Choropleth needs country or state/province data; bubbles were drawn instead.")
        choropleth = False
        st.map_style = "bubbles"

    # ---- area, crs, extent
    ext4326, selected, is_global = resolve_area(cfg.area, gaz, locs)
    crs = pick_crs(cfg.area, ext4326, is_global)
    tr = QgsCoordinateTransform(QgsCoordinateReferenceSystem(WGS84), crs, project.transformContext())
    extent = tr.transformBoundingBox(ext4326)
    inside = [l for l in locs if ext4326.xMinimum() <= l.lon <= ext4326.xMaximum()
              and ext4326.yMinimum() <= l.lat <= ext4326.yMaximum()]
    outside = [l for l in locs if l not in inside]
    outside_note = ""
    if outside:
        if not inside:
            raise ValueError("None of your locations falls inside the chosen study area. "
                             "Pick another area or 'Fit extent to my data'.")
        rows_out = sum(l.n_rows for l in outside)
        outside_note = "Outside the mapped area: %d studies in %d location(s)." % (rows_out, len(outside))
        res.warnings.append("%d location(s) with %d studies lie outside the chosen area and are not drawn "
                            "(e.g. %s). They are listed in the footnote and in the exported CSV."
                            % (len(outside), rows_out, ", ".join(l.name for l in outside[:3])))
        for l in outside:
            l.id = 0
        locs = inside
        for i, l in enumerate(locs, 1):
            l.id = i

    # ---- groups, colours, sizes
    from collections import Counter
    group_totals = Counter()
    for l in locs:
        group_totals[l.group] += l.value
    ordered = [g for g, _ in sorted(group_totals.items(), key=lambda kv: (-kv[1], kv[0]))]
    single = (not cfg.data.group_field) or len(ordered) <= 1
    colors, others = styling.group_colors(ordered, st.palette, st.max_groups)
    vmax = max(l.value for l in locs)
    for l in locs:
        l.plot_group = l.group if l.group in colors else "Other"
        l.size_mm = styling.size_for(l.value, vmax, st.max_size_mm, st.min_size_mm)

    # ---- output folder & persistence
    out_dir = ex.out_dir
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    gpkg = os.path.join(out_dir, _slug(ex.base_name) + "_data.gpkg") if (out_dir and ex.save_data) else ""
    if gpkg and os.path.exists(gpkg):
        try:
            os.remove(gpkg)
        except OSError:
            pass

    # ---- layers (top -> bottom)
    layers = []
    pts = styling.build_point_layer(locs)
    if gpkg:
        pts = _write_gpkg(pts, gpkg, "evidence")
        pts.setName("Evidence (bubbles)")
    legend_choro = None
    if not choropleth:
        styling.style_bubbles(pts, colors, others, single, st.single_color, st.fill_opacity)
        styling.style_labels(pts, st.label_mode, st.label_size, lo.font)
        layers.append(pts)
    for lid in st.extra_layers:
        lyr = project.mapLayer(lid)
        if lyr is not None:
            layers.append(lyr)
    if st.show_admin1:
        a1 = QgsVectorLayer(ADMIN1_PATH, "State / province boundaries", "ogr")
        if selected:
            a1.setSubsetString("\"adm0_a3\" IN (%s)" % ",".join("'%s'" % c for c in selected))
        styling.style_admin1(a1)
        layers.append(a1)
    if choropleth:
        cl_mem, legend_choro = styling.build_choropleth_layer(locs, gaz, st.ramp, st.classes, st.class_method)
        cl = cl_mem
        if gpkg:
            cl = _write_gpkg(cl_mem, gpkg, "choropleth")
            cl.setName("Evidence (choropleth)")
            cl.setRenderer(cl_mem.renderer().clone())
        layers.append(cl)

    basemap, attr = None, ""
    if st.basemap == "project_layer":
        basemap = project.mapLayer(st.basemap_layer_id) if st.basemap_layer_id else None
        if basemap is None:
            res.warnings.append("The chosen project basemap layer was not found; no basemap used.")
        else:
            attr = basemap.name()
    elif st.basemap != "none":
        basemap = make_basemap_layer(st.basemap)
        if basemap is None:
            res.warnings.append("The basemap could not be created; the map was built without it.")
        else:
            attr = BASEMAPS[st.basemap][3]
            basemap.setOpacity(st.basemap_opacity)
            if st.basemap_gray:
                try:
                    basemap.hueSaturationFilter().setSaturation(-100)
                except Exception:
                    pass
    world_scale = is_global or ext4326.width() > 60 or ext4326.height() > 60
    graticule_layer = False
    if st.graticule and world_scale:
        gl = styling.build_graticule_layer(30 if ext4326.width() > 250 else (15 if ext4326.width() > 110 else 10))
        layers.append(gl)
        graticule_layer = True
    if st.show_countries:
        cty = QgsVectorLayer(COUNTRIES_PATH, "Country boundaries", "ogr")
        styling.style_countries(cty, selected, st.mask_outside, basemap is not None)
        layers.append(cty)
    if basemap is not None:
        layers.append(basemap)

    world = QgsVectorLayer(WORLD_PATH, "Locator world", "ogr")
    styling.style_world_inset(world)

    # ---- register in the project inside one group
    stamp = _slug(lo.title)[:40]
    root = project.layerTreeRoot()
    group = root.insertGroup(0, "Evidence Mapper – " + (lo.title[:50] or "map"))
    for lyr in layers + [world]:
        if project.mapLayer(lyr.id()) is None:
            project.addMapLayer(lyr, False)
    for lyr in layers:
        group.addLayer(lyr)
    world_node = group.addLayer(world)
    if world_node is not None:
        world_node.setItemVisibilityChecked(False)
        world_node.setExpanded(False)
    res.group = group

    # ---- layout
    ctx = Ctx()
    ctx.cfg, ctx.agg, ctx.locs = cfg, agg, locs
    ctx.map_layers = layers
    ctx.extent, ctx.ext4326, ctx.crs = extent, ext4326, crs
    ctx.colors, ctx.other_groups, ctx.vmax = colors, others, vmax
    ctx.choropleth_legend = legend_choro
    ctx.is_global = is_global
    ctx.basemap_attr = attr
    ctx.subtitle = default_subtitle(cfg, agg, sum(l.n_rows for l in locs) if outside else None)
    ctx.note = (format_unmapped_note(agg, lo.note_prefix) + " " + outside_note).strip()
    ctx.mixed_any = any(l.mixed for l in locs)
    ctx.world_layer = world
    ctx.single_group = single
    ctx.single_color = st.single_color
    ctx.graticule_in_layers = graticule_layer
    ctx.group_title = lo.group_title.strip().upper() or (cfg.data.group_field.upper() if cfg.data.group_field else "")

    name = "Evidence Map – " + (lo.title[:40] or "figure")
    mgr = project.layoutManager()
    base, n = name, 2
    while mgr.layoutByName(name):
        name = "%s (%d)" % (base, n)
        n += 1
    layout, w = build_layout(project, name, ctx)
    res.layout, res.layout_name = layout, name
    res.warnings.extend(w)

    # ---- export
    if out_dir and ex.formats:
        files, errs = export_layout(layout, out_dir, _slug(ex.base_name), ex.formats, ex.dpi)
        res.files.extend(files)
        res.warnings.extend(errs)
        if ex.save_data:
            csv_path = os.path.join(out_dir, _slug(ex.base_name) + "_locations.csv")
            _write_csv(csv_path, agg)
            res.files.append(csv_path)
            if gpkg:
                res.files.append(gpkg)

    res.caption = make_caption(cfg, agg, attr, choropleth)
    return res


def _write_csv(path, agg):
    import csv
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["ID", "Name", "Category", "Value", "Rows", "Mixed_categories", "Lon", "Lat"])
        for l in agg.locs:
            w.writerow([l.id or "", l.name, l.group, l.value, l.n_rows, int(l.mixed), round(l.lon, 5), round(l.lat, 5)])
        if agg.unmapped:
            w.writerow([])
            w.writerow(["Unmapped reason", "Rows"])
            for k, v in agg.unmapped.items():
                w.writerow([k, v])


def make_caption(cfg, agg, attr, choropleth):
    what = "Shading shows the number of included studies per %s." % (
        "state/province" if cfg.data.loc_mode == "admin1" else "country") if choropleth else \
        "Circle area is proportional to the number of included studies at each location; numbers refer to the key."
    s = "Figure X. %s %d of %d studies could be assigned to a mappable location (%d locations). %s" % (
        cfg.layout.title.rstrip("."), agg.rows_mapped, agg.total_rows, len(agg.locs), what)
    if agg.unmapped:
        s += " " + format_unmapped_note(agg, "Studies without a mappable location")
    s += " Boundaries: Natural Earth."
    if attr:
        s += " Basemap: %s." % attr
    return s
