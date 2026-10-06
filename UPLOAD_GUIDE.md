# Publishing Evidence Mapper – step by step

## A. Put the code on GitHub
1. Create an empty repository named `evidence_mapper` on github.com (no README).
2. Edit `evidence_mapper/metadata.txt`: replace `YOUR NAME`, `your.email@example.org` and both `YOUR_GITHUB_USER` URLs. Also use your user name in README if you add badges.
3. In this folder:
```
git init && git add . && git commit -m "Evidence Mapper 1.0.0"
git branch -M main
git remote add origin https://github.com/<you>/evidence_mapper.git
git push -u origin main
```
CI (GitHub Actions) now runs the tests on QGIS 3.28, 3.34 and latest.

## B. Build the installable zip
```
python3 scripts/package_plugin.py      # creates dist/evidence_mapper-1.0.2.zip
```
Install locally to try it: QGIS ▸ Plugins ▸ Manage and Install ▸ *Install from ZIP*.

## C. Release on GitHub
`git tag v1.0.0 && git push --tags` – the Release workflow attaches the zip to a GitHub release.

## D. Official QGIS plugin repository (plugins.qgis.org)
1. Create / log in to an OSGeo account: https://www.osgeo.org/community/getting-started-osgeo/
2. Open https://plugins.qgis.org/plugins/add/ and upload `dist/evidence_mapper-1.0.2.zip`.
3. The upload is validated automatically (metadata, folder name, licence). A staff member approves new plugins, usually within days.
4. For updates: raise `version=` in metadata.txt (+ changelog), rebuild the zip, upload as a new version.
Checklist: unique plugin name · real author/e-mail · repository & tracker URLs reachable · GPL licence file present · no `__pycache__`/binaries in the zip.
