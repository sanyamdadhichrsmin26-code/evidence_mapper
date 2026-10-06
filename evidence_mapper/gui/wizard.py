"""Step-by-step wizard: data -> fields -> area -> look -> layout & export."""
import json
import os
import shutil
import traceback

from qgis.PyQt.QtCore import Qt, QSettings
from qgis.PyQt.QtGui import QFont, QColor
from qgis.PyQt.QtWidgets import (
    QWizard, QWizardPage, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout, QLabel, QRadioButton,
    QComboBox, QPushButton, QCheckBox, QSpinBox, QDoubleSpinBox, QLineEdit, QListWidget, QListWidgetItem,
    QTableWidget, QTableWidgetItem, QGroupBox, QFileDialog, QMessageBox, QProgressDialog, QApplication,
    QSlider, QScrollArea, QWidget, QDialog, QPlainTextEdit, QDialogButtonBox, QButtonGroup, QFontComboBox,
    QAbstractItemView, QHeaderView)
from qgis.core import (QgsProject, QgsMapLayerProxyModel, QgsCoordinateReferenceSystem, QgsCoordinateTransform)
from qgis.gui import QgsFileWidget, QgsMapLayerComboBox, QgsColorButton, QgsProjectionSelectionWidget

from ..core import tables
from ..core.util import log
from ..core.aggregate import aggregate
from ..core.basemaps import BASEMAPS
from ..core.builder import build_map, get_gazetteer
from ..core.gazetteer import REGIONS
from ..core.geocode import Geocoder
from ..core.layout_builder import PAGES
from ..core.models import MapConfig
from ..core.styling import PALETTES, RAMPS

NONE = "— none —"
PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_KEY = "EvidenceMapper/last_config"


def _combo(items=None):
    c = QComboBox()
    for it in items or []:
        c.addItem(it)
    return c


def _hint(text):
    lb = QLabel(text)
    lb.setWordWrap(True)
    lb.setStyleSheet("color: #666;")
    return lb


class _Page(QWizardPage):
    def __init__(self, wiz, title, subtitle=""):
        super().__init__()
        self.wiz = wiz
        self.setTitle(title)
        self.setSubTitle(subtitle)

    def collect(self, cfg):
        pass

    def restore(self, cfg):
        pass


# =============================================================== 1. data
class DataPage(_Page):
    def __init__(self, wiz):
        super().__init__(wiz, "1 · Your data",
                         "One row per study (recommended) or one row per place with a count column.")
        lay = QVBoxLayout(self)
        self.r_file = QRadioButton("A file: CSV, TSV, Excel (.xlsx), OpenDocument (.ods), GeoPackage, Shapefile, GeoJSON")
        self.r_layer = QRadioButton("A layer that is already open in this QGIS project")
        self.r_file.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.r_file)
        grp.addButton(self.r_layer)
        self.file = QgsFileWidget()
        self.file.setFilter("Data files (*.csv *.tsv *.txt *.xlsx *.ods *.gpkg *.shp *.geojson *.json);;All files (*)")
        self.sheet = _combo()
        self.sheet.setVisible(False)
        self.layer = QgsMapLayerComboBox()
        self.layer.setFilters(QgsMapLayerProxyModel.Filter.VectorLayer)
        self.layer.setEnabled(False)
        lay.addWidget(self.r_file)
        lay.addWidget(self.file)
        row = QHBoxLayout()
        row.addWidget(QLabel("Worksheet / layer:"))
        row.addWidget(self.sheet, 1)
        self.sheet_row = QWidget()
        self.sheet_row.setLayout(row)
        self.sheet_row.setVisible(False)
        lay.addWidget(self.sheet_row)
        lay.addWidget(self.r_layer)
        lay.addWidget(self.layer)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.preview = QTableWidget()
        self.preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        lay.addWidget(self.preview, 1)
        b = QPushButton("Save an example CSV template…")
        b.clicked.connect(self.save_template)
        lay.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)

        self.r_file.toggled.connect(self._toggle)
        self.file.fileChanged.connect(self._file_changed)
        self.sheet.currentIndexChanged.connect(lambda *_: self.load())
        self.layer.layerChanged.connect(lambda *_: self.load())

    def _toggle(self):
        use_file = self.r_file.isChecked()
        self.file.setEnabled(use_file)
        self.layer.setEnabled(not use_file)
        self.load()

    def _file_changed(self, path):
        self.sheet.blockSignals(True)
        self.sheet.clear()
        subs = tables.list_sublayers(path) if path else []
        for s in subs:
            self.sheet.addItem(s)
        self.sheet.blockSignals(False)
        self.sheet_row.setVisible(bool(subs))
        self.load()

    def source(self):
        if self.r_file.isChecked():
            return self.file.filePath().strip()
        lyr = self.layer.currentLayer()
        return "layer:" + lyr.id() if lyr else ""

    def load(self):
        src = self.source()
        self.wiz.table = None
        self.wiz.agg = None
        self.preview.clear()
        self.preview.setRowCount(0)
        self.preview.setColumnCount(0)
        if src:
            try:
                sheet = self.sheet.currentText() if (self.r_file.isChecked() and self.sheet_row.isVisible()) else ""
                t = tables.load_table(src, sheet)
                if not t.rows:
                    raise ValueError("The table has no data rows.")
                self.wiz.table = t
                self.info.setText("<b>%d rows</b>, %d columns. First rows:" % (len(t), len(t.fields)))
                self.info.setStyleSheet("")
                self.preview.setColumnCount(len(t.fields))
                self.preview.setHorizontalHeaderLabels(t.fields)
                n = min(8, len(t))
                self.preview.setRowCount(n)
                for i in range(n):
                    for j, f in enumerate(t.fields):
                        self.preview.setItem(i, j, QTableWidgetItem(str(t.rows[i].get(f, ""))))
                self.preview.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            except Exception as exc:
                self.info.setText("⚠ %s" % exc)
                self.info.setStyleSheet("color:#b00020;")
        else:
            self.info.setText("")
        self.completeChanged.emit()

    def isComplete(self):
        return self.wiz.table is not None

    def save_template(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save template", "studies_template.csv", "CSV (*.csv)")
        if path:
            shutil.copy(os.path.join(PLUGIN_DIR, "sample_data", "TEMPLATE_studies.csv"), path)

    def collect(self, cfg):
        cfg.data.source = self.source()
        cfg.data.sheet = self.sheet.currentText() if self.sheet_row.isVisible() else ""

    def restore(self, cfg):
        s = cfg.data.source
        if s and not s.startswith("layer:") and os.path.exists(s):
            self.r_file.setChecked(True)
            self.file.setFilePath(s)


# =============================================================== 2. fields
MODES = [("latlon", "Latitude / longitude columns"),
         ("country", "Country names or ISO codes"),
         ("admin1", "State / province names"),
         ("place", "Place names (geocoded online with OpenStreetMap Nominatim)"),
         ("geometry", "Use the geometry of the layer (points / polygon centroids)")]


class FieldsPage(_Page):
    def __init__(self, wiz):
        super().__init__(wiz, "2 · Tell the plugin what your columns mean")
        lay = QVBoxLayout(self)
        self.mode = QComboBox()
        for k, t in MODES:
            self.mode.addItem(t, k)
        form = QFormLayout()
        form.addRow("Locations are given as:", self.mode)
        self.f = {n: _combo() for n in ("lat", "lon", "country", "admin1", "place", "name", "group", "value")}
        self.rows = {}
        labels = {"lat": "Latitude column", "lon": "Longitude column", "country": "Country column",
                  "admin1": "State / province column", "place": "Place-name column",
                  "name": "Label for the key (optional)", "group": "Colour categories (optional)",
                  "value": "Numeric column"}
        self.val_mode = _combo(["Count rows – each row is one study", "Sum a numeric column (e.g. studies per place)"])
        form.addRow("Each location's size is:", self.val_mode)
        for k in ("lat", "lon", "country", "admin1", "place"):
            lb = QLabel(labels[k])
            form.addRow(lb, self.f[k])
            self.rows[k] = (lb, self.f[k])
        for k in ("value", "name", "group"):
            lb = QLabel(labels[k])
            form.addRow(lb, self.f[k])
            self.rows[k] = (lb, self.f[k])
        lay.addLayout(form)
        self.split = QCheckBox("Split cells such as “India; Kenya” (separated by ; or |) – the study counts for each place")
        self.split.setChecked(True)
        self.geo = QCheckBox("Allow online geocoding (results are cached; 1 request/second as required by Nominatim)")
        self.geo.setChecked(True)
        lay.addWidget(self.split)
        lay.addWidget(self.geo)
        self.check_btn = QPushButton("Check mapping")
        self.check_btn.clicked.connect(lambda: self.run_check(True))
        lay.addWidget(self.check_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.report = QLabel("")
        self.report.setWordWrap(True)
        self.report.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.report)
        self.result = QTableWidget()
        self.result.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        lay.addWidget(self.result, 1)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.val_mode.currentIndexChanged.connect(self._mode_changed)
        self._sig = None

    # ---- helpers
    def initializePage(self):
        t = self.wiz.table
        names = [NONE] + t.fields
        for k, c in self.f.items():
            c.blockSignals(True)
            c.clear()
            c.addItems(names if k not in ("lat", "lon", "country", "admin1", "place") else names)
            c.blockSignals(False)
        self.mode.model().item(4).setEnabled(t.points is not None)
        self._autodetect(t)
        self._mode_changed()
        self.report.setText("")
        self.result.clear()
        self.result.setRowCount(0)
        self.wiz.agg = None
        self._sig = None

    def _find(self, fields, words):
        low = {f.lower().replace(" ", "").replace("_", ""): f for f in fields}
        for w in words:
            if w in low:
                return low[w]
        for w in words:
            for k, f in low.items():
                if w in k:
                    return f
        return None

    def _set(self, key, field):
        if field:
            self.f[key].setCurrentText(field)

    def _autodetect(self, t):
        F = t.fields
        lat = self._find(F, ["latitude", "lat", "ycoord", "y"])
        lon = self._find(F, ["longitude", "lon", "lng", "long", "xcoord", "x"])
        ctry = self._find(F, ["country", "nation", "countries"])
        adm = self._find(F, ["state", "province", "admin1", "region"])
        place = self._find(F, ["place", "city", "town", "locality", "site", "location"])
        self._set("lat", lat); self._set("lon", lon); self._set("country", ctry)
        self._set("admin1", adm); self._set("place", place)
        self._set("name", self._find(F, ["coalfield", "sitename", "name", "site", "place", "location"]))
        self._set("group", self._find(F, ["group", "category", "basin", "design", "type", "class", "setting"]))
        nums = t.numeric_fields()
        self._set("value", self._find(nums, ["studies", "count", "number", "n", "value"]) or (nums[0] if nums else None))
        if lat and lon:
            self.mode.setCurrentIndex(0)
        elif ctry:
            self.mode.setCurrentIndex(1)
        elif t.points is not None:
            self.mode.setCurrentIndex(4)
        elif place:
            self.mode.setCurrentIndex(3)

    def _mode_changed(self):
        m = self.mode.currentData()
        show = {"lat": m == "latlon", "lon": m == "latlon",
                "country": m in ("country", "admin1", "place"),
                "admin1": m == "admin1", "place": m == "place",
                "value": self.val_mode.currentIndex() == 1, "name": True, "group": True}
        for k, (lb, w) in self.rows.items():
            lb.setVisible(show[k])
            w.setVisible(show[k])
        self.split.setVisible(m in ("country", "admin1"))
        self.geo.setVisible(m == "place")
        if m == "country":
            self.rows["country"][0].setText("Country column")
        elif m in ("admin1", "place"):
            self.rows["country"][0].setText("Country column (optional – improves matching)")
        self.wiz.agg = None

    def _val(self, key):
        v = self.f[key].currentText()
        return "" if v == NONE else v

    def data_options(self, cfg):
        d = cfg.data
        d.loc_mode = self.mode.currentData()
        d.lat_field, d.lon_field = self._val("lat"), self._val("lon")
        d.country_field, d.admin1_field, d.place_field = self._val("country"), self._val("admin1"), self._val("place")
        d.name_field, d.group_field = self._val("name"), self._val("group")
        d.value_mode = "sum" if self.val_mode.currentIndex() == 1 else "count"
        d.value_field = self._val("value") if d.value_mode == "sum" else ""
        d.split_multi = self.split.isChecked()
        d.geocode = self.geo.isChecked()
        return d

    def _required_ok(self, d):
        need = {"latlon": [d.lat_field, d.lon_field], "country": [d.country_field],
                "admin1": [d.admin1_field], "place": [d.place_field], "geometry": ["x"]}[d.loc_mode]
        if not all(need):
            QMessageBox.warning(self, "Evidence Mapper", "Please choose the column(s) that hold the locations.")
            return False
        if d.value_mode == "sum" and not d.value_field:
            QMessageBox.warning(self, "Evidence Mapper", "Please choose the numeric column to sum.")
            return False
        return True

    def run_check(self, interactive):
        cfg = MapConfig()
        d = self.data_options(cfg)
        if not self._required_ok(d):
            return False
        prog = QProgressDialog("Matching locations…", "Cancel", 0, 100, self)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(400)
        cancelled = {"v": False}

        def cb(i, n, text):
            prog.setMaximum(max(1, n))
            prog.setValue(i)
            prog.setLabelText(text)
            QApplication.processEvents()
            if prog.wasCanceled():
                cancelled["v"] = True

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            agg = aggregate(self.wiz.table, d, get_gazetteer(), Geocoder() if d.loc_mode == "place" and d.geocode else None,
                            cb, lambda: cancelled["v"])
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            prog.close()
            QMessageBox.warning(self, "Evidence Mapper", str(exc))
            return False
        QApplication.restoreOverrideCursor()
        prog.close()
        self.wiz.agg = agg
        self._sig = json.dumps(d.__dict__, sort_keys=True, default=str)
        self._show(agg)
        self.completeChanged.emit()
        return True

    def _show(self, agg):
        pct = 100.0 * agg.rows_mapped / max(1, agg.total_rows)
        txt = "<b>%d of %d rows (%.0f%%)</b> placed on %d location(s)." % (
            agg.rows_mapped, agg.total_rows, pct, len(agg.locs))
        if agg.unmapped:
            txt += "<br><b>Not mappable:</b> " + "; ".join("%s (n = %d)" % kv for kv in agg.unmapped.most_common(8))
            if len(agg.unmapped) > 8:
                txt += "; …"
        for m in agg.messages:
            txt += "<br><i>%s</i>" % m
        self.report.setText(txt)
        self.result.clear()
        self.result.setColumnCount(4)
        self.result.setHorizontalHeaderLabels(["#", "Location", "Category", "Value"])
        self.result.setRowCount(len(agg.locs))
        for i, lc in enumerate(agg.locs):
            vals = [str(lc.id), lc.name, lc.group, ("%g" % lc.value)]
            for j, v in enumerate(vals):
                self.result.setItem(i, j, QTableWidgetItem(v))
        self.result.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

    def validatePage(self):
        cfg = MapConfig()
        d = self.data_options(cfg)
        if not self._required_ok(d):
            return False
        sig = json.dumps(d.__dict__, sort_keys=True, default=str)
        if self.wiz.agg is None or sig != self._sig:
            if not self.run_check(False):
                return False
        if not self.wiz.agg.locs:
            QMessageBox.warning(self, "Evidence Mapper",
                                "No row could be placed on the map. Check the columns above and the report.")
            return False
        return True

    def isComplete(self):
        return True

    def collect(self, cfg):
        self.data_options(cfg)

    def restore(self, cfg):
        d = cfg.data
        i = self.mode.findData(d.loc_mode)
        if i >= 0:
            self.mode.setCurrentIndex(i)
        for key, val in (("lat", d.lat_field), ("lon", d.lon_field), ("country", d.country_field),
                         ("admin1", d.admin1_field), ("place", d.place_field), ("name", d.name_field),
                         ("group", d.group_field), ("value", d.value_field)):
            if val and self.f[key].findText(val) >= 0:
                self.f[key].setCurrentText(val)
        self.val_mode.setCurrentIndex(1 if d.value_mode == "sum" else 0)
        self.split.setChecked(d.split_multi)
        self.geo.setChecked(d.geocode)


# =============================================================== 3. area
class AreaPage(_Page):
    def __init__(self, wiz):
        super().__init__(wiz, "3 · Where should the map focus?",
                         "Choose the whole world, a region, one or more countries, or let the plugin fit your data.")
        gaz = get_gazetteer()
        lay = QVBoxLayout(self)
        self.g_global = QRadioButton("Global")
        self.g_region = QRadioButton("A world region")
        self.g_countries = QRadioButton("One or more countries")
        self.g_data = QRadioButton("Fit the extent to my data")
        self.g_custom = QRadioButton("Custom bounding box")
        self.group = QButtonGroup(self)
        for i, rb in enumerate((self.g_global, self.g_region, self.g_countries, self.g_data, self.g_custom)):
            self.group.addButton(rb, i)
        self.g_global.setChecked(True)
        lay.addWidget(self.g_global)
        self.antarctica = QCheckBox("Exclude Antarctica")
        self.antarctica.setChecked(True)
        lay.addWidget(self.antarctica)
        lay.addWidget(self.g_region)
        self.region = _combo([r for r in REGIONS if not r.startswith("World")])
        lay.addWidget(self.region)
        lay.addWidget(self.g_countries)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Type to filter countries…")
        self.clist = QListWidget()
        self.clist.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        for name, a3 in gaz.country_choices():
            it = QListWidgetItem(name)
            it.setData(Qt.ItemDataRole.UserRole, a3)
            self.clist.addItem(it)
        self.clist.setMaximumHeight(150)
        self.terr = QCheckBox("Include distant islands / overseas territories in the extent")
        lay.addWidget(self.filter)
        lay.addWidget(self.clist)
        lay.addWidget(self.terr)
        lay.addWidget(self.g_custom)
        grid = QGridLayout()
        self.bb = [QDoubleSpinBox() for _ in range(4)]
        for sp, (lo, hi) in zip(self.bb, ((-180, 180), (-90, 90), (-180, 180), (-90, 90))):
            sp.setRange(lo, hi)
            sp.setDecimals(3)
        for i, (t, sp) in enumerate(zip(("West", "South", "East", "North"), self.bb)):
            grid.addWidget(QLabel(t), 0, i)
            grid.addWidget(sp, 1, i)
        lay.addLayout(grid)
        self.canvas_btn = QPushButton("Use current map canvas extent")
        lay.addWidget(self.canvas_btn, 0, Qt.AlignmentFlag.AlignLeft)
        self.filter.textChanged.connect(self._filter)
        self.canvas_btn.clicked.connect(self._canvas_extent)
        self.group.buttonClicked.connect(lambda *_: self._enable())
        self._enable()

    def _filter(self, text):
        t = text.lower()
        for i in range(self.clist.count()):
            self.clist.item(i).setHidden(t not in self.clist.item(i).text().lower())

    def _enable(self):
        m = self.group.checkedId()
        self.antarctica.setEnabled(m == 0)
        self.region.setEnabled(m == 1)
        for w in (self.filter, self.clist, self.terr):
            w.setEnabled(m == 2)
        for w in self.bb + [self.canvas_btn]:
            w.setEnabled(m == 4)

    def _canvas_extent(self):
        from qgis.utils import iface
        if iface is None:
            return
        c = iface.mapCanvas()
        tr = QgsCoordinateTransform(c.mapSettings().destinationCrs(), QgsCoordinateReferenceSystem("EPSG:4326"),
                                    QgsProject.instance())
        r = tr.transformBoundingBox(c.extent())
        for sp, v in zip(self.bb, (r.xMinimum(), r.yMinimum(), r.xMaximum(), r.yMaximum())):
            sp.setValue(v)

    def initializePage(self):
        agg = self.wiz.agg
        if agg and agg.locs and self.clist.selectedItems() == []:
            xs = [lc.lon for lc in agg.locs]
            span = max(xs) - min(xs)
            codes = {lc.adm0 for lc in agg.locs if lc.adm0}
            if len(codes) == 1:
                for i in range(self.clist.count()):
                    if self.clist.item(i).data(Qt.ItemDataRole.UserRole) in codes:
                        self.clist.item(i).setSelected(True)
                self.g_countries.setChecked(True)
            elif span < 60:
                self.g_data.setChecked(True)
            else:
                self.g_global.setChecked(True)
            self._enable()

    def collect(self, cfg):
        a = cfg.area
        a.mode = ("global", "region", "countries", "data", "custom")[max(0, self.group.checkedId())]
        a.region = self.region.currentText()
        a.countries = [it.data(Qt.ItemDataRole.UserRole) for it in self.clist.selectedItems()]
        a.include_territories = self.terr.isChecked()
        a.exclude_antarctica = self.antarctica.isChecked()
        a.bbox = [sp.value() for sp in self.bb]

    def restore(self, cfg):
        a = cfg.area
        idx = ("global", "region", "countries", "data", "custom").index(a.mode) if a.mode in (
            "global", "region", "countries", "data", "custom") else 0
        self.group.button(idx).setChecked(True)
        self.antarctica.setChecked(a.exclude_antarctica)
        if a.region and self.region.findText(a.region) >= 0:
            self.region.setCurrentText(a.region)
        for i in range(self.clist.count()):
            self.clist.item(i).setSelected(self.clist.item(i).data(Qt.ItemDataRole.UserRole) in a.countries)
        self.terr.setChecked(a.include_territories)
        for sp, v in zip(self.bb, a.bbox):
            sp.setValue(v)
        self._enable()

    def validatePage(self):
        if self.group.checkedId() == 2 and not self.clist.selectedItems():
            QMessageBox.warning(self, "Evidence Mapper", "Select at least one country in the list.")
            return False
        return True


# =============================================================== 4. look
class StylePage(_Page):
    def __init__(self, wiz):
        super().__init__(wiz, "4 · Basemap and symbols")
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        lay = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll)

        # basemap
        gb = QGroupBox("Basemap")
        f = QFormLayout(gb)
        self.base = QComboBox()
        for k, (label, *_r) in BASEMAPS.items():
            self.base.addItem(label, k)
        self.base_layer = QgsMapLayerComboBox()
        self.base_layer.setFilters(QgsMapLayerProxyModel.Filter.RasterLayer)
        self.base_layer.setEnabled(False)
        self.base_op = QSlider(Qt.Orientation.Horizontal)
        self.base_op.setRange(10, 100)
        self.base_op.setValue(100)
        self.base_gray = QCheckBox("Convert basemap to greyscale")
        self.bg = QgsColorButton()
        self.bg.setColor(QColor("#ffffff"))
        f.addRow("Style:", self.base)
        f.addRow("Project layer:", self.base_layer)
        f.addRow("Opacity:", self.base_op)
        f.addRow("", self.base_gray)
        f.addRow("Background (sea) colour:", self.bg)
        f.addRow("", _hint("Tip: install the QuickMapServices plugin, add any basemap to your project, then choose "
                          "“Use a raster layer already in my project”. Tile basemaps need an internet connection."))
        lay.addWidget(gb)
        self.base.currentIndexChanged.connect(lambda *_: self.base_layer.setEnabled(self.base.currentData() == "project_layer"))

        # symbols
        gs = QGroupBox("Symbols")
        f = QFormLayout(gs)
        self.style = QComboBox()
        self.style.addItem("Proportional circles (area = number of studies)", "bubbles")
        self.style.addItem("Choropleth (shade countries / states – needs country or state data)", "choropleth")
        self.palette = _combo(list(PALETTES.keys()))
        self.single = QgsColorButton()
        self.single.setColor(QColor("#3b6fb6"))
        self.max_size = QDoubleSpinBox(); self.max_size.setRange(4, 40); self.max_size.setValue(12); self.max_size.setSuffix(" mm")
        self.min_size = QDoubleSpinBox(); self.min_size.setRange(0.8, 6); self.min_size.setValue(1.6); self.min_size.setSingleStep(0.2); self.min_size.setSuffix(" mm")
        self.opacity = QSlider(Qt.Orientation.Horizontal); self.opacity.setRange(20, 100); self.opacity.setValue(75)
        self.max_groups = QSpinBox(); self.max_groups.setRange(2, 20); self.max_groups.setValue(12)
        self.labels = QComboBox()
        self.labels.addItem("Numbers beside circles (avoid overlaps)", "beside")
        self.labels.addItem("Numbers inside circles", "inside")
        self.labels.addItem("No numbers", "none")
        self.label_size = QDoubleSpinBox(); self.label_size.setRange(5, 14); self.label_size.setValue(8); self.label_size.setSuffix(" pt")
        self.ramp = _combo(list(RAMPS.keys()))
        self.classes = QSpinBox(); self.classes.setRange(3, 9); self.classes.setValue(5)
        self.cmethod = QComboBox(); self.cmethod.addItem("Quantiles", "quantile"); self.cmethod.addItem("Equal intervals", "equal")
        for lbl, w in (("Map type:", self.style), ("Category colours:", self.palette),
                       ("Colour when there are no categories:", self.single), ("Largest circle:", self.max_size),
                       ("Smallest circle:", self.min_size), ("Circle opacity:", self.opacity),
                       ("Show at most … categories (rest = “Other”):", self.max_groups),
                       ("Numbers:", self.labels), ("Number size:", self.label_size),
                       ("Choropleth colour ramp:", self.ramp), ("Choropleth classes:", self.classes),
                       ("Class method:", self.cmethod)):
            f.addRow(lbl, w)
        lay.addWidget(gs)

        # boundaries
        gbd = QGroupBox("Boundaries, grid and extra layers")
        f = QVBoxLayout(gbd)
        self.b_countries = QCheckBox("Country boundaries (Natural Earth)"); self.b_countries.setChecked(True)
        self.b_admin1 = QCheckBox("State / province boundaries (only inside the chosen countries)")
        self.b_mask = QCheckBox("Fade everything outside the chosen countries"); self.b_mask.setChecked(True)
        self.b_grat = QCheckBox("Graticule (lat/lon grid with coordinate labels)"); self.b_grat.setChecked(True)
        for w in (self.b_countries, self.b_admin1, self.b_mask, self.b_grat):
            f.addWidget(w)
        f.addWidget(QLabel("Also draw these layers from my project (e.g. your own coalfield polygons):"))
        self.extra = QListWidget()
        self.extra.setMaximumHeight(90)
        f.addWidget(self.extra)
        lay.addWidget(gbd)

        # crs
        gc = QGroupBox("Projection")
        f = QFormLayout(gc)
        self.crs = QComboBox()
        for k, t in (("auto", "Automatic (Robinson for the world, equal-area centred on the area otherwise)"),
                     ("epsg:4326", "Plate carrée – WGS 84 (EPSG:4326)"),
                     ("epsg:3857", "Web Mercator (EPSG:3857)"),
                     ("robinson", "Robinson (ESRI:54030)"),
                     ("equal_earth", "Equal Earth (EPSG:8857)"),
                     ("laea", "Lambert azimuthal equal-area centred on the area"),
                     ("custom", "Custom…")):
            self.crs.addItem(t, k)
        self.crs_sel = QgsProjectionSelectionWidget()
        self.crs_sel.setEnabled(False)
        f.addRow("Map projection:", self.crs)
        f.addRow("Custom CRS:", self.crs_sel)
        lay.addWidget(gc)
        self.crs.currentIndexChanged.connect(lambda *_: self.crs_sel.setEnabled(self.crs.currentData() == "custom"))
        lay.addStretch(1)

    def initializePage(self):
        self.extra.clear()
        for lyr in QgsProject.instance().mapLayers().values():
            it = QListWidgetItem(lyr.name())
            it.setData(Qt.ItemDataRole.UserRole, lyr.id())
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Unchecked)
            self.extra.addItem(it)
        d = self.wiz.cfg_data()
        ok = d.loc_mode in ("country", "admin1")
        self.style.model().item(1).setEnabled(ok)
        if not ok:
            self.style.setCurrentIndex(0)
        if d.loc_mode == "admin1":
            self.b_admin1.setChecked(True)

    def collect(self, cfg):
        s = cfg.style
        s.map_style = self.style.currentData()
        s.palette = self.palette.currentText()
        s.single_color = self.single.color().name()
        s.max_size_mm, s.min_size_mm = self.max_size.value(), self.min_size.value()
        s.fill_opacity = self.opacity.value() / 100.0
        s.max_groups = self.max_groups.value()
        s.label_mode, s.label_size = self.labels.currentData(), self.label_size.value()
        s.basemap = self.base.currentData()
        lyr = self.base_layer.currentLayer()
        s.basemap_layer_id = lyr.id() if lyr else ""
        s.basemap_opacity = self.base_op.value() / 100.0
        s.basemap_gray = self.base_gray.isChecked()
        s.background = self.bg.color().name()
        s.show_countries, s.show_admin1 = self.b_countries.isChecked(), self.b_admin1.isChecked()
        s.mask_outside, s.graticule = self.b_mask.isChecked(), self.b_grat.isChecked()
        s.extra_layers = [self.extra.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.extra.count())
                          if self.extra.item(i).checkState() == Qt.CheckState.Checked]
        s.ramp, s.classes, s.class_method = self.ramp.currentText(), self.classes.value(), self.cmethod.currentData()
        a = cfg.area
        a.crs_mode = self.crs.currentData()
        a.crs_custom = self.crs_sel.crs().authid() if self.crs_sel.crs().isValid() else ""

    def restore(self, cfg):
        s = cfg.style
        for combo, data in ((self.style, s.map_style), (self.labels, s.label_mode), (self.base, s.basemap),
                            (self.cmethod, s.class_method), (self.crs, cfg.area.crs_mode)):
            i = combo.findData(data)
            if i >= 0:
                combo.setCurrentIndex(i)
        if s.palette in PALETTES:
            self.palette.setCurrentText(s.palette)
        if s.ramp in RAMPS:
            self.ramp.setCurrentText(s.ramp)
        self.single.setColor(QColor(s.single_color))
        self.max_size.setValue(s.max_size_mm); self.min_size.setValue(s.min_size_mm)
        self.opacity.setValue(int(s.fill_opacity * 100)); self.max_groups.setValue(s.max_groups)
        self.label_size.setValue(s.label_size); self.base_op.setValue(int(s.basemap_opacity * 100))
        self.base_gray.setChecked(s.basemap_gray); self.bg.setColor(QColor(s.background))
        self.b_countries.setChecked(s.show_countries); self.b_admin1.setChecked(s.show_admin1)
        self.b_mask.setChecked(s.mask_outside); self.b_grat.setChecked(s.graticule)
        self.classes.setValue(s.classes)


# =============================================================== 5. layout & export
class OutputPage(_Page):
    def __init__(self, wiz):
        super().__init__(wiz, "5 · Layout and export", "Everything stays editable in the QGIS layout designer afterwards.")
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        lay = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll)

        gt = QGroupBox("Texts")
        f = QFormLayout(gt)
        self.title = QLineEdit("Geographic distribution of the evidence base")
        self.subtitle = QLineEdit()
        self.subtitle.setPlaceholderText("(automatic: mapped counts and symbol explanation)")
        self.key_title = QLineEdit("LOCATION – NUMBER OF STUDIES")
        self.group_title = QLineEdit()
        self.group_title.setPlaceholderText("(automatic: name of the category column)")
        self.size_title = QLineEdit("CIRCLE AREA = NUMBER OF STUDIES")
        self.note_prefix = QLineEdit("Studies without a mappable location")
        for lc, w in (("Title:", self.title), ("Subtitle:", self.subtitle), ("Key heading:", self.key_title),
                     ("Category legend heading:", self.group_title), ("Size legend heading:", self.size_title),
                     ("Footnote for unmapped studies:", self.note_prefix)):
            f.addRow(lc, w)
        lay.addWidget(gt)

        gp = QGroupBox("Page")
        f = QFormLayout(gp)
        self.page = _combo(list(PAGES.keys()))
        self.orient = QComboBox(); self.orient.addItem("Landscape", "landscape"); self.orient.addItem("Portrait", "portrait")
        self.panel = QComboBox()
        self.panel.addItem("Key and legends to the right", "right")
        self.panel.addItem("Key and legends below the map", "bottom")
        self.panel.addItem("Map only", "none")
        self.font = QFontComboBox(); self.font.setCurrentFont(QFont("Arial"))
        self.margin = QDoubleSpinBox(); self.margin.setRange(5, 25); self.margin.setValue(10); self.margin.setSuffix(" mm")
        self.keyrows = QSpinBox(); self.keyrows.setRange(5, 60); self.keyrows.setValue(30)
        f.addRow("Page size:", self.page); f.addRow("Orientation:", self.orient)
        f.addRow("Key and legends:", self.panel); f.addRow("Font:", self.font)
        f.addRow("Margin:", self.margin); f.addRow("Maximum rows in the key:", self.keyrows)
        lay.addWidget(gp)

        ge = QGroupBox("Elements")
        v = QVBoxLayout(ge)
        self.chk = {}
        for k, t in (("key", "Numbered key of locations"), ("groups", "Category legend"), ("size", "Circle-size legend"),
                     ("scale", "Scale bar"), ("north", "North arrow"), ("inset", "Locator inset (world overview)"),
                     ("note", "Footnote with unmapped studies"), ("source", "Source / attribution line")):
            c = QCheckBox(t); c.setChecked(True); self.chk[k] = c; v.addWidget(c)
        lay.addWidget(ge)

        gx = QGroupBox("Export")
        f = QFormLayout(gx)
        self.out_dir = QgsFileWidget(); self.out_dir.setStorageMode(QgsFileWidget.StorageMode.GetDirectory)
        self.out_dir.setFilePath(os.path.join(os.path.expanduser("~"), "EvidenceMaps"))
        self.base_name = QLineEdit("Figure_Evidence_Map")
        self.fmt = {k: QCheckBox(k.upper()) for k in ("png", "pdf", "svg", "tif")}
        self.fmt["png"].setChecked(True); self.fmt["pdf"].setChecked(True)
        row = QHBoxLayout()
        for c in self.fmt.values():
            row.addWidget(c)
        row.addStretch(1)
        self.dpi = QComboBox()
        for d in (150, 300, 600, 1200):
            self.dpi.addItem("%d dpi" % d, d)
        self.dpi.setCurrentIndex(1)
        self.save_data = QCheckBox("Also save the aggregated data (GeoPackage + CSV) next to the figure")
        self.save_data.setChecked(True)
        self.open_designer = QCheckBox("Open the result in the layout designer")
        self.open_designer.setChecked(True)
        f.addRow("Output folder:", self.out_dir); f.addRow("File name:", self.base_name)
        f.addRow("Formats:", row); f.addRow("Resolution:", self.dpi)
        f.addRow("", self.save_data); f.addRow("", self.open_designer)
        lay.addWidget(gx)

        rb = QHBoxLayout()
        sv = QPushButton("Save these settings…"); ld = QPushButton("Load settings…")
        sv.clicked.connect(self.wiz.save_settings); ld.clicked.connect(self.wiz.load_settings)
        rb.addWidget(sv); rb.addWidget(ld); rb.addStretch(1)
        lay.addLayout(rb)
        lay.addWidget(_hint("Click Finish to build the map. Your settings are remembered for next time; "
                            "a saved settings file lets you reproduce this exact figure later."))
        lay.addStretch(1)
        self.setFinalPage(True)

    def collect(self, cfg):
        lo, ex = cfg.layout, cfg.export
        lo.title, lo.subtitle, lo.key_title = self.title.text(), self.subtitle.text(), self.key_title.text()
        lo.group_title, lo.size_legend_title, lo.note_prefix = self.group_title.text(), self.size_title.text(), self.note_prefix.text()
        lo.page, lo.orientation, lo.panel = self.page.currentText(), self.orient.currentData(), self.panel.currentData()
        lo.font, lo.margin_mm, lo.key_max_rows = self.font.currentFont().family(), self.margin.value(), self.keyrows.value()
        lo.show_key, lo.show_groups, lo.show_size_legend = self.chk["key"].isChecked(), self.chk["groups"].isChecked(), self.chk["size"].isChecked()
        lo.show_scale_bar, lo.show_north_arrow = self.chk["scale"].isChecked(), self.chk["north"].isChecked()
        lo.show_inset, lo.show_note, lo.show_source = self.chk["inset"].isChecked(), self.chk["note"].isChecked(), self.chk["source"].isChecked()
        ex.out_dir, ex.base_name = self.out_dir.filePath().strip(), self.base_name.text().strip() or "Figure_Evidence_Map"
        ex.formats = [k for k, c in self.fmt.items() if c.isChecked()]
        ex.dpi, ex.save_data, ex.open_designer = self.dpi.currentData(), self.save_data.isChecked(), self.open_designer.isChecked()

    def restore(self, cfg):
        lo, ex = cfg.layout, cfg.export
        self.title.setText(lo.title); self.subtitle.setText(lo.subtitle); self.key_title.setText(lo.key_title)
        self.group_title.setText(lo.group_title); self.size_title.setText(lo.size_legend_title)
        self.note_prefix.setText(lo.note_prefix)
        if lo.page in PAGES:
            self.page.setCurrentText(lo.page)
        for combo, data in ((self.orient, lo.orientation), (self.panel, lo.panel), (self.dpi, ex.dpi)):
            i = combo.findData(data)
            if i >= 0:
                combo.setCurrentIndex(i)
        self.font.setCurrentFont(QFont(lo.font)); self.margin.setValue(lo.margin_mm); self.keyrows.setValue(lo.key_max_rows)
        for k, v in (("key", lo.show_key), ("groups", lo.show_groups), ("size", lo.show_size_legend),
                     ("scale", lo.show_scale_bar), ("north", lo.show_north_arrow), ("inset", lo.show_inset),
                     ("note", lo.show_note), ("source", lo.show_source)):
            self.chk[k].setChecked(v)
        if ex.out_dir:
            self.out_dir.setFilePath(ex.out_dir)
        self.base_name.setText(ex.base_name)
        for k, c in self.fmt.items():
            c.setChecked(k in ex.formats)
        self.save_data.setChecked(ex.save_data); self.open_designer.setChecked(ex.open_designer)

    def validatePage(self):
        cfg = MapConfig()
        self.collect(cfg)
        if not cfg.export.formats and not cfg.export.out_dir:
            return True
        if cfg.export.formats and not cfg.export.out_dir:
            QMessageBox.warning(self, "Evidence Mapper", "Choose an output folder (or untick all formats).")
            return False
        return True


# =============================================================== result dialog
class ResultDialog(QDialog):
    def __init__(self, res, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Evidence Mapper – map created")
        self.resize(720, 520)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("<h3>Your map is ready</h3>Print layout: <b>%s</b>" % res.layout_name))
        if res.files:
            lay.addWidget(QLabel("<b>Files written</b><br>" + "<br>".join(res.files)))
        if res.warnings:
            w = QLabel("<b>Notes</b><br>• " + "<br>• ".join(res.warnings))
            w.setWordWrap(True)
            w.setStyleSheet("color:#8a5a00;")
            lay.addWidget(w)
        lay.addWidget(QLabel("<b>Suggested figure caption</b> (edit “Figure X”):"))
        self.cap = QPlainTextEdit(res.caption)
        self.cap.setReadOnly(False)
        lay.addWidget(self.cap, 1)
        bb = QDialogButtonBox()
        cp = bb.addButton("Copy caption", QDialogButtonBox.ButtonRole.ActionRole)
        cp.clicked.connect(lambda: QApplication.clipboard().setText(self.cap.toPlainText()))
        bb.addButton(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.accept)
        lay.addWidget(bb)


# =============================================================== wizard
class EvidenceWizard(QWizard):
    def __init__(self, iface, parent=None):
        super().__init__(parent or iface.mainWindow())
        self.iface = iface
        self.setWindowTitle("Evidence Mapper – study distribution maps")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.resize(900, 720)
        self.table = None
        self.agg = None
        self.p_data = DataPage(self)
        self.p_fields = FieldsPage(self)
        self.p_area = AreaPage(self)
        self.p_style = StylePage(self)
        self.p_out = OutputPage(self)
        for p in (self.p_data, self.p_fields, self.p_area, self.p_style, self.p_out):
            self.addPage(p)
        self.setButtonText(QWizard.WizardButton.FinishButton, "Create map")
        self._restore_last()

    # ---- config plumbing
    def cfg_data(self):
        cfg = MapConfig()
        self.p_fields.data_options(cfg)
        return cfg.data

    def collect(self):
        cfg = MapConfig()
        for p in (self.p_data, self.p_fields, self.p_area, self.p_style, self.p_out):
            p.collect(cfg)
        return cfg

    def apply(self, cfg, include_data=True):
        if include_data:
            self.p_data.restore(cfg)
        self.p_area.restore(cfg)
        self.p_style.restore(cfg)
        self.p_out.restore(cfg)
        self._pending_fields = cfg

    def save_settings(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save settings", "evidence_map_settings.json", "JSON (*.json)")
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self.collect().to_dict(), fh, indent=2)

    def load_settings(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load settings", "", "JSON (*.json)")
        if path:
            try:
                with open(path, encoding="utf-8") as fh:
                    cfg = MapConfig.from_dict(json.load(fh))
                self.apply(cfg)
                self.p_fields.restore(cfg)
                QMessageBox.information(self, "Evidence Mapper", "Settings loaded. Review each page, then create the map.")
            except Exception as exc:
                QMessageBox.warning(self, "Evidence Mapper", "Could not read the settings file: %s" % exc)

    def _restore_last(self):
        try:
            raw = QSettings().value(SETTINGS_KEY, "")
            if raw:
                cfg = MapConfig.from_dict(json.loads(raw))
                cfg.data.source = ""
                cfg.export.out_dir = cfg.export.out_dir
                self.p_style.restore(cfg)
                self.p_out.restore(cfg)
        except (ValueError, TypeError, KeyError) as exc:
            log("Last settings not restored: %s" % exc)

    # ---- run
    def accept(self):
        cfg = self.collect()
        try:
            QSettings().setValue(SETTINGS_KEY, json.dumps(cfg.to_dict()))
        except (TypeError, ValueError) as exc:
            log("Settings not remembered: %s" % exc)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            res = build_map(cfg, table=self.table, agg=self.agg)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Evidence Mapper")
            box.setText(str(exc))
            box.setDetailedText(traceback.format_exc())
            box.exec()
            return
        QApplication.restoreOverrideCursor()
        super().accept()
        if cfg.export.open_designer and res.layout is not None:
            try:
                self.iface.openLayoutDesigner(res.layout)
            except Exception as exc:
                log("Could not open the layout designer: %s" % exc)
        ResultDialog(res, self.iface.mainWindow()).exec()
