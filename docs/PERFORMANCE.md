# Performance record

The latest tab-switch, 05-data, workbook-export, and code-simplification audit is in [OPTIMISATION_AUDIT_2026-11-06.md](OPTIMISATION_AUDIT_2026-11-06.md). Its follow-up caches and measurements are recorded below.

## Environment and method

Measurements were taken on Windows on 4 November 2026 with the project `.venv` and read-only integration data in `../04_Test_data`. The environment is CPython 3.12.13 and Streamlit 1.66.1. The ZIP is 755,446 bytes; the four uncompressed source files total 14,227,916 bytes. LG and LL each contain 77,000 rows.

Whole-script timings use Streamlit `AppTest`; they include Streamlit widget and element handling but do not include browser painting. Cache-function timings were measured in a standalone process, where Streamlit uses its in-memory cache manager. Figure timings include Plotly JSON serialization but not browser rendering. Timings are wall-clock, repeated as stated below; report medians and observed ranges rather than treating one run as a stable estimate.

## Baseline workflows

| Workflow | Result | Method |
|---|---:|---|
| Cold Streamlit server readiness | Median 1.450 s; range 1.446–1.550 s, 3 runs | Separate fresh server processes; HTTP `/_stcore/health` returned 200. Does not include a browser session or first chart. |
| Empty AppTest startup | 1.219 s, 1 run | First empty app script run; not a browser start measurement. |
| Uncached ZIP upload, parse and Summary run | Median 1.049 s; range 1.039–1.093 s, 3 fresh AppTest processes | Real integration ZIP uploaded; includes the Streamlit script run and Summary figures. |
| Warm Summary rerun | Median 0.500 s; range 0.482–0.513 s, 6 runs | Same session and cached source data. |
| Warm All envelopes rerun, before selection reuse | Median 0.963 s; range 0.910–1.047 s, 6 runs | Same real ZIP and 66 kV selection. |
| ZIP source-discovery cache | 0.030 s miss; warm median 0.0051 s, 3 hits | Standalone decorated-cache call. Individual-file discovery took 0.0037 s. |
| Project parse and validation cache | 0.323 s miss; warm median 0.013 s, 3 hits | `ProjectData.load_seconds` was 0.284 s; cache-hit time includes retrieval and copy. |
| Summary selection, comparison, figures and JSON | Median 0.252 s; range 0.199–0.405 s, 3 runs; 107,011 bytes | Six cases and eight 66 kV MMs; two figures. |
| All envelopes selection, comparison, figures and JSON | Median 0.597 s; range 0.578–0.630 s, 3 runs; 3,419,354 bytes | Six cases and eight 66 kV MMs. This stage includes the sidebar axis-selection pass and the view’s second selection pass. |
| Results workbook, before single-writer change | Median 14.220 s; range 13.481–14.232 s, 3 runs; 2,317,035 bytes | App-equivalent 66 kV export: 48,000 selected rows, 96 reference rows, no exceedance rows, all SA metadata and 1,000 SA points. |

## Changes and after measurements

The All envelopes sidebar now passes its filtered LG/LL frames to the plot builder instead of filtering and sorting the same rows a second time. With the same AppTest workload, warm All envelopes reruns fell from a 0.963 s median (6 runs) to 0.797 s (range 0.745–0.918 s, 9 runs), about 17% lower. This comparison is whole-script timing, not browser paint.

Workbook formatting now runs on the existing `ExcelWriter` workbook. The exporter no longer closes, reopens, formats, and saves a second copy. Under the same app-equivalent workload, export time fell from a 14.220 s median to 6.487 s (range 6.329–6.567 s, 3 runs), about 54% lower. The resulting workbook was about 2,317,490 bytes. The small package-size difference is from OOXML serialization; tests verify selected values, metadata, SA source points and gaps, header formatting, filters and freeze panes.

## Previous 05 snapshot — historical stress measurement

The following before/after run used an earlier 05 dataset snapshot with `LLp.zip`, 16 cases, 40 MMs at 66 kV and 266,500 parsed rows per CSV after duplicate cleanup. That archive is no longer present in the refreshed `../05_Test_data`, so these timings are historical and are not directly comparable with the current dataset.

| Workflow | Before optimization | After optimization | Change |
|---|---:|---:|---:|
| All envelopes AppTest rerun | 11.458 s | 3.262 s | 71.5% lower (about 3.5× faster) |
| Violation-table row-selection AppTest rerun | 11.405 s | 3.161 s | 72.3% lower (about 3.6× faster) |
| Two serialized All envelopes figures | 19.22 MiB | 12.31 MiB | 35.9% lower |

Each before/after UI timing is a single AppTest run in the same uploaded-data workflow, not a median or range. AppTest measures Python/Streamlit script execution and serialized elements; it excludes browser drawing, hover responsiveness, and hosted-network transfer. The latest serialized figures are still about 12.31 MiB combined, so actual browser and hosted latency may differ.

The changes remove repeated whole-frame Case/MM filtering during per-curve figure construction, compute the all/SFO/TOV IC comparisons together for each measurement, and reuse those results for tables and workbook output. Case and MM labels are now stored once per Plotly trace instead of repeated in every plotted point's hover data; per-point Run/Fault and phase identity remain available. A standalone combined-comparison timing on the 05 66 kV selection was 0.354 s for both measurements and all three comparison segments; the preceding six-call comparison profile took 6.115 s. Engineering values, selected rows, trace count, hover fields and chart semantics are unchanged.

For that earlier snapshot, each detailed figure contained 680 traces. Reducing point count or combining traces would change curve/hover behavior and needs a browser-level check against the full-resolution results before adoption.

## Refreshed 05 dataset — 5 November 2026

The current folder contains separate result CSVs, the v11 input workbook and `SA.xlsx`. The measured AppTest ZIP was built in memory from those files. Each result CSV has 133,000 rows, eight cases and 67 result MMs; `MM_blocks` has 68 configured points. At 66 kV, the app selected all eight cases and 40 MM points.

| Workflow | Measurement |
|---|---:|
| Upload, parse and Summary script run | 1.322 s |
| First All envelopes script rerun after selecting 66 kV, after hover-data optimization | 1.853 s |
| Warm All envelopes script rerun after optimization | Median 1.863 s; range 1.845–1.927 s, 3 runs |
| Violation-table row-selection rerun | Not remeasured: the current 66 kV selection has no displayed violation rows to select. The earlier 1.886 s observation predates the optimization. |
| Serialized LG / LL figure traces | 361 / 360 |
| Combined serialized figure JSON | 6.25 MiB |

The 1.853 s first All envelopes result and upload measurement are individual AppTest timings. The warm result is the median of three reruns in one local session. AppTest excludes browser drawing and hosted-network transfer. The earlier row-selection timing predates the change and is retained only as a prior observation; regression tests still check that selecting a violation row highlights its curve.

For the 66 kV data, Run/Fault hover metadata preparation was separately benchmarked over 80,000 rows and 320 curves. Converting to strings per curve took a median 0.197 s; converting once for the whole figure and slicing by group positions took 0.049 s (75% lower). The complete All envelopes AppTest warm-rerun median fell from 2.235 s immediately before the change to 1.863 s after it (16.6% lower); the pre/post measurements used the same 05 fixture and local environment. An instrumented cProfile run after the change shows Plotly `Scatter` construction and validation as the largest remaining Python-side figure cost. Batching `add_trace` calls was benchmarked and was too small a gain to justify restructuring; reducing traces or hover fields would change visible or inspection behavior, so those were left intact.

The audit found no exact or near-duplicate production function bodies. `_view_controls()` now reuses `available_cases()` and `available_mms()` for its Case/MM options instead of rebuilding those unions. Summary and detailed hover-data builders share one string-array conversion helper; their field selection remains different because detailed traces store Case/MM as trace metadata. `build_envelope_figure()` handles both Summary and detailed charts, and `_crossing_summaries()` is shared by the single-part and combined comparison functions. Summary and detailed page renderers keep separate orchestration because their selected data, comparison outputs and export metadata differ. Removed the unused `curve_summary()` peak-table helper, its empty-frame-only test, and an unused app import of `load_sa_workbook()`; source loading remains centralized in `data_loader.py`.

## Memory and rendering notes

For the earlier 04 integration dataset (77,000 rows per result CSV), the two parsed result DataFrames used 22.30 MiB by `memory_usage(deep=True)` and uploaded source bytes totalled 14.23 MB. For the refreshed 05 dataset, a direct load measured 37.09 MiB across LG, LL and MM_blocks DataFrames; the individual uploaded files total 23,235,373 bytes and their project ZIP is 1,337,661 bytes. Source discovery and project data caches each keep at most three entries; process RSS under concurrent hosted sessions has not been measured. Keep these limits until the hosting memory budget and concurrency are known.

The 230 kV integration selection has 14 result MMs and two voltage-compatible SA limits; the two All envelopes figures produced 5,574,965 bytes of Plotly JSON. Browser chart drawing time has not been measured. The recorded browser legend check at a 1,212 px chart width is in [VALIDATION.md](VALIDATION.md). The Plotly legend now uses a maximum height and native scrolling; automated serialization confirms the figure height does not grow from 30 to 300 trace labels, but browser scroll interaction and layout across viewport widths have not been measured.

The `MM_blocks` workbook emits a benign `openpyxl` warning because it contains an Excel Data Validation extension that `openpyxl` does not preserve. The app only reads this source workbook; it does not save or modify it.

## 2026-11-05 — code and performance re-audit

### Scope and method

The saved generic audit prompt also names waveform rendering, Sustained SDPF heatmaps, and Build/Run analysis stages; those workflows do not exist in this dashboard and were excluded. `docs/CURRENT_CONTEXT.md`, `docs/ANALYSIS_METHODS.md` and `pyproject.toml` are absent, so the audit used `AGENTS.md`, README, the app-specific documentation, pinned requirements and current tests. `ruff` is not installed; no lint dependency was added. Static Python AST checks and the full regression suite were used instead.

The workload used the actual 05 project inputs: 133,000 rows in each LG/LL CSV, the v11 input workbook and SA.xlsx. Whole-script timings use Streamlit AppTest, not browser paint. Server readiness uses three fresh Streamlit processes and an HTTP 200 from `/_stcore/health`. PNG timing runs the actual All envelopes figures through Kaleido. The AppTest measurements include background-process variation and should be treated as an observed baseline, not a before/after performance claim.

| Workflow | Current measurement | Notes |
|---|---:|---|
| Cold server readiness | Median 1.439 s; range 1.341–2.344 s, 3 fresh processes | Starts a local Streamlit process without opening a browser. |
| Uncached upload, parse and Summary | Median 1.277 s; range 1.238–1.441 s, 3 runs | AppTest with the actual project ZIP built in memory. |
| First All envelopes at 66 kV | Median 1.852 s; range 1.715–2.246 s, 3 runs | Eight cases and 40 MM points. |
| Warm All envelopes rerun | Median 2.100 s; range 1.826–2.312 s, 9 runs | Same AppTest sessions and selection. A prior measurement was 1.863 s; the current UI-only cleanup does not touch data selection, comparison or chart construction, so this timing difference is not evidence that the change caused a performance regression. |
| Cached project reopen in a new AppTest session | Median 0.655 s; range 0.520–0.793 s, 3 runs | Reuses source discovery and parsed-project cache entries. |
| Data & references render | Median 0.426 s; range 0.370–0.471 s, 5 reruns | Same uploaded 05 project after deferred template generation; the MM assignments table is collapsed by default. |
| Detailed report chart ZIP | Median 7.064 s; range 7.057–7.371 s, 3 exports | Actual Kaleido render; ZIP 549,419 bytes, containing LG/LL PNGs at 1800 × 1050 each. This work is called only when the user requests the download. |

The 66 kV charts remain at 361 LG traces and 360 LL traces, with 6.25 MiB combined Plotly JSON. A cProfile run (instrumentation increases elapsed time and is not used as a timing comparison) attributes the largest remaining Python cost to `build_envelope_figure()` and Plotly `Scatter` construction/validation. Existing code already builds both IC segments together, reuses filtered frames and converts hover metadata once per figure. Reducing or combining traces would remove individual Case/MM lines or hover behavior; no such change was justified. Report PNGs are generated on demand, so their 7-second render does not slow ordinary interactions.

### Code audit findings

- **Medium, maintenance:** `tests/test_data_loader.py` had two functions with the same filename-test name and body. Python silently replaced the first definition with the second, so only one test existed at runtime. Removed the duplicate; this cleanup did not alter test collection. The audit adds one separate AppTest for deferred template generation; the full suite now has 65 tests.
- **Low, simplification:** `_main_selection_controls()` entered each Case/MM container and passed the same container into `_selection_pills()`, where children are placed explicitly. Removed the unused outer scopes; AppTest and the live page confirm the same panel placement.
- **Low, avoid discarded work:** The SA template took a median 15 ms to construct across ten direct calls. The download button now passes the template builder as a callable, so ordinary Data & references renders do not create and discard a workbook.
- **User-facing layout:** The complete SA `MM_Assignment` table is now inside a collapsed Data & references expander. Valid and invalid SA sources share one rendering block, avoiding duplicated table code.
- An AST check found no unreferenced production functions/imports or duplicate top-level function bodies after the cleanup. The custom chip and plot-width components, selection-state helper, split Summary/All renderers, source caches, and report export helper remain in use and address separate tested requirements.
- The cached 05 project uses 37.09 MiB of parsed DataFrames before accounting for uploaded bytes, serialized cache entries, charts or concurrent sessions. The app keeps three source/project snapshots. The hosting memory budget and concurrent-session RSS are unknown, so changing cache bounds or adding another cache would be speculative.

## 2026-11-06 — tab switching and refreshed 05 export audit

The current 05 project was uploaded as individual files (23,235,373 bytes total). On the same AppTest session, uncached upload plus Summary took 1.263 s; warm Summary reruns had a 0.431 s median, and All envelopes at 66 kV had a 1.602 s median. Selecting a row in the 16-row TOV table had a 1.737 s median rerun. AppTest excludes browser chart rendering and network transfer.

Direct stage measurements on the 66 kV selection were 0.219 s for Case/MM catalog generation, 0.054 s for LG/LL curve filtering, 0.213 s for both IC comparison outputs, and 0.602 s for both All figures. The figures contain 361 LG and 360 LL traces and serialize to 6.25 MiB combined. Data & references AppTest reruns were 0.378 s median without chart output. Current Streamlit server readiness was 1.297 s median across three fresh processes, checked through `/_stcore/health`.

The current All report ZIP took 4.059 s median across three exports and contained two 1800 × 1050 PNGs (549,387-byte ZIP). The selected-results workbook took 23.161 s median across three exports for 160,000 selected rows and produced a 7,657,137-byte workbook. This is on-demand work, not part of tab navigation. Profiling points to pandas/OpenPyXL cell writing and XML serialization; the profiler adds substantial overhead and was used only to identify the call tree. The new detailed findings and proposed validation sequence are in the linked audit report above.

## 2026-11-06 — reuse unchanged source-derived view data

Data & references depends on the uploaded project files. Voltage, Case/MM selection, chart channel, index range and IC/SA visibility do not change its source summary, derived IC reference table, SA point counts or validation table. Streamlit still reruns the script and rebuilds the active tab's UI when a tab changes; it now reuses these derived tables and the Case/MM option catalogs from a bounded `st.cache_data` cache keyed by the existing source-content signature. Each cache keeps at most three source sets, matching the discovery and parsed-project caches. Replacing a source changes the signature and rebuilds the relevant data. Since Data & references has no charts, it also skips mounting the plot-width sensor used by Summary and All envelopes.

With the current `05_Test_data` files combined into one in-memory project ZIP, five warm Data & references AppTest reruns took a median **0.092 s** (range **0.085–0.119 s**). The audit's preceding ZIP-upload baseline was **0.378 s** (range **0.334–0.473 s**), about **76% lower** in this repeated-run comparison. AppTest excludes browser painting and hosted-network transfer. The cache regression test verifies that same-signature calls reuse their computed tables and a changed signature refreshes Case/MM catalogs and IC rows. `run_checks.bat` passes with **67 tests** after adding the chart-width sensor guard.
