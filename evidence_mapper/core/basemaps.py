"""Built-in XYZ basemaps (no extra plugin required)."""
from qgis.core import QgsRasterLayer

# id: (label, url template or None, max zoom, attribution)
BASEMAPS = {
    "none": ("None – plain background (offline)", None, 0, ""),
    "carto_light": ("CARTO Positron (light, minimal)",
                    "https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png", 19,
                    "© OpenStreetMap contributors © CARTO"),
    "carto_light_nolabels": ("CARTO Positron – no labels",
                             "https://basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}.png", 19,
                             "© OpenStreetMap contributors © CARTO"),
    "carto_voyager": ("CARTO Voyager",
                      "https://basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png", 19,
                      "© OpenStreetMap contributors © CARTO"),
    "carto_dark": ("CARTO Dark Matter",
                   "https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png", 19,
                   "© OpenStreetMap contributors © CARTO"),
    "osm": ("OpenStreetMap Standard",
            "https://tile.openstreetmap.org/{z}/{x}/{y}.png", 19, "© OpenStreetMap contributors"),
    "esri_gray": ("Esri World Light Gray Canvas",
                  "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
                  16, "Tiles © Esri — Esri, HERE, Garmin, FAO, NOAA, USGS"),
    "esri_topo": ("Esri World Topographic",
                  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
                  19, "Tiles © Esri — Esri, HERE, Garmin, USGS, NGA"),
    "esri_relief": ("Esri World Shaded Relief",
                    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Shaded_Relief/MapServer/tile/{z}/{y}/{x}",
                    13, "Tiles © Esri — Source: Esri"),
    "esri_physical": ("Esri World Physical (small-scale)",
                      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Physical_Map/MapServer/tile/{z}/{y}/{x}",
                      8, "Tiles © Esri — Source: US National Park Service"),
    "esri_imagery": ("Esri World Imagery (satellite)",
                     "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                     19, "Tiles © Esri — Esri, Maxar, Earthstar Geographics"),
    "opentopomap": ("OpenTopoMap",
                    "https://tile.opentopomap.org/{z}/{x}/{y}.png", 17,
                    "© OpenStreetMap contributors, SRTM | © OpenTopoMap (CC-BY-SA)"),
    "project_layer": ("Use a raster layer already in my project (e.g. from QuickMapServices)", None, 0, ""),
}


def make_basemap_layer(basemap_id):
    label, url, zmax, _ = BASEMAPS[basemap_id]
    if not url:
        return None
    uri = "type=xyz&url=%s&zmax=%d&zmin=0" % (url, zmax)
    lyr = QgsRasterLayer(uri, label, "wms")
    return lyr if lyr.isValid() else None
