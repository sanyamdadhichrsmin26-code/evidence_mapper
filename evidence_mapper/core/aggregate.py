"""Turn a table of studies into mappable, aggregated locations."""
import re
from collections import Counter


from .tables import to_float

MULTI_SPLIT = re.compile(r"\s*[;|]\s*")


class Loc:
    def __init__(self, key, name, lon, lat, kind="point", adm0=None):
        self.key, self.name, self.lon, self.lat = key, name, lon, lat
        self.kind, self.adm0 = kind, adm0       # kind: point | country | admin1
        self.value = 0.0
        self.n_rows = 0
        self.groups = Counter()
        self.id = 0
        self._lon_sum = 0.0
        self._lat_sum = 0.0
        self._n_pts = 0

    @property
    def group(self):
        if not self.groups:
            return ""
        top = max(self.groups.values())
        return sorted(g for g, v in self.groups.items() if v == top)[0]

    @property
    def mixed(self):
        return len(self.groups) > 1


class AggResult:
    def __init__(self):
        self.locs = []
        self.unmapped = Counter()          # reason -> rows
        self.unmatched_tokens = Counter()  # text that could not be matched
        self.total_rows = 0
        self.rows_mapped = 0
        self.rows_unmapped = 0
        self.messages = []
        self.group_totals = Counter()

    @property
    def total_value(self):
        return sum(lc.value for lc in self.locs)


def _split(cell, split_multi):
    cell = (cell or "").strip()
    if not cell:
        return []
    return [t for t in MULTI_SPLIT.split(cell) if t] if split_multi else [cell]


def _fmt_num(v):
    return str(int(v)) if abs(v - round(v)) < 1e-9 else ("%g" % v)


def aggregate(table, opt, gaz, geocoder=None, progress=None, is_canceled=None):
    """`progress(i, n, text)` is called while geocoding; `is_canceled()` may abort."""
    res = AggResult()
    res.total_rows = len(table)
    locs = {}

    def get_loc(key, factory):
        if key not in locs:
            locs[key] = factory()
        return locs[key]

    mode = opt.loc_mode
    # ---- optional pre-geocoding so that progress is meaningful
    geo_cache = {}
    if mode == "place" and opt.place_field:
        queries = []
        for r in table.rows:
            q = _place_query(r, opt)
            if q:
                queries.append(q)
        uniq = list(dict.fromkeys(queries))
        if uniq and not opt.geocode:
            res.messages.append("Place names are present but geocoding is switched off.")
        elif uniq and geocoder is not None:
            todo = [q for q in uniq if not geocoder.is_cached(q)]
            for i, q in enumerate(uniq):
                if is_canceled and is_canceled():
                    raise RuntimeError("Cancelled by user.")
                if progress and not geocoder.is_cached(q):
                    progress(i, len(uniq), "Geocoding: %s" % q)
                geo_cache[q] = geocoder.geocode(q)
            geocoder.save()
            if todo:
                res.messages.append("Geocoded %d new place(s); results are cached." % len(todo))

    for i, row in enumerate(table.rows):
        w = 1.0
        if opt.value_mode == "sum" and opt.value_field:
            w = to_float(row.get(opt.value_field))
            if w is None:
                res.unmapped["Non-numeric value"] += 1
                res.rows_unmapped += 1
                continue
        grp = (row.get(opt.group_field, "") if opt.group_field else "").strip() or \
              ("Not specified" if opt.group_field else "All studies")
        name_cell = (row.get(opt.name_field, "") if opt.name_field else "").strip()
        mapped_here, reasons = 0, []

        def add(loc, weight=w, group=grp):
            loc.value += weight
            loc.n_rows += 1
            loc.groups[group] += weight

        if mode == "latlon":
            lat, lon = to_float(row.get(opt.lat_field)), to_float(row.get(opt.lon_field))
            if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                reasons.append(name_cell or "Not reported")
            else:
                key = ("n:" + name_cell.casefold()) if name_cell else "c:%.4f,%.4f" % (lat, lon)
                loc = get_loc(key, lambda: Loc(key, name_cell or "%.2f, %.2f" % (lat, lon), lon, lat))
                loc._lon_sum += lon; loc._lat_sum += lat; loc._n_pts += 1
                add(loc); mapped_here += 1

        elif mode == "geometry":
            p = table.points[i] if table.points else None
            if p is None:
                reasons.append(name_cell or "Not reported")
            else:
                key = ("n:" + name_cell.casefold()) if name_cell else "c:%.4f,%.4f" % (p.y(), p.x())
                loc = get_loc(key, lambda: Loc(key, name_cell or "%.2f, %.2f" % (p.y(), p.x()), p.x(), p.y()))
                loc._lon_sum += p.x(); loc._lat_sum += p.y(); loc._n_pts += 1
                add(loc); mapped_here += 1

        elif mode == "country":
            tokens = _split(row.get(opt.country_field, ""), opt.split_multi)
            if not tokens:
                reasons.append("Not reported")
            for t in tokens:
                c = gaz.match_country(t)
                if c is None:
                    reasons.append(t)
                    res.unmatched_tokens[t] += 1
                else:
                    a = c["anchor"]
                    loc = get_loc(c["a3"], lambda: Loc(c["a3"], c["name"], a.x(), a.y(), "country", c["a3"]))
                    add(loc); mapped_here += 1

        elif mode == "admin1":
            tokens = _split(row.get(opt.admin1_field, ""), opt.split_multi)
            hint = gaz.match_country(row.get(opt.country_field, "")) if opt.country_field else None
            if not tokens:
                reasons.append("Not reported")
            for t in tokens:
                rec, status = gaz.match_admin1(t, hint["a3"] if hint else None)
                if rec is None:
                    reasons.append(t if status == "none" else t + " (ambiguous – add a country column)")
                    res.unmatched_tokens[t] += 1
                else:
                    a = rec["anchor"]
                    loc = get_loc(rec["key"], lambda: Loc(rec["key"], rec["name"], a.x(), a.y(), "admin1", rec["a3"]))
                    add(loc); mapped_here += 1

        elif mode == "place":
            q = _place_query(row, opt)
            if not q:
                reasons.append("Not reported")
            else:
                hit = geo_cache.get(q)
                if hit is None:
                    reasons.append(row.get(opt.place_field, "").strip())
                    res.unmatched_tokens[q] += 1
                else:
                    key = "p:" + q.casefold()
                    nm = row.get(opt.place_field, "").strip()
                    loc = get_loc(key, lambda: Loc(key, nm, hit[0], hit[1]))
                    add(loc); mapped_here += 1

        if mapped_here:
            res.rows_mapped += 1
        else:
            res.rows_unmapped += 1
            res.unmapped[reasons[0] if reasons else "Not reported"] += 1

    # ---- finalise
    out = list(locs.values())
    for lc in out:
        if lc.kind == "point" and lc._n_pts > 1:       # mean of coordinates for named sites
            lc.lon, lc.lat = lc._lon_sum / lc._n_pts, lc._lat_sum / lc._n_pts
    names = Counter(lc.name for lc in out)
    for lc in out:                     # disambiguate e.g. Punjab (India) / Punjab (Pakistan)
        if lc.kind == "admin1" and names[lc.name] > 1 and lc.adm0 in gaz.by_a3:
            lc.name = "%s (%s)" % (lc.name, gaz.by_a3[lc.adm0]["name"])
    out.sort(key=lambda lc: (-lc.value, lc.name.casefold()))
    for i, lc in enumerate(out, 1):
        lc.id = i
        res.group_totals[lc.group] += lc.value
    res.locs = out
    if mode == "latlon" and not opt.name_field:
        res.messages.append("No name column chosen: rows are merged by identical coordinates "
                            "(rounded to 4 decimals).")
    return res


def _place_query(row, opt):
    p = (row.get(opt.place_field, "") or "").strip()
    if not p:
        return ""
    c = (row.get(opt.country_field, "") or "").strip() if opt.country_field else ""
    return "%s, %s" % (p, c) if c else p


def format_unmapped_note(res, prefix):
    if not res.unmapped:
        return ""
    parts = ["%s (n = %d)" % (k, v) for k, v in sorted(res.unmapped.items(), key=lambda kv: (-kv[1], kv[0]))]
    return "%s: %s." % (prefix, "; ".join(parts))
