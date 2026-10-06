#!/usr/bin/env python3
"""Build dist/evidence_mapper-<version>.zip in the layout required by plugins.qgis.org
(one top-level folder named after the plugin; no tests, caches or VCS files)."""
import configparser
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "evidence_mapper")
EXCLUDE_DIRS = {"__pycache__", "tests", ".pytest_cache", ".git"}
EXCLUDE_EXT = {".pyc", ".pyo"}

cp = configparser.ConfigParser()
cp.read(os.path.join(SRC, "metadata.txt"), encoding="utf-8")
meta = cp["general"]
for key in ("name", "version", "qgisMinimumVersion", "author", "email", "description", "about", "tracker", "repository"):
    if not meta.get(key):
        sys.exit("metadata.txt: missing '%s'" % key)
if "YOUR" in meta["author"] + meta["email"] + meta["repository"]:
    print("WARNING: metadata.txt still contains placeholders (author / email / repository). "
          "plugins.qgis.org will reject it.", file=sys.stderr)

out_dir = os.path.join(ROOT, "dist")
os.makedirs(out_dir, exist_ok=True)
out = os.path.join(out_dir, "evidence_mapper-%s.zip" % meta["version"])
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for base, dirs, files in os.walk(SRC):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in files:
            if os.path.splitext(f)[1] in EXCLUDE_EXT or f == "pytest.ini":
                continue
            p = os.path.join(base, f)
            z.write(p, os.path.join("evidence_mapper", os.path.relpath(p, SRC)))
print("Created", out, "(%.1f MB)" % (os.path.getsize(out) / 1e6))
