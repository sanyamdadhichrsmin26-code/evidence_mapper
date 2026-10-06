"""Run inside a QGIS Python environment:  python -m pytest evidence_mapper/tests -q
(headless: QT_QPA_PLATFORM=offscreen)."""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
qgis_core = pytest.importorskip("qgis.core")
from qgis.core import QgsApplication  # noqa: E402

_app = QgsApplication([], False)
_app.initQgis()

from evidence_mapper.core.models import MapConfig  # noqa: E402
from evidence_mapper.core.builder import build_map, get_gazetteer  # noqa: E402
from evidence_mapper.core.aggregate import aggregate  # noqa: E402
from evidence_mapper.core.tables import load_table  # noqa: E402
from evidence_mapper.core import styling  # noqa: E402

SAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sample_data")


def test_country_matching():
    g = get_gazetteer()
    for name, expected in [("USA", "USA"), ("Viet Nam", "VNM"), ("Türkiye", "TUR"), ("Myanmar (Burma)", "MMR"),
                           ("Korea, Republic of", "KOR"), ("Côte d'Ivoire", "CIV"), ("DEU", "DEU")]:
        assert g.match_country(name)["a3"] == expected
    assert g.match_country("Global") is None


def test_area_proportional_size():
    a = styling.size_for(4, 16, 12, 1)
    b = styling.size_for(16, 16, 12, 1)
    assert abs((b / a) ** 2 - 4) < 1e-9          # 4x the value = 4x the area


def test_aggregate_india_sample():
    cfg = MapConfig()
    d = cfg.data
    d.loc_mode, d.lat_field, d.lon_field, d.name_field = "latlon", "Latitude", "Longitude", "Coalfield"
    t = load_table(os.path.join(SAMPLES, "india_coalfield_studies.csv"))
    agg = aggregate(t, d, get_gazetteer())
    assert agg.total_rows == 83 and agg.rows_mapped == 65 and len(agg.locs) == 18
    assert agg.locs[0].name == "Jharia" and agg.locs[0].value == 14
    assert agg.unmapped["Not reported"] == 12


def test_country_split_multi():
    t = load_table(os.path.join(SAMPLES, "world_studies_by_country.csv"))
    cfg = MapConfig()
    cfg.data.loc_mode, cfg.data.country_field = "country", "Country"
    with_split = aggregate(t, cfg.data, get_gazetteer())
    cfg.data.split_multi = False
    no_split = aggregate(t, cfg.data, get_gazetteer())
    assert with_split.total_value > no_split.total_value


@pytest.mark.parametrize("mode,area", [("bubbles", "global"), ("choropleth", "global"), ("bubbles", "countries")])
def test_full_build_exports(mode, area):
    cfg = MapConfig()
    cfg.data.source = os.path.join(SAMPLES, "world_studies_by_country.csv")
    cfg.data.loc_mode, cfg.data.country_field, cfg.data.group_field = "country", "Country", "Design"
    cfg.style.basemap, cfg.style.map_style = "none", mode
    cfg.area.mode = area
    cfg.area.countries = ["IND"]
    with tempfile.TemporaryDirectory() as tmp:
        cfg.export.out_dir, cfg.export.formats, cfg.export.dpi = tmp, ["png", "pdf"], 72
        res = build_map(cfg)
        assert any(f.endswith(".png") and os.path.getsize(f) > 5000 for f in res.files)
        assert any(f.endswith(".pdf") for f in res.files)
        assert "Figure X" in res.caption
