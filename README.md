# Evidence Mapper – QGIS plugin

Publication-ready **study-distribution maps** for literature reviews, systematic reviews, scoping reviews and
evidence-gap maps. Give it a table of included studies; get a journal-style figure (map + numbered key +
legends + scale bar + north arrow + locator inset + footnote) as a QGIS print layout and as PNG / PDF / SVG / TIFF.

## Features
- **Input:** CSV/TSV, Excel (.xlsx), ODS, GeoPackage, Shapefile, GeoJSON, or any layer open in the project.
- **Locations from:** latitude/longitude · country names or ISO codes (handles *USA, Viet Nam, Türkiye, Myanmar (Burma)…*) ·
  state/province names (~4,600 bundled) · place names (geocoded with OSM Nominatim, cached) · layer geometry.
- **Study area:** whole world, 14 regions, any number of countries, fit-to-data, or custom box. Automatic
  equal-area projection (Robinson for the world, centred Lambert azimuthal equal-area otherwise) or your own CRS.
- **Symbols:** circles whose **area** is exactly proportional to the count (a true square-root scale), colour-blind-safe
  categories, greyscale option for B/W print; or a country/state **choropleth**.
- **Layout:** title, auto subtitle, numbered key, category legend, size legend, scale bar, north arrow,
  graticule, locator inset, attribution, and an automatic footnote such as
  *"Studies without a mappable location: Not reported (n = 12); Global (n = 5)"*.
- **Basemaps (no extra plugin):** CARTO Positron / Voyager / Dark, OpenStreetMap, Esri Gray / Topo / Relief / Physical /
  Imagery, OpenTopoMap, plain offline background – or any raster layer in your project (e.g. from QuickMapServices).
- **Reproducibility:** save/load all settings as JSON; aggregated data exported as GeoPackage + CSV; a ready-to-edit figure caption.
- Everything remains editable in the QGIS layout designer.

## Install
**From a zip:** `Plugins ▸ Manage and Install Plugins ▸ Install from ZIP` → choose `evidence_mapper-1.0.2.zip`.
**From the official repository** (after publication): search for *Evidence Mapper*.

## Quick start
1. `Plugins ▸ Evidence Mapper ▸ Create study distribution map…`
2. Pick your file → tell it which columns hold the locations (auto-detected) → press *Check mapping*.
3. Choose area, basemap and symbols → *Create map*.

Sample data: `Plugins ▸ Evidence Mapper ▸ Open sample data folder`
(`india_coalfield_studies.csv` reproduces the example figure; `world_studies_by_country.csv` is synthetic demo data).

## Data format
One row per study is easiest; the plugin counts rows per location. Or give one row per place and sum a numeric column.
Multi-country studies: `India; Kenya` (split on `;` or `|`).

| Mode | Needed columns |
|---|---|
| Coordinates | latitude, longitude (+ optional name, category) |
| Country | country name / ISO-2 / ISO-3 |
| State / province | name (+ country column recommended: *Punjab* exists in India and Pakistan) |
| Place | place name (+ country column recommended) |

## Notes & limits
- Boundaries are **Natural Earth** (public domain). They show de-facto borders and may differ from the official
  maps required by some countries/journals – supply your own boundary layer under *Also draw these layers* and untick
  the built-in boundaries if needed.
- The scale bar is exact only at the map centre (all projections distort). Don't use world maps to measure.
- Tile basemaps need internet and are subject to the providers' terms; credit is printed automatically.
  For bulk/commercial use prefer your own licensed layer.
- Where one location has studies in several categories, the most frequent category sets the colour (noted in the figure).
- Geocoding sends place names to nominatim.openstreetmap.org (1 request/s, cached locally). Switch it off for confidential data.
- Tested on QGIS 3.34 (headless) – CI also runs 3.28 and the latest release.

## Develop / release
```
python3 scripts/package_plugin.py          # -> dist/evidence_mapper-<version>.zip
QT_QPA_PLATFORM=offscreen python3 -m pytest tests
```
Tag `vX.Y.Z` to publish a GitHub release automatically. GPL-2.0-or-later.
