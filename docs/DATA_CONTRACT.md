# Data contract and interpretation

This file records the source fields the app reads, how it maps them, and which claims it permits. Integration data in `../04_Test_data` and the second-project dataset in `../05_Test_data` are read-only.

## Representative-envelope CSVs

`LGp.csv` and `LLp.csv` each require `Time (s)`, `Max_A`, `Max_B`, `Max_C`, `MM_name_A`, `MM_name_B`, `MM_name_C`, `Max_all`, `Case`, `Run`, `Fault_type` and `MM_name_all`. Exact duplicate rows are removed during load and reported as a warning; distinct rows that collide on `(Case, MM_name_all, Time (s))` remain a blocking structural error. Missing case/MM combinations remain missing; no zero rows are generated.

`Max_all` is the source row's maximum phase value. The Summary view takes the maximum across selected source rows at each ranked index and keeps the winning Case/MM/Run/Fault type for hover and export. Run and fault provenance is shown only for `Max_all`; it is not attached to separate phase selections.

In All envelopes, the exceedance table groups by measurement, Case and MM point. Its `Runs with exceedance` cell lists unique `Run (Fault_type)` pairs from rows above the selected IC reference. The pair values come from the result CSV itself; the app does not infer a separate run-to-fault mapping. This column is shown for `Max_all` only.

`Time (s)` is a representative-envelope ranking/index from the upstream reduction. It is not chronological exposure time or a reconstructed waveform. Reference intersections and sample counts are numerical comparisons only; do not label them compliant/non-compliant or as physical-duration failures.

All envelopes splits the selected IC reference at the project changeover: the SFO table covers `Index_s < 0.020 s`, and the TOV table covers `Index_s >= 0.020 s`. Each table uses the active Withstand or Safety margin basis and calculates its over-limit area only within that segment. The 20 ms point belongs to TOV.

## IC catalogue and formula

The required IC source is either `Input_Data_PSCAD_Python_v11*.xlsx` or `Input_Data_PSCAD_Python_0.11*.xlsx`, worksheet `MM_blocks`, with `Group`, `Un`, `Um`, `SDPF_LG`, `SDPF_LL`, `SIWL_LG`, `SIWL_LL` and `LIWL`. `Group` joins exactly to `MM_name_all`. LG and LL fields stay independent for every MM; equal nominal voltage does not imply equal withstand values. `LIWL` remains catalogue metadata and does not set the plotted transition.

The project plotting convention in [limits.py](../limits.py) is:

- Index `< 0.020 s`: `SIWL_LG` or `SIWL_LL`, treated as kV peak.
- Index `≥ 0.020 s`: `SDPF_LG` or `SDPF_LL`, assumed kV RMS and converted once by `sqrt(2)` to kV peak.
- Safety-margin reference: withstand peak divided by `1.15`.

The 20 ms step and RMS basis are documented project assumptions, not universal IEC declarations. `WLs.xlsx` is not discovered, required, loaded as fallback or used to overwrite `MM_blocks`.

## Surge-arrester workbook discovery

Only `SA.xlsx` and `SA_*.xlsx` are SA candidates, matched case-insensitively. Excel lock files are skipped. `SAs.xlsx` and `SA analysis CIGRE method.xlsx` are not dashboard candidates. When more than one matching file exists, the source selector requires an explicit choice. If none exists, envelope and IC views continue without SA references.

### `SA_Curves` — wide source layout

The first column is `Duration_s`; each remaining exact, unique, non-empty header is an `SA_ID` and contains supplied voltage values in kV peak. This is the source-unit contract for the dashboard. The parser normalizes the sheet to internal `SA_ID`, `Duration_s`, `Voltage_kV_peak` rows while retaining one row per source duration and curve, including blank cells as `NaN`.

Durations must be finite, unique and strictly increasing in source order. Supplied voltages must be finite and positive. Blank voltage cells are missing points, not zero; the app does not fill, interpolate or extrapolate them. Source points are plotted at their supplied durations with gaps disconnected. The 0 s source point is retained and identified as source data only, never as a physical zero-duration withstand value.

SA `Duration_s` values are elapsed durations, whereas envelope `Time (s)` values are ranked indices. They are not aligned measurement axes. The app therefore keeps SA curves as visual references and does not calculate SA violations from these overlays; that comparison is deferred until actual exposure-time data is available.

### `MM_Assignment` — exact mapping

`MM_ID` and `SA_ID` are the required columns. `MM_ID` must exactly match `MM_blocks.Group`; `SA_ID` must exactly match a non-duration column in `SA_Curves`. Each MM point has at most one SA assignment, and one SA curve may be assigned to multiple MM points. A blank `SA_ID` means there is no assigned curve. The app does not infer assignments from busbar names or from the curve's voltage values.

These two sheets are the only SA inputs the dashboard requires. `SA_Types`, `SA_VI_Calculated` and other helper sheets may remain in the workbook; the dashboard ignores them. The dashboard determines an SA curve's voltage class by joining `MM_Assignment.MM_ID` to `MM_blocks.Group` and reading that MM row's `Un` (nominal voltage). The SA curve's y-values are the limit curve itself; they do not identify the network voltage class. Available SA choices are the curves assigned to any MM point at the selected `Un`. Curves assigned to the selected MM points are checked by default, and the user may select other curves mapped to that same voltage. A selected SA curve is drawn once as an LG reference overlay. No `SA_Types` voltage metadata is required.

The 04 test workbook has four source mappings for its two curves. The 05 test workbook has 40 assignments to `66 WTT SA`; all 40 mapped MM points have `Un = 66`, so this curve is available at 66 kV. Its `SA_Types` and `SA_VI_Calculated` sheets are not needed to determine the voltage class or plot that curve. The sidebar **SA limits to apply** chips list curves mapped to the selected voltage; assignments to selected MM points are checked by default. Multiple same-voltage curves can be selected for the Summary LG overlay. SA references are not applied to LL. The All envelopes exceedance ranking is against the selected IC reference, not against SA curves.

The two-sheet template download contains `SA_Curves` and `MM_Assignment`. The former `SAs`-sheet conversion workflow is removed; that format is not read as a dashboard input.

## Hosting and source replacement

On hosted Streamlit, upload either one ZIP containing `LGp.csv`, `LLp.csv` and the PSCAD workbook, optionally with `SA.xlsx` or `SA_*.xlsx`, or upload those individual CSV/XLSX files. Do not combine the ZIP and individual files in one upload. Both paths are read in memory and are not written to disk. Use the uploader's X beside each file to remove it. The content signature changes when the selected upload set or file content changes, so the new source set is discovered, parsed and validated automatically. There is no local or server-folder input.

## Traceability

Requirement IDs, source evidence, implementing modules and regression/browser checks are mapped in [TRACEABILITY.md](TRACEABILITY.md).
