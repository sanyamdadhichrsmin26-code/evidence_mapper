"""Bundled Natural Earth gazetteer: country / state matching, anchors, extents."""
import math
import os
import unicodedata
import re

from qgis.core import QgsVectorLayer, QgsGeometry, QgsRectangle

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
COUNTRIES_PATH = os.path.join(DATA_DIR, "countries.geojson")
ADMIN1_PATH = os.path.join(DATA_DIR, "admin1.geojson")
WORLD_PATH = os.path.join(DATA_DIR, "world_overview.geojson")


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = s.replace("&", " and ").replace("'", "").replace("\u2019", "")
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    s = re.sub(r"^the ", "", s)
    return s


# normalised alias -> Natural Earth ADM0_A3
ALIASES = {
    "usa": "USA", "us": "USA", "u s": "USA", "u s a": "USA", "united states": "USA",
    "united states of america": "USA", "america": "USA",
    "uk": "GBR", "u k": "GBR", "great britain": "GBR", "britain": "GBR", "england": "GBR",
    "scotland": "GBR", "wales": "GBR", "northern ireland": "GBR",
    "russian federation": "RUS", "russia": "RUS",
    "korea": "KOR", "south korea": "KOR", "republic of korea": "KOR", "korea republic of": "KOR",
    "korea south": "KOR", "north korea": "PRK", "dprk": "PRK",
    "korea democratic peoples republic of": "PRK",
    "iran islamic republic of": "IRN", "viet nam": "VNM", "turkiye": "TUR",
    "czech republic": "CZE", "ivory coast": "CIV", "cote divoire": "CIV",
    "drc": "COD", "dr congo": "COD", "congo kinshasa": "COD", "democratic republic of congo": "COD",
    "congo democratic republic of the": "COD", "congo brazzaville": "COG", "republic of congo": "COG",
    "laos": "LAO", "lao pdr": "LAO", "burma": "MMR", "swaziland": "SWZ", "eswatini": "SWZ",
    "macedonia": "MKD", "uae": "ARE", "east timor": "TLS", "timor leste": "TLS",
    "peoples republic of china": "CHN", "prc": "CHN", "p r china": "CHN", "mainland china": "CHN",
    "holland": "NLD", "the netherlands": "NLD", "cape verde": "CPV",
    "tanzania united republic of": "TZA", "united republic of tanzania": "TZA",
    "syrian arab republic": "SYR", "bolivia plurinational state of": "BOL",
    "venezuela bolivarian republic of": "VEN", "moldova republic of": "MDA",
    "palestinian territory": "PSE", "state of palestine": "PSE", "west bank": "PSE", "gaza": "PSE",
    "gambia the": "GMB", "bahamas the": "BHS", "hong kong sar": "HKG", "macau": "MAC",
    "south sudan": "SDS", "sao tome and principe": "STP", "bosnia": "BIH",
    "central african republic": "CAF", "dominican republic": "DOM",
    "equatorial guinea": "GNQ", "solomon islands": "SLB", "marshall islands": "MHL",
    "united arab emirates": "ARE", "western sahara": "SAH", "falkland islands": "FLK",
    "faroe islands": "FRO", "cayman islands": "CYM", "turks and caicos islands": "TCA",
    "saint kitts and nevis": "KNA", "saint vincent and the grenadines": "VCT",
    "antigua and barbuda": "ATG", "french polynesia": "PYF",
}

# Extent used for a country when "include overseas territories" is OFF.
# (xmin, ymin, xmax, ymax) in lon/lat. Countries not listed use their full extent.
MAINLAND_BBOX = {
    "USA": (-125.5, 24.0, -66.5, 49.8), "FRA": (-5.8, 41.0, 10.0, 51.5),
    "RUS": (19.0, 41.0, 180.0, 82.0), "NOR": (4.0, 57.8, 31.5, 71.4),
    "NLD": (3.2, 50.7, 7.4, 53.7), "DNK": (7.9, 54.5, 15.3, 57.9),
    "ESP": (-9.5, 35.8, 4.6, 43.9), "PRT": (-9.7, 36.8, -6.0, 42.2),
    "GBR": (-8.8, 49.7, 2.0, 60.9), "CHL": (-76.0, -56.0, -66.0, -17.0),
    "ECU": (-81.2, -5.1, -75.0, 1.5), "NZL": (166.0, -47.5, 178.8, -34.0),
    "AUS": (112.5, -44.0, 154.0, -10.0), "IDN": (94.9, -11.2, 141.1, 6.2),
    "JPN": (122.8, 24.0, 146.2, 45.8), "FJI": (176.8, -19.3, 180.0, -12.3),
    "CAN": (-141.2, 41.5, -52.0, 83.2), "IND": (68.0, 6.4, 97.5, 37.2),
    "KIR": (172.8, -4.8, 176.8, 4.8), "ITA": (6.5, 36.5, 18.6, 47.2),
    "GRC": (19.3, 34.7, 28.3, 41.8), "CHN": (73.4, 18.0, 135.1, 53.6),
}

REGIONS = {  # curated extents (xmin, ymin, xmax, ymax)
    "World (excluding Antarctica)": (-180, -58, 180, 84),
    "Africa": (-26, -36, 56, 38), "Asia": (25, -11, 150, 78),
    "Central Asia": (45, 33, 90, 56), "East Asia": (73, 18, 146, 54),
    "South Asia": (60, 5, 98, 38), "Southeast Asia": (92, -11.5, 142, 29),
    "Middle East / West Asia": (25, 11, 66, 43), "Europe": (-25, 34, 45, 72),
    "North America": (-170, 5, -50, 84), "Central America & Caribbean": (-93, 7, -58, 28),
    "South America": (-84, -57, -33, 14), "Oceania": (110, -48, 180, 2),
    "Latin America & Caribbean": (-120, -57, -33, 33), "Sub-Saharan Africa": (-20, -36, 53, 20),
}


def haversine_km(lon1, lat1, lon2, lat2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1, math.sqrt(a)))


def _anchor(geom):
    """Representative point on the largest part of the polygon."""
    if geom.isMultipart():
        parts = geom.asMultiPolygon()
        best = max(parts, key=lambda p: QgsGeometry.fromPolygonXY(p).area())
        g = QgsGeometry.fromPolygonXY(best)
    else:
        g = geom
    c = g.centroid()
    if c and not c.isNull() and g.contains(c):
        return c.asPoint()
    return g.pointOnSurface().asPoint()


class Gazetteer:
    def __init__(self):
        self.countries = []
        self._index = {}
        self._load_countries()
        self._admin1 = None
        self._admin1_index = None

    # ---------------------------------------------------------------- countries
    def _load_countries(self):
        lyr = QgsVectorLayer(COUNTRIES_PATH, "countries", "ogr")
        if not lyr.isValid():
            raise RuntimeError("Bundled country data missing: %s" % COUNTRIES_PATH)
        for f in lyr.getFeatures():
            g = f.geometry()
            rec = {
                "name": f["name"], "a3": f["adm0_a3"], "iso3": f["iso_a3_eh"], "iso2": f["iso_a2_eh"],
                "continent": f["continent"], "subregion": f["subregion"], "geom": g,
                "anchor": _anchor(g), "id": f.id(),
            }
            self.countries.append(rec)
        by_a3 = {c["a3"]: c for c in self.countries}
        self.by_a3 = by_a3
        idx = self._index
        for f in lyr.getFeatures():
            a3 = f["adm0_a3"]
            for fld in ("name", "name_long", "admin", "formal_en", "name_en", "abbrev", "iso_a2_eh",
                        "iso_a3_eh", "adm0_a3"):
                v = f[fld]
                if v and str(v) != "-99" and str(v) != "NULL":
                    idx.setdefault(norm(v), a3)
            alt = f["name_alt"]
            if alt and str(alt) != "NULL":
                for a in re.split(r"[;,|]", str(alt)):
                    idx.setdefault(norm(a), a3)
        for k, v in ALIASES.items():
            if v in by_a3:
                idx[k] = v
        # NE special codes
        for k, v in (("south sudan", "SDS"), ("western sahara", "SAH"), ("kosovo", "KOS"),
                     ("siachen glacier", "KAS"), ("somaliland", "SOL"), ("cyprus", "CYP")):
            if v in by_a3:
                idx[k] = v

    def match_country(self, text):
        t = norm(text)
        if not t:
            return None
        a3 = self._index.get(t)
        if not a3 and "(" in str(text):          # "Myanmar (Burma)" -> try both parts
            outer = re.sub(r"\(.*?\)", " ", str(text))
            inner = re.findall(r"\((.*?)\)", str(text))
            for cand in [outer] + inner:
                a3 = self._index.get(norm(cand))
                if a3:
                    break
        return self.by_a3.get(a3) if a3 else None

    def country_choices(self):
        return sorted(((c["name"], c["a3"]) for c in self.countries if c["a3"] != "ATA"))

    # ------------------------------------------------------------------ admin-1
    def _load_admin1(self):
        if self._admin1 is not None:
            return
        lyr = QgsVectorLayer(ADMIN1_PATH, "admin1", "ogr")
        self._admin1, self._admin1_index = [], {}
        for f in lyr.getFeatures():
            g = f.geometry()
            rec = {"name": f["name"], "a3": f["adm0_a3"], "code": f["iso_3166_2"],
                   "anchor": _anchor(g), "geom": g, "key": "%s|%s" % (f["adm0_a3"], f["name"])}
            self._admin1.append(rec)
            names = {f["name"], f["iso_3166_2"]}
            alt = f["name_alt"]
            if alt and str(alt) != "NULL":
                names.update(re.split(r"[|;]", str(alt)))
            for n in names:
                if n and str(n) != "NULL":
                    self._admin1_index.setdefault(norm(n), []).append(rec)

    def match_admin1(self, text, country_a3=None):
        """Returns (record, status) where status is ok | ambiguous | none."""
        self._load_admin1()
        cands = self._admin1_index.get(norm(text), [])
        if country_a3:
            sub = [c for c in cands if c["a3"] == country_a3]
            cands = sub or cands
        uniq = {c["key"]: c for c in cands}
        if not uniq:
            return None, "none"
        if len(uniq) > 1:
            return None, "ambiguous"
        return list(uniq.values())[0], "ok"

    # ------------------------------------------------------------------- extents
    def area_extent(self, a3_list, include_territories=False):
        rect = None
        for a3 in a3_list:
            c = self.by_a3.get(a3)
            if not c:
                continue
            if not include_territories and a3 in MAINLAND_BBOX:
                r = QgsRectangle(*MAINLAND_BBOX[a3])
            else:
                r = QgsRectangle(c["geom"].boundingBox())
            if rect is None:
                rect = QgsRectangle(r)
            else:
                rect.combineExtentWith(r)
        return rect
