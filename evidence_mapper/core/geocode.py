"""Optional place-name geocoding through OpenStreetMap Nominatim.

Follows the Nominatim usage policy: identifying User-Agent, max one request per
second, and a persistent on-disk cache so each place is only queried once."""
import json
import os
import time
import urllib.parse

from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.core import QgsApplication, QgsBlockingNetworkRequest

USER_AGENT = b"QGIS-EvidenceMapper/1.0 (QGIS plugin; literature-review maps)"


class Geocoder:
    def __init__(self, cache_path=None):
        self.cache_path = cache_path or os.path.join(
            QgsApplication.qgisSettingsDirPath(), "evidence_mapper_geocache.json")
        self.cache = {}
        self._last = 0.0
        try:
            with open(self.cache_path, "r", encoding="utf-8") as fh:
                self.cache = json.load(fh)
        except Exception:
            self.cache = {}

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
            with open(self.cache_path, "w", encoding="utf-8") as fh:
                json.dump(self.cache, fh, ensure_ascii=False)
        except Exception:
            pass

    def is_cached(self, query):
        return query.strip().lower() in self.cache

    def geocode(self, query):
        """Returns (lon, lat) or None. Raises RuntimeError on network failure."""
        key = query.strip().lower()
        if key in self.cache:
            v = self.cache[key]
            return tuple(v) if v else None
        wait = 1.1 - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        url = "https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q=" + \
              urllib.parse.quote(query)
        req = QNetworkRequest(QUrl(url))
        req.setRawHeader(b"User-Agent", USER_AGENT)
        blocking = QgsBlockingNetworkRequest()
        err = blocking.get(req, False)
        self._last = time.time()
        if err != QgsBlockingNetworkRequest.NoError:
            raise RuntimeError("Geocoding service unreachable: %s" % blocking.errorMessage())
        try:
            data = json.loads(bytes(blocking.reply().content()).decode("utf-8"))
        except Exception:
            raise RuntimeError("Unexpected reply from the geocoding service.")
        res = (float(data[0]["lon"]), float(data[0]["lat"])) if data else None
        self.cache[key] = list(res) if res else None
        return res
