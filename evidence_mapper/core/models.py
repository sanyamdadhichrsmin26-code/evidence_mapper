"""Plain-data configuration objects. Everything is JSON-serialisable so a
complete map recipe can be saved and re-loaded (reproducible figures)."""
from dataclasses import dataclass, field, asdict, fields
from typing import List


@dataclass
class DataOptions:
    source: str = ""              # file path, or "layer:<layer id>"
    sheet: str = ""               # sublayer / worksheet name
    loc_mode: str = "latlon"      # latlon | country | admin1 | place | geometry
    lat_field: str = ""
    lon_field: str = ""
    country_field: str = ""       # country mode; hint for admin1 / place modes
    admin1_field: str = ""
    place_field: str = ""
    name_field: str = ""          # label used in the key (optional)
    group_field: str = ""         # colour categories (optional)
    value_field: str = ""         # numeric column (value_mode == "sum")
    value_mode: str = "count"     # count | sum
    split_multi: bool = True      # split "India; China" into two locations
    geocode: bool = True          # place mode: query Nominatim


@dataclass
class AreaOptions:
    mode: str = "global"          # global | region | countries | data | custom
    region: str = "Asia"
    countries: List[str] = field(default_factory=list)   # ADM0_A3 codes
    include_territories: bool = False
    exclude_antarctica: bool = True
    bbox: List[float] = field(default_factory=lambda: [60.0, 5.0, 100.0, 40.0])
    crs_mode: str = "auto"        # auto | epsg:4326 | epsg:3857 | robinson | equal_earth | laea | custom
    crs_custom: str = ""


@dataclass
class StyleOptions:
    map_style: str = "bubbles"    # bubbles | choropleth
    palette: str = "Okabe-Ito (colour-blind safe)"
    single_color: str = "#3b6fb6"
    max_size_mm: float = 12.0
    min_size_mm: float = 1.6
    fill_opacity: float = 0.75
    max_groups: int = 12
    label_mode: str = "beside"    # beside | inside | none
    label_size: float = 8.0
    basemap: str = "carto_light"
    basemap_layer_id: str = ""
    basemap_opacity: float = 1.0
    basemap_gray: bool = False
    background: str = "#ffffff"
    show_countries: bool = True
    show_admin1: bool = False
    mask_outside: bool = True
    graticule: bool = True
    extra_layers: List[str] = field(default_factory=list)
    ramp: str = "Blues"
    classes: int = 5
    class_method: str = "quantile"   # quantile | equal


@dataclass
class LayoutOptions:
    title: str = "Geographic distribution of the evidence base"
    subtitle: str = ""
    page: str = "A4"
    orientation: str = "landscape"
    panel: str = "right"          # right | bottom | none
    font: str = "Arial"
    margin_mm: float = 10.0
    show_key: bool = True
    key_title: str = "LOCATION – NUMBER OF STUDIES"
    key_max_rows: int = 30
    show_groups: bool = True
    group_title: str = ""
    show_size_legend: bool = True
    size_legend_title: str = "CIRCLE AREA = NUMBER OF STUDIES"
    show_scale_bar: bool = True
    show_north_arrow: bool = True
    show_inset: bool = True
    show_note: bool = True
    show_source: bool = True
    note_prefix: str = "Studies without a mappable location"


@dataclass
class ExportOptions:
    out_dir: str = ""
    base_name: str = "Figure_Evidence_Map"
    formats: List[str] = field(default_factory=lambda: ["png", "pdf"])
    dpi: int = 300
    save_data: bool = True
    open_designer: bool = True


@dataclass
class MapConfig:
    data: DataOptions = field(default_factory=DataOptions)
    area: AreaOptions = field(default_factory=AreaOptions)
    style: StyleOptions = field(default_factory=StyleOptions)
    layout: LayoutOptions = field(default_factory=LayoutOptions)
    export: ExportOptions = field(default_factory=ExportOptions)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        cfg = cls()
        for sect in ("data", "area", "style", "layout", "export"):
            obj = getattr(cfg, sect)
            src = (d or {}).get(sect, {})
            names = {f.name for f in fields(obj)}
            for k, v in src.items():
                if k in names:
                    setattr(obj, k, v)
        return cfg
