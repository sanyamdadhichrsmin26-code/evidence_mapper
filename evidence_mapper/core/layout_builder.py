"""Builds the print layout: title, map, graticule, key, legends, scale bar, north
arrow, locator inset and the automatic footnotes."""
import math
import os

from qgis.PyQt.QtCore import QRectF, Qt
from qgis.PyQt.QtGui import QColor, QFont
from qgis.core import (
    QgsApplication, QgsCoordinateReferenceSystem, QgsFillSymbol, QgsLayoutItemLabel,
    QgsLayoutItemMap, QgsLayoutItemMapGrid, QgsLayoutItemMapOverview, QgsLayoutItemPicture,
    QgsLayoutItemScaleBar, QgsLayoutItemShape, QgsLayoutPoint, QgsLayoutSize, QgsPrintLayout,
    QgsRectangle, QgsUnitTypes, QgsLineSymbol, QgsLayoutMeasurement)

from .styling import size_for, legend_values, OTHER_COLOR

PAGES = {"A4": (210.0, 297.0), "A3": (297.0, 420.0), "A5": (148.0, 210.0),
         "Letter": (215.9, 279.4), "Legal": (215.9, 355.6)}

INK = "#222222"
GREY = "#555555"


def _fmt(v):
    return str(int(round(v))) if abs(v - round(v)) < 1e-9 else ("%.1f" % v)


def line_h(pt):
    return pt * 0.3528 * 1.36


def chars_fit(width_mm, pt):
    return max(4, int(width_mm / (pt * 0.3528 * 0.52)))


class Ctx:
    """Everything the layout needs, collected by the builder."""
    cfg = None
    agg = None
    locs = None
    map_layers = None
    extent = None            # QgsRectangle in `crs`
    ext4326 = None
    crs = None
    colors = None            # group -> hex
    other_groups = None
    vmax = 1.0
    choropleth_legend = None
    is_global = False
    basemap_attr = ""
    subtitle = ""
    note = ""
    mixed_any = False
    world_layer = None
    single_group = False
    single_color = "#3b6fb6"
    group_title = ""


# ------------------------------------------------------------------ primitives
def label(layout, text, x, y, w, h, pt=8, bold=False, italic=False, color=INK, h_align=Qt.AlignmentFlag.AlignLeft,
          v_align=Qt.AlignmentFlag.AlignVCenter, font="Arial"):
    lb = QgsLayoutItemLabel(layout)
    lb.setText(text)
    f = QFont(font)
    f.setPointSizeF(float(pt))
    f.setBold(bold)
    f.setItalic(italic)
    lb.setFont(f)
    lb.setFontColor(QColor(color))
    lb.setHAlign(h_align)
    lb.setVAlign(v_align)
    lb.setMargin(0)
    lb.attemptSetSceneRect(QRectF(x, y, w, h))
    layout.addLayoutItem(lb)
    return lb


def frame_box(layout, x, y, w, h, stroke="#333333", width=0.3, fill="255,255,255,0"):
    sh = QgsLayoutItemShape(layout)
    sh.setShapeType(QgsLayoutItemShape.Shape.Rectangle)
    sh.setSymbol(QgsFillSymbol.createSimple({"color": fill, "outline_color": stroke,
                                             "outline_width": str(width)}))
    sh.attemptSetSceneRect(QRectF(x, y, w, h))
    layout.addLayoutItem(sh)
    return sh


def circle(layout, cx, cy, d, fill, stroke="#2b2b2b", width=0.2):
    sh = QgsLayoutItemShape(layout)
    sh.setShapeType(QgsLayoutItemShape.Shape.Ellipse)
    sh.setSymbol(QgsFillSymbol.createSimple({"color": fill, "outline_color": stroke,
                                             "outline_width": str(width)}))
    sh.attemptSetSceneRect(QRectF(cx - d / 2.0, cy - d / 2.0, d, d))
    layout.addLayoutItem(sh)
    return sh


def swatch(layout, x, y, w, h, color, stroke="#555555"):
    sh = QgsLayoutItemShape(layout)
    sh.setShapeType(QgsLayoutItemShape.Shape.Rectangle)
    sh.setSymbol(QgsFillSymbol.createSimple({"color": color, "outline_color": stroke, "outline_width": "0.15"}))
    sh.attemptSetSceneRect(QRectF(x, y, w, h))
    layout.addLayoutItem(sh)


def _rgba(hexcol, a):
    c = QColor(hexcol)
    c.setAlphaF(a)
    return "%d,%d,%d,%d" % (c.red(), c.green(), c.blue(), c.alpha())


# ------------------------------------------------------------------ panel geometry
def groups_geom(ctx, w):
    n = len(ctx.colors) + (1 if ctx.other_groups else 0)
    ncol = 2 if (n > 6 and w >= 70) else 1
    rows = int(math.ceil(n / float(ncol))) if n else 0
    return ncol, rows, 6.0 + rows * 4.8 + 4.0


def sizes_height(ctx):
    st = ctx.cfg.style
    vals = legend_values(ctx.vmax, min(lc.value for lc in ctx.locs))
    big = max(size_for(v, ctx.vmax, st.max_size_mm, st.min_size_mm) for v in vals)
    return 6.0 + big + 6.5 + 2.0


def ramp_height(ctx):
    return 6.0 + (len(ctx.choropleth_legend or []) + 1) * 4.8 + 4.0


def key_height(ctx, n_rows_cap):
    lh = line_h(7.0)
    n = min(len(ctx.locs), ctx.cfg.layout.key_max_rows, n_rows_cap)
    extra = 1 if len(ctx.locs) > n else 0
    return 6.0 + (n + extra) * lh + 4.0


# ------------------------------------------------------------------ panel boxes
def box_key(layout, ctx, x, y, w, hmax, show_ids=True):
    lo = ctx.cfg.layout
    pt, font = 7.0, lo.font
    lh = line_h(pt)
    head_h = 6.0
    pad = 2.0
    locs = ctx.locs
    rows_fit = int((hmax - head_h - 2 * pad) // lh)
    n = max(0, min(len(locs), lo.key_max_rows, rows_fit))
    extra = len(locs) - n
    if extra > 0 and n > 1:           # keep one line for the "+ k more" note
        n -= 1
        extra = len(locs) - n
    rows_total = n + (1 if extra > 0 else 0)
    h = head_h + rows_total * lh + 2 * pad
    ctx_label = lo.key_title
    label(layout, ctx_label, x + pad, y + 1.2, w - 2 * pad, head_h - 1.2, pt=7.0, bold=True, font=font)
    id_w = 6.5 if show_ids else 0
    val_w = 8.5
    name_w = w - 2 * pad - id_w - val_w
    yy = y + head_h + pad - 0.5
    for lc in locs[:n]:
        if show_ids:
            label(layout, str(lc.id), x + pad, yy, id_w - 1.0, lh, pt=pt, bold=True, h_align=Qt.AlignmentFlag.AlignRight, font=font)
        nm = lc.name if len(lc.name) <= chars_fit(name_w, pt) else lc.name[:chars_fit(name_w, pt) - 1] + "…"
        label(layout, nm, x + pad + id_w, yy, name_w, lh, pt=pt, font=font)
        label(layout, _fmt(lc.value), x + w - pad - val_w, yy, val_w, lh, pt=pt, h_align=Qt.AlignmentFlag.AlignRight, font=font)
        yy += lh
    if extra > 0:
        rest = sum(lc.value for lc in locs[n:])
        label(layout, "+ %d more locations (%s)" % (extra, _fmt(rest)), x + pad + id_w, yy, w - 2 * pad - id_w,
              lh, pt=pt, italic=True, color=GREY, font=font)
    frame_box(layout, x, y, w, h)
    return h


def box_groups(layout, ctx, x, y, w):
    lo = ctx.cfg.layout
    font = lo.font
    items = [(g, c) for g, c in ctx.colors.items()]
    if ctx.other_groups:
        items.append(("Other (%d categories)" % len(ctx.other_groups), OTHER_COLOR))
    head_h, pad, row_h = 6.0, 2.0, 4.8
    ncol, rows, h = groups_geom(ctx, w)
    label(layout, ctx.group_title, x + pad, y + 1.2, w - 2 * pad, head_h - 1.2, pt=7.0, bold=True, font=font)
    col_w = (w - 2 * pad) / ncol
    for i, (g, c) in enumerate(items):
        col, row = divmod(i, rows)
        cx = x + pad + col * col_w
        cy = y + head_h + pad + row * row_h
        circle(layout, cx + 2.0, cy + row_h / 2.0 - 0.3, 3.4, _rgba(c, ctx.cfg.style.fill_opacity))
        txt = g if len(g) <= chars_fit(col_w - 6, 7) else g[:chars_fit(col_w - 6, 7) - 1] + "…"
        label(layout, txt, cx + 5.0, cy - 0.3, col_w - 5.5, row_h, pt=7.0, font=font)
    frame_box(layout, x, y, w, h)
    return h


def box_ramp(layout, ctx, x, y, w):
    lo = ctx.cfg.layout
    font = lo.font
    items = list(ctx.choropleth_legend or []) + [("No data", "#ffffff")]
    head_h, pad, row_h = 6.0, 2.0, 4.8
    h = head_h + len(items) * row_h + 2 * pad
    label(layout, "NUMBER OF STUDIES", x + pad, y + 1.2, w - 2 * pad, head_h - 1.2, pt=7.0, bold=True, font=font)
    for i, (txt, col) in enumerate(items):
        cy = y + head_h + pad + i * row_h
        swatch(layout, x + pad, cy, 6.0, row_h - 1.0, col)
        label(layout, txt, x + pad + 8.0, cy - 0.5, w - 2 * pad - 8.0, row_h, pt=7.0, font=font)
    frame_box(layout, x, y, w, h)
    return h


def box_sizes(layout, ctx, x, y, w):
    st, lo = ctx.cfg.style, ctx.cfg.layout
    font = lo.font
    vals = legend_values(ctx.vmax, min(lc.value for lc in ctx.locs))
    sizes = [size_for(v, ctx.vmax, st.max_size_mm, st.min_size_mm) for v in vals]
    pad = 2.0
    while len(vals) > 2 and sum(sizes) + 5 * (len(sizes) - 1) + 2 * pad > w:
        vals.pop(len(vals) // 2)
        sizes.pop(len(sizes) // 2)
    head_h = 6.0
    big = max(sizes)
    h = head_h + big + 6.5 + pad
    label(layout, lo.size_legend_title, x + pad, y + 1.2, w - 2 * pad, head_h - 1.2, pt=7.0, bold=True, font=font)
    total = sum(sizes) + 5 * (len(sizes) - 1)
    cx = x + (w - total) / 2.0
    base = y + head_h + big + 0.5
    for v, d in zip(vals, sizes):
        circle(layout, cx + d / 2.0, base - d / 2.0, d, _rgba("#9a9a9a", 0.35), stroke="#2b2b2b", width=0.25)
        label(layout, _fmt(v), cx + d / 2.0 - 7, base + 0.8, 14, 4.5, pt=7.0, h_align=Qt.AlignmentFlag.AlignHCenter, font=font)
        cx += d + 5
    frame_box(layout, x, y, w, h)
    return h


def box_inset(layout, ctx, main_map, x, y, w, h_fixed=None):
    """Locator map: world with a red frame showing the mapped area."""
    world = QgsCoordinateReferenceSystem("ESRI:54030")
    from qgis.core import QgsCoordinateTransform, QgsProject
    tr = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:4326"), world, QgsProject.instance())
    ext = tr.transformBoundingBox(QgsRectangle(-180, -58, 180, 84))
    h = h_fixed or (w * ext.height() / ext.width())
    inset = QgsLayoutItemMap(layout)
    inset.attemptSetSceneRect(QRectF(x, y, w, h))
    layout.addLayoutItem(inset)
    inset.setCrs(world)
    inset.setLayers([ctx.world_layer])
    inset.setKeepLayerSet(True)
    inset.setExtent(ext)
    inset.setBackgroundColor(QColor("#ffffff"))
    inset.setFrameEnabled(True)
    inset.setFrameStrokeWidth(QgsLayoutMeasurement(0.3))
    ov = QgsLayoutItemMapOverview("Locator", inset)
    inset.overviews().addOverview(ov)
    ov.setLinkedMap(main_map)
    ov.setFrameSymbol(QgsFillSymbol.createSimple({"color": "214,39,40,60", "outline_color": "#d62728",
                                                  "outline_width": "0.5"}))
    return h


# ------------------------------------------------------------------ main entry
def nice_interval(span_deg):
    for v in (0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 20, 30, 45):
        if span_deg / v <= 5.5:
            return v
    return 45


def add_graticule(main_map, ext4326, font, warnings):
    try:
        g = QgsLayoutItemMapGrid("Graticule", main_map)
        main_map.grids().addGrid(g)
        g.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
        iv = nice_interval(min(ext4326.width(), ext4326.height() * 1.0) * 1.15)
        g.setIntervalX(iv)
        g.setIntervalY(iv)
        g.setStyle(QgsLayoutItemMapGrid.GridStyle.Solid)
        g.setLineSymbol(QgsLineSymbol.createSimple({"line_color": "120,120,120,110", "line_width": "0.12"}))
        g.setFrameStyle(QgsLayoutItemMapGrid.FrameStyle.NoFrame)
        g.setAnnotationEnabled(True)
        f = QFont(font)
        f.setPointSizeF(6.5)
        g.setAnnotationFont(f)
        g.setAnnotationFormat(QgsLayoutItemMapGrid.AnnotationFormat.DecimalWithSuffix)
        g.setAnnotationPrecision(0 if iv >= 1 else (1 if iv >= 0.1 else 2))
        for side, direction, mode in (
                (QgsLayoutItemMapGrid.BorderSide.Left, QgsLayoutItemMapGrid.AnnotationDirection.Vertical, QgsLayoutItemMapGrid.DisplayMode.LatitudeOnly),
                (QgsLayoutItemMapGrid.BorderSide.Bottom, QgsLayoutItemMapGrid.AnnotationDirection.Horizontal, QgsLayoutItemMapGrid.DisplayMode.LongitudeOnly),
                (QgsLayoutItemMapGrid.BorderSide.Top, QgsLayoutItemMapGrid.AnnotationDirection.Horizontal, QgsLayoutItemMapGrid.DisplayMode.LongitudeOnly),
                (QgsLayoutItemMapGrid.BorderSide.Right, QgsLayoutItemMapGrid.AnnotationDirection.Vertical, QgsLayoutItemMapGrid.DisplayMode.LatitudeOnly)):
            g.setAnnotationDisplay(mode, side)
            g.setAnnotationPosition(QgsLayoutItemMapGrid.AnnotationPosition.OutsideMapFrame, side)
            g.setAnnotationDirection(direction, side)
        g.setAnnotationFrameDistance(1.2)
        g.setEnabled(True)
    except Exception as exc:                          # graticule is cosmetic: never fatal
        warnings.append("Graticule could not be created (%s)." % exc)


def find_north_arrow():
    return ":/images/north_arrows/layout_default_north_arrow.svg"


def _find_north_arrow_svg():
    for base in QgsApplication.svgPaths():
        p = os.path.join(base, "arrows", "NorthArrow_02.svg")
        if os.path.exists(p):
            return p
        p = os.path.join(base, "arrows", "NorthArrow_04.svg")
        if os.path.exists(p):
            return p
    return ":/images/north_arrows/layout_default_north_arrow.svg"


def build_layout(project, name, ctx):
    lo, st = ctx.cfg.layout, ctx.cfg.style
    warnings = []
    font = lo.font

    layout = QgsPrintLayout(project)
    layout.initializeDefaults()
    layout.setName(name)
    project.layoutManager().addLayout(layout)

    pw, ph = PAGES.get(lo.page, PAGES["A4"])
    W, H = (max(pw, ph), min(pw, ph)) if lo.orientation == "landscape" else (min(pw, ph), max(pw, ph))
    layout.pageCollection().page(0).setPageSize(QgsLayoutSize(W, H, QgsUnitTypes.LayoutUnit.LayoutMillimeters))

    m = lo.margin_mm
    title_h, sub_h = 8.5, 5.0
    y_top = m + title_h + sub_h + 1.5
    has_footer = lo.show_note or lo.show_source
    footer_h = 11.0 if has_footer else 0.0
    y_bot = H - m - footer_h - (2.0 if has_footer else 0.0)
    ann = 6.5 if st.graticule else 1.5
    gap = 5.0

    choropleth = st.map_style == "choropleth"
    show_panel = lo.panel != "none" and (lo.show_key or lo.show_groups or lo.show_size_legend or lo.show_inset)
    right = show_panel and lo.panel == "right"
    bottom = show_panel and lo.panel == "bottom"
    panel_w = 0.285 * W if right else 0.0
    panel_h = min(80.0, 0.30 * (y_bot - y_top)) if bottom else 0.0

    avail_w = (W - 2 * m) - (panel_w + gap if right else 0) - 2 * ann
    avail_h = (y_bot - y_top) - 2 * ann - (panel_h + gap if bottom else 0)
    ext = QgsRectangle(ctx.extent)
    r = ext.width() / ext.height()
    mw = min(avail_w, avail_h * r)
    mh = mw / r
    total_w = mw + 2 * ann + ((gap + panel_w) if right else 0)
    x0 = m + ((W - 2 * m) - total_w) / 2.0
    mx, my = x0 + ann, y_top + ann

    # ---- title & subtitle
    label(layout, lo.title, m, m, W - 2 * m, title_h, pt=14, bold=True, font=font)
    label(layout, ctx.subtitle, m, m + title_h, W - 2 * m, sub_h, pt=8, color=GREY, font=font)

    # ---- main map
    mp = QgsLayoutItemMap(layout)
    mp.attemptSetSceneRect(QRectF(mx, my, mw, mh))
    layout.addLayoutItem(mp)
    mp.setCrs(ctx.crs)
    mp.setLayers(ctx.map_layers)
    mp.setKeepLayerSet(True)
    mp.setBackgroundColor(QColor(st.background))
    mp.setBackgroundEnabled(True)
    mp.zoomToExtent(ext)
    mp.setFrameEnabled(True)
    mp.setFrameStrokeWidth(QgsLayoutMeasurement(0.35))
    mp.setFrameStrokeColor(QColor("#222222"))
    if st.graticule and not getattr(ctx, 'graticule_in_layers', False):
        add_graticule(mp, ctx.ext4326, font, warnings)

    # ---- scale bar
    if lo.show_scale_bar:
        try:
            sb = QgsLayoutItemScaleBar(layout)
            sb.setLinkedMap(mp)
            sb.setUnits(QgsUnitTypes.DistanceUnit.DistanceKilometers)
            sb.setUnitLabel("km")
            sb.setStyle("Single Box")
            sb.applyDefaultSize(QgsUnitTypes.DistanceUnit.DistanceKilometers)
            sb.setNumberOfSegmentsLeft(0)
            f = QFont(font)
            f.setPointSizeF(7)
            sb.setFont(f)
            sb.setBackgroundEnabled(True)
            sb.setBackgroundColor(QColor(255, 255, 255, 190))
            layout.addLayoutItem(sb)
            sb.attemptMove(QgsLayoutPoint(mx + 2.0, my + mh - 2.0 - sb.rect().height(),
                                          QgsUnitTypes.LayoutUnit.LayoutMillimeters))
        except Exception as exc:
            warnings.append("Scale bar could not be created (%s)." % exc)

    # ---- north arrow
    if lo.show_north_arrow:
        try:
            na = QgsLayoutItemPicture(layout)
            na.setPicturePath(find_north_arrow())
            na.setLinkedMap(mp)
            na.setNorthMode(QgsLayoutItemPicture.NorthMode.GridNorth)
            na.attemptSetSceneRect(QRectF(mx + mw - 13.0, my + 2.0, 11.0, 13.0))
            layout.addLayoutItem(na)
        except Exception as exc:
            warnings.append("North arrow could not be created (%s)." % exc)

    # ---- panels
    if show_panel:
        if right:
            px = mx + mw + ann + gap
            py = y_top
            avail = y_bot - y_top
            inset_h = panel_w * 0.40
            use_inset = lo.show_inset and not ctx.is_global
            # wide maps leave free space under the map: put the legends there
            by = my + mh + ann + 2.0
            free_below = y_bot - by
            half_w = (mw - 3.0) / 2.0
            if choropleth:
                legend_items = [("ramp", ramp_height(ctx), half_w)]
            else:
                legend_items = []
                if lo.show_groups and not ctx.single_group:
                    legend_items.append(("groups", groups_geom(ctx, half_w)[2], half_w))
                if lo.show_size_legend:
                    legend_items.append(("sizes", sizes_height(ctx), half_w))
            below = bool(legend_items) and len(legend_items) <= 2 and \
                max(h for _, h, _ in legend_items) <= free_below
            if below:
                bx = mx
                for kind, hh, ww in legend_items:
                    if kind == "ramp":
                        box_ramp(layout, ctx, bx, by, ww)
                    elif kind == "groups":
                        box_groups(layout, ctx, bx, by, ww)
                    else:
                        box_sizes(layout, ctx, bx, by, ww)
                    bx += ww + 3.0
                other_h = []
            else:
                other_h = [h for _, h, _ in legend_items]
            show_key = lo.show_key and bool(ctx.locs)

            def need(with_inset):
                parts = list(other_h)
                if with_inset:
                    parts.append(inset_h)
                if show_key:
                    parts.append(key_height(ctx, 10 ** 6))
                return sum(parts) + 3.0 * max(0, len(parts) - 1)
            corner_inset = False
            if use_inset and need(True) > avail:
                use_inset = False
                corner_inset = True          # fall back to a small inset inside the map corner
            yy = py
            if use_inset:
                yy += box_inset(layout, ctx, mp, px, yy, panel_w, inset_h) + 3.0
            if show_key:
                reserve = sum(other_h) + 3.0 * len(other_h)
                hmax = max(18.0, avail - (yy - py) - reserve)
                yy += box_key(layout, ctx, px, yy, panel_w, hmax, show_ids=not choropleth) + 3.0
            if corner_inset:
                iw = max(30.0, 0.30 * mw)
                ih = iw * 0.5
                box_inset(layout, ctx, mp, mx + mw - iw - 2.0, my + mh - ih - 2.0, iw, ih)
            if not below:
                for kind, hh, ww in legend_items:
                    if kind == "ramp":
                        yy += box_ramp(layout, ctx, px, yy, panel_w) + 3.0
                    elif kind == "groups":
                        yy += box_groups(layout, ctx, px, yy, panel_w) + 3.0
                    else:
                        yy += box_sizes(layout, ctx, px, yy, panel_w) + 3.0
            if yy - 3.0 > y_bot + 0.5:
                warnings.append("The side panel is taller than the page; reduce 'Key rows', the category "
                                "count or the circle size, or use a larger page.")
        else:  # bottom panel
            px, py = m, my + mh + ann + gap
            wtot = W - 2 * m
            n_cols = 3 if (lo.show_inset and not ctx.is_global) else 2
            key_w = wtot * (0.42 if n_cols == 3 else 0.5)
            mid_w = wtot * (0.30 if n_cols == 3 else 0.5) - gap
            ins_w = wtot - key_w - mid_w - 2 * gap if n_cols == 3 else 0
            cx = px
            if lo.show_key and ctx.locs:
                box_key(layout, ctx, cx, py, key_w - gap, panel_h, show_ids=not choropleth)
            cx += key_w
            yy = py
            if choropleth:
                yy += box_ramp(layout, ctx, cx, yy, mid_w) + 3
            else:
                if lo.show_groups and not ctx.single_group:
                    yy += box_groups(layout, ctx, cx, yy, mid_w) + 3
                if lo.show_size_legend:
                    box_sizes(layout, ctx, cx, yy, mid_w)
            if n_cols == 3:
                box_inset(layout, ctx, mp, cx + mid_w + gap, py, ins_w)

    # ---- footer
    fy = H - m - footer_h
    if lo.show_note and ctx.note:
        label(layout, ctx.note, m, fy, W - 2 * m, 5.5, pt=6.5, italic=True, color=INK, font=font,
              v_align=Qt.AlignmentFlag.AlignTop)
        fy += 5.0
    if lo.show_source:
        src = []
        if ctx.basemap_attr:
            src.append("Basemap: " + ctx.basemap_attr + ".")
        src.append("Boundaries: Natural Earth (public domain).")
        if ctx.mixed_any and not ctx.single_group:
            src.append("Where a location has studies in several categories, the most frequent one sets the colour.")
        src.append("Scale bar is valid at the map centre.")
        label(layout, " ".join(src), m, fy, W - 2 * m, 5.5, pt=5.5, color=GREY, font=font, v_align=Qt.AlignmentFlag.AlignTop)
    return layout, warnings
