# App reference

## Verified Excel behavior

The supplied `Voltage_envelope_dashboard.xlsx` contains detailed LG and LL dashboard charts with case and busbar filters, plus independent LG and LL summary charts that take a maximum at each index across selected cases/busbars. The workbook's Power Query, pivots, slicers, data model and connections are not runtime dependencies here. The standalone app recreates those selections in Python and keeps separate state for Detailed comparison and Overall summary.

The Excel reference initially displays a 0–0.5 range. The app defaults to the complete available representative-index range, as required for review. The source `Input_Data` final-duration metadata of 0.5 s is distinct from the ranked CSV index reaching 0.998 s.

## Implemented controls

- Folder scan, explicit candidate selection when duplicate source roles exist, optional session-only uploads and explicit reload.
- Independent view state for voltage, cases, MM points, representative-index range, channel and IC reference.
- Compact All/Clear/search selection for cases and MM points; one case and one MM point are selected initially.
- Detailed LG and LL traces; summary per-index maximum with governing case/MM and, for Max_all only, Run/Fault_type provenance.
- Exact Group-to-MM_blocks matching, separate withstand/safety-margin IC references, and assigned/alternative LG-only SA comparison lines.
- Validation findings, selected-curve/peak tables, CSV/XLSX exports, PNG/SVG chart exports and a session-only legacy SA mapping path.

## Reference-app review and design decisions

| App evidence inspected | Reuse/adapt | Avoid and reason |
|---|---|---|
| Harmonics `Murakami` current `data_loader.py`: context-managed `pd.ExcelFile`; `app.py`: bounded `st.cache_data`; chart export: Kaleido | Use context-managed Excel reads, path/mtime keyed cache, Kaleido and independent view state. This app has comparatively small result files and two charts per view. | Did not copy app architecture or harmonic-specific spectrum/THD behavior. |
| LF `Murakami` README and app source: independent panels, session state and cache | Keep detailed and summary selector keys independent; cache parsed sources only. | Did not add LF-specific calculations or extra chart panels. |
| FS Sweep `fs_sweep_app_spline.py`: full-legend viewport sizing and PNG export | Adapt responsive chart height and bottom margin to trace count; test both short and long SVG/PNG legends. | Avoided its custom JavaScript export machinery; two chart builders can use Plotly/Kaleido directly. |

Reference app worktrees were inspected read-only and left untouched. At implementation start, Harmonics and FS Sweep had existing dirty changes; LF had no local Git repository. No source code was copied wholesale.

## Limitations

The legacy `WLs.xlsx` curve is shown as an optional source/status input and is not treated as an authoritative limit. It is not overlaid by default. Unknown-basis legacy SA values can be shown only after explicitly enabling raw-value comparison; no unit conversion is applied. The IC source workbook omits the SDPF unit declaration.
