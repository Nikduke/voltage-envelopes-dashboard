# Optimisation audit — 6 November 2026

## Status and scope

The audit identified source-derived work repeated on tab reruns. Its low-risk follow-up is now implemented: Case/MM catalogs and the static Data & references table model are cached by the project source signature, with three entries per cache. No calculations, inputs, displayed values, or user-facing behavior changed.

The audit follows `Code Simplification and Performance Audit` in the Codex attachment. The prompt also names `docs/CURRENT_CONTEXT.md`, `docs/ANALYSIS_METHODS.md`, and `pyproject.toml`; these files are absent from this app. I used the present `AGENTS.md`, README, app architecture/data/performance/validation/traceability documents, source code, and tests. Where an older record differed from the current code or refreshed test data, the current code and measurements were treated as authoritative.

The 05 test project contains 133,000 rows in each LG/LL CSV, eight cases, 67 result MM points, and 68 configured MM points. At 66 kV, the selected view contains 40 MM points and 80,000 rows per measurement. The parsed LG, LL, and MM DataFrames use 37.08 MiB by `memory_usage(deep=True)`.

## A. Performance baseline

### Method

- `run_checks.bat` ran the full project test suite.
- Streamlit `AppTest` timings include the Python script run and Streamlit element/figure serialization. They exclude the browser's JavaScript, chart painting, network transfer, and hosted latency.
- The AppTest workload used the actual 05 files uploaded individually: 23,235,373 bytes across the v11 workbook, LG CSV, LL CSV, and `SA.xlsx`.
- Direct stage timings used the parsed 05 project and the 66 kV selection. Repeated medians are reported where repeated.
- Cold readiness used three fresh local Streamlit processes on a test port and an HTTP 200 from `/_stcore/health`. The existing server on port 8501 also returned HTTP 200.
- Report and workbook exports were generated in memory; no export file was written to a source folder.

### Measurements

| Workflow | Current measurement | Notes |
|---|---:|---|
| Cold Streamlit server readiness | Median 1.297 s; range 1.247–1.677 s, 3 fresh processes | Health endpoint returned `200 ok`; excludes browser startup and first browser paint. |
| Uncached individual-file upload and Summary | 1.263 s, 1 run | Actual 05 inputs, uploaded separately. |
| Warm Summary rerun | Median 0.431 s; range 0.423–0.464 s, 5 reruns | Same AppTest session and project. |
| Warm All envelopes at 66 kV | Median 1.602 s; range 1.498–1.694 s, 5 reruns | Same session; 361 LG and 360 LL traces. |
| Violation-row selection rerun | Median 1.737 s; range 1.667–1.773 s, 5 reruns | Selection rebuilds the active detailed figures to apply the selected-curve highlight. |
| Data & references render | Median 0.378 s; range 0.334–0.473 s, 5 reruns | ZIP-upload AppTest session; charts are not rendered on this tab. |
| Direct project load and validation | 0.518 s, 1 load | `ProjectData.load_seconds`; parsed 266,000 CSV rows plus workbooks. |
| Case/MM option generation | Median 0.219 s; range 0.211–0.298 s, 9 calls | `available_cases()` and `available_mms()` together on the two full result frames. |
| Two-measurement curve filtering | Median 0.054 s; range 0.045–0.061 s, 9 calls | 80,000 selected rows per measurement. |
| Two-measurement IC comparisons | Median 0.213 s; range 0.176–0.225 s, 5 calls | Includes the combined all/SFO/TOV comparison outputs used by the All view. |
| All-view figure construction | Median 0.602 s; range 0.593–0.780 s, 5 calls | Direct Python timing for both figures; excludes AppTest's chart serialization. |
| All-view figure payload | 6.25 MiB JSON; 5.86 MiB pickled | Payload is sent again when Streamlit reruns the active All tab. Browser render time is not measured. |
| Report charts ZIP | Median 4.059 s; range 4.054–4.441 s, 3 exports | 549,387 bytes; two 1800 × 1050 PNGs. This callable runs only when requested. |
| Results workbook export | Median 23.161 s; range 22.910–23.670 s, 3 exports | 160,000 selected data rows, 16 IC-exceedance rows, 640 reference rows, 241 SA points, 68 assignments; output 7,657,137 bytes. This callable runs only when requested. |

The export profile used `cProfile`, which stretched one export from 23.2 s to 61.6 s and is not a valid timing comparison. It identifies the main work as pandas cell writing and OpenPyXL worksheet/XML serialization for approximately 2.25 million cells. The worksheet-width scan is present but is not the dominant profiled path.

### Follow-up: stable source-derived view data

Data & references changes only when the selected project files change; voltage, Case/MM selection and chart controls do not affect its content. Streamlit still runs the app script on a tab change and rebuilds the active tab's UI, but repeated Case/MM catalog scans and the source summary, derived IC rows, SA point counts and validation frame are now reused from `st.cache_data`. Both caches use the existing source-content signature and are bounded to three projects. A changed upload creates a new cache key. Data & references also skips the plot-width sensor because it has no charts.

In a matched warm-rerun AppTest with the current 05 files uploaded as one in-memory ZIP, Data & references decreased from the prior median of 0.378 s (range 0.334–0.473 s) to 0.092 s (range 0.085–0.119 s) across five runs, about 76% lower. The cache test confirms same-signature reuse and refresh on a changed signature. A tab-specific AppTest verifies the width sensor is absent from Data & references. The latest full check reports 67 passed tests and the same five known OpenPyXL Data Validation warnings.

### Applicability of the audit prompt's other workflows

This app consumes already-produced representative-envelope CSVs. It has no `Build envelope data/checks`, `Run analysis`, waveform rendering, plot-batch generation, sustained-SDPF heatmap, or process-pool pipeline. Those audit-prompt items do not apply. Report PNGs and the selected-results workbook are the app's export paths and were measured above.

## B. Prioritised findings

### High — Results workbook generation is slow for the 05 66 kV selection

**Location:** `exports.py:15` and its `DataFrame.to_excel()`/OpenPyXL save path.

**Evidence:** The real 66 kV All selection took a median 23.161 s over three in-memory exports and produced a 7.66 MB workbook with 160,000 selected rows. The profiler attributes most work to writing and serializing roughly 2.25 million spreadsheet cells. The export is correctly deferred until the download is requested, so this does not account for tab-switch time.

**Proposed change:** After approval, benchmark a lower-overhead XLSX writing path in isolation. Keep the current writer unless the alternative produces a material measured improvement on the same 05 selection. Preserve all selected values, seven sheet names/roles, SA source rows, metadata, filters, frozen headers, and supported formatting.

**Expected benefit:** A faster export response; no percentage is claimed before an A/B measurement.

**Risk:** A different writer can change workbook cell types, ordering, styles, filters, freeze panes, or SA content. Workbook semantics must be compared, not just file size.

**Validation:** Same input and selection, at least three timed exports before/after; compare sheet names, headers, row counts, cell values/types for representative fields, SA points/assignments, metadata, filters, frozen panes, and relevant styles. Retain only a change that is materially faster and passes those checks.

### Medium — Tab changes rerun the Streamlit script, but only the active view renders

**Location:** `app.py:main()`, `_render_summary_view()`, `_render_detailed_view()`, `_render_data_references()`, and `plots.py:build_envelope_figure()`.

**Evidence:** The app uses `st.tabs(..., on_change="rerun")`, reads each container's `.open` state, and calls only the active Summary, All, or Data & references renderer. On 05 data, warm All reruns took 1.50–1.69 s; the two All figures themselves took 0.59–0.78 s to construct and serialize to 6.25 MiB of JSON. Data & references emitted no Plotly charts. Returning to a chart tab rebuilds that tab's figures; source-derived Case/MM catalogs and Data & references tables are now cached, reducing the matched Data & references rerun median from 0.378 s to 0.092 s.

**Best-practice check:** This is Streamlit's documented lazy-tab pattern. Removing tab state would cause hidden tab contents to execute too; it would not make the page cheaper. The normal full-script rerun is expected for stateful tab changes.

**Update completed:** Keep the lazy active-tab logic. Reuse the measured static source-derived tables and Case/MM catalogs under the project signature. A separate bounded final-figure cache for All remains an experiment only; no figure cache has been added because memory, full cache-key behavior and browser transfer/render time still need measurement.

**Expected benefit:** Potentially less Python figure construction on repeated identical views. Direct figure construction is 0.60 s for both charts, but cache retrieval, key calculation, serialization, browser transfer, and memory impact have not been measured as a complete cache experiment.

**Risk:** An incomplete cache key could show stale selections, limits, index range, highlighting, or plot width. A full detailed-figure pair occupies about 5.86 MiB pickled before cache overhead, and the browser still receives the plot payload after a hit.

**Validation:** Compare full `to_plotly_json()` output, trace counts/order, hover provenance, limits, selected highlight, legend layout, axis range, and report export. Benchmark identical state before/after with repeated tab switches and selection changes; measure cache hit time and memory. Include source-content signature and every plot-affecting control in the key.

### Medium — Case and MM option lists are reconstructed from full result tables on every rerun

**Location:** `app.py:404–408` and `analysis.py:19–27`.

**Evidence:** On the 05 frames, recomputing the Case and MM catalogs takes a median 0.219 s. `main()` requests these lists on every rerun, including Data & references, where the main Case/MM selector panels are not rendered and the tab content does not use those lists.

**Update completed:** `cached_selection_catalogs()` computes the two catalogs once per source signature. The Data & references view model is cached under the same signature in `cached_reference_display_data()`. Each cache has `max_entries=3`, and the source-replacement regression test checks invalidation. Selection-preservation rules are unchanged.

**Measured result:** The full Data & references warm-rerun median is now 0.092 s versus the prior 0.378 s median on the matched 05 ZIP workflow. Full-script execution remains necessary for tab state; this optimization removes repeated source-derived computation rather than suppressing Streamlit's rerun.

**Risk:** A cache that is not keyed by the selected source content could leave stale cases/MMs after an upload is replaced. Current options combine LG and LL, so both sources must participate in invalidation.

**Validation:** The cache regression test verifies one computation for repeated same-signature calls and updated Case/MM and IC output for a changed signature. The full suite passes 66 tests, including selector, voltage filtering, chip-default and source-signature replacement checks. Matched AppTest timing is recorded above.

### Low — Unused `ProjectData` load telemetry remains in production state

**Location:** `data_loader.py:62–63`, `data_loader.py:175`, and `data_loader.py:224`.

**Evidence:** `loaded_at` and `load_seconds` are assigned during load but have no production or test consumers. The time measurement is used only in historical performance notes, not in the UI or any control flow.

**Proposed change:** Remove these fields and their `datetime`/`time` bookkeeping if no new diagnostics use is intended.

**Expected benefit:** Less unused state and simpler loading code; no meaningful speed improvement is expected.

**Risk:** A future diagnostic may have intended to consume the timing. Confirm no external caller relies on the dataclass fields before removal.

**Validation:** Search for callers, run the loader/validation tests and the full test suite, and keep performance measurement in the benchmark harness rather than the project data object.

### Low — `pytest` is included in the runtime dependency file

**Location:** `requirements.txt:7`.

**Evidence:** `pytest` is used by `run_checks.bat` and tests, not by the app modules. Streamlit Cloud installs `requirements.txt` for the app.

**Proposed change:** Consider separating test-only dependencies into a development requirements file and update the local test setup documentation.

**Expected benefit:** Slightly smaller/cleaner deployment environment and install set; no dashboard runtime speed benefit is expected.

**Risk:** A local environment installed from only `requirements.txt` would no longer have the test runner.

**Validation:** Verify a clean runtime install starts the app and a development install runs all tests.

### Medium — Custom component behavior is not tested in a real browser

**Location:** `tests/test_app_ui.py:167–179`; custom component JavaScript in `app.py`.

**Evidence:** The component tests assert source strings; AppTest does not execute the component JavaScript. A prior user screenshot reported `setStateValue is not defined`. The current source uses the setter documented for Streamlit Components v2, but the current page could not be checked in the in-app browser: it showed connection refused for localhost while the host-side health endpoint returned 200.

**Proposed change:** Add or maintain a browser smoke check for an empty app and a loaded project: component loads without a runtime error, plot width is measured, selection chips respond to ordinary and Ctrl-click, and switching views does not produce a frontend exception.

**Expected benefit:** Catches frontend failures that AppTest and source-text assertions cannot detect; no direct performance claim.

**Risk:** A new browser-test dependency or brittle browser setup adds maintenance. Prefer a small targeted smoke test over a new end-to-end suite.

**Validation:** Check the actual browser console/UI using the supported local launcher and Chrome. This could not be completed in this audit because the available in-app browser could not reach the host-local address.

## C. Recommended sequence

1. Benchmark an alternate workbook writing path against the 23.2 s baseline. Do not switch engines unless workbook equivalence and measured speed both pass.
2. **Completed:** Cache Case/MM catalogs and source-derived Data & references tables under the loaded source signature; tests verify reuse and invalidation.
3. Run a bounded figure-cache experiment for All envelopes, with a complete cache key and a memory measurement. Keep it only if it improves full AppTest time beyond normal variation and does not increase browser latency.
4. Add the targeted browser smoke check for the custom components and tab interactions.
5. Remove unused load-time fields and consider splitting the test dependency from runtime requirements as separate low-priority cleanup.

Each code change should be isolated and measured against the same 05 inputs before proceeding to the next.

## D. Validation plan

- Baseline is the table above. Preserve the exact 05 source files and 66 kV selection for before/after timing.
- Run `run_checks.bat`; all 66 tests pass after the cache follow-up. Five known OpenPyXL warnings report that Excel Data Validation extensions are not supported while reading the MM workbook; the source workbook is not saved or altered.
- For any figure or catalog cache, verify upload replacement invalidation and exact equality of selections, comparison tables, traces, tooltips, and output values.
- For any workbook writer change, compare workbook meaning and layout, then repeat timing at least three times.
- Measure actual browser paint and interaction latency separately from AppTest. The current browser limitation leaves this measurement open.
- No percentage improvement should be claimed until the same measurement is repeated after a change and variation is reported.

## E. Things to leave alone

- Keep the current `st.tabs` `on_change="rerun"` plus `.open` gating. It is the documented lazy-execution pattern and prevents hidden chart tabs from rendering.
- Keep the source-discovery and parsed-project caches keyed by file content with their current `max_entries=3` until hosted RSS and concurrency are measured. Parsed project data is already cached; tab switches do not re-read and re-parse the original files.
- Keep the Case/MM catalogs and Data & references derived tables keyed by the same source signature and bounded to three entries. These small outputs do not include chart state and can be shared for identical source content.
- Keep the single combined SFO/TOV/all IC comparison path, exact Case/MM/run provenance, and source validation. These are required engineering semantics, not redundant work.
- Keep detailed and Summary renderers separate. Their chart inputs, comparison outputs, selection/highlight behavior, and export metadata differ.
- Do not reduce traces, omit hover fields, downsample points, or combine curves to improve timing; those changes alter trace identity or inspection behavior.
- Do not add parallel workers, another broad cache, or a new dependency without a measured net improvement and a clear invalidation/memory case.
- The OpenPyXL Data Validation warning is expected on this read-only input and does not indicate that the source workbook was changed.
