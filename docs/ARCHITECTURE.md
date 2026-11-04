# Architecture

## Data flow

```text
Folder scan / session uploads
    -> data_loader.py (candidate selection, file parsing, bounded source cache)
    -> validation.py (source and cross-source findings)
    -> analysis.py (exact Case/MM/index filtering, pointwise maxima, reference counts)
    -> limits.py + sa_data.py (IC conventions, SA validation/assignment/interpolation)
    -> plots.py (Plotly detailed and summary figures)
    -> app.py (session state, controls, tables, downloads)
    -> exports.py (CSV/XLSX/PNG/SVG)
```

## Module boundaries

- `data_loader.py` discovers plausible filenames without guessing among duplicates and loads CSV/XLSX into a detached `ProjectData` snapshot. Excel workbooks are context-managed; parsed sources are cached by source path, size, modified time or uploaded content digest plus the source folder and reload token.
- `validation.py` reports structural errors, warnings and missing coverage separately. Only blocking LG/LL result structure issues suppress result plots.
- `analysis.py` operates on pandas frames and does not depend on Streamlit. Summary uses each index's actual winner row.
- `limits.py` contains the single project IC formula and explicit 20 ms / 1.15 constants.
- `sa_data.py` handles the three-sheet schema, legacy import, explicit mapping conversion, validation and bounded interpolation.
- `plots.py` builds white-background figures with dark axes, stable case colors, MM dash patterns, source hover and trace-count-aware legend space.
- `exports.py` carries filters and interpretation metadata into selected data CSV/XLSX and uses Kaleido for chart images.
- `app.py` contains only UI/session orchestration and selection state.

## Performance decisions

Parsing is cached with three source snapshots maximum. The cache key observes path/size/mtime and uploaded bytes; an explicit reload increments the signature. Selector changes filter the cached 77k-row frames; no aggregate chart payload is retained in session state. Initial selections are one case and one MM point. The app does not poll, create a server API, use a database, or parallelize this workload.

## Local reference reuse

See [APP_REFERENCE.md](APP_REFERENCE.md) for evidence and the reuse/adapt/avoid table. Only small patterns were adapted: context-managed Excel reads and bounded cache, independent session selectors, and dynamic legend area with Kaleido exports. No reference app was modified or copied wholesale.
