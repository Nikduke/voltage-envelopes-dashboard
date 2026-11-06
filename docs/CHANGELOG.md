# Changelog and deferred work

## 2026-11-06 — add paired IC/SA display and distinguish SA curves

- Added a third sidebar mode, **SA on LGp + IC on LLp**. It clears the two independent toggles, keeps the voltage-filtered SA selector available, and routes overlays to the requested plots on Summary and All envelopes. Clicking either standalone toggle exits paired mode; if the selected voltage has no compatible SA curve, paired mode clears and IC limits return on.
- Assigned each SA curve a stable cool color and distinct line dash, separate from the red Withstand and amber Safety margin IC lines. The same style is used in report PNGs generated from the figures.
- Added AppTest checks for paired state transitions, plot routing on both analysis views, voltage fallback and distinct SA styles.

## 2026-11-06 — make index range control both analysis views

- Show the ranked-index range control on Summary and All envelopes, preserving its selection when switching between the two.
- Apply the selected bounds as explicit Plotly x-axis limits as well as the existing row filter, so the chosen interval is visible and an earlier chart zoom cannot keep stale limits.
- Added AppTest coverage for both figures and the view-switch state.

## 2026-11-06 — reuse stable data across tab reruns

- Cache Case/MM option catalogs and the source-derived Data & references tables under the existing project-content signature, with a three-source-set limit.
- Data & references updates when project files change; analysis selections and chart controls do not affect it. Tab navigation still reruns Streamlit and re-emits the active view, but the cached source-derived work is reused. The chart-width sensor is skipped on this plot-free tab.
- Five warm 05-data Data & references AppTest reruns decreased from the previous 0.378 s median to 0.092 s; upload-signature invalidation, cache reuse and tab-specific sensor behavior are covered by regression tests. See [PERFORMANCE.md](PERFORMANCE.md).

## 2026-11-06 — use the MPE browser icon and prepare Community Cloud deployment

- Reused the exact MPE browser-tab icon from the Load Flow and Harmonics dashboards; the existing sidebar wordmark is unchanged.
- Documented private GitHub and Streamlit Community Cloud deployment using the app root, `master` branch and Python 3.12.
- Added an AppTest assertion that the favicon asset is present.

## 2026-11-05 — fold the SA MM assignments table

- Placed the SA workbook's full MM assignments table inside a collapsed section on Data & references, using the same section for valid and invalid SA sources.
- Deferred blank-template workbook generation until download; creating it directly takes about 15 ms and was unnecessary on every Data & references rerun.
- Removed a duplicated filename-test definition that Python had been silently overriding, and removed redundant outer container scopes around the existing Case/MM selector helper.
- Added AppTest coverage for the collapsed table, its assignment contents, and deferred template generation.

## 2026-11-05 — restore selector panels beneath the main views

- Keep Summary, All envelopes and Data & references as the top-level tabs. Restore Cases and MM points as separate, equal-width chip panels in Summary and All envelopes; neither selector is a tab.
- Hide Cases and MM points on Data & references because those selections do not change its source details or validation.

## 2026-11-05 — remove unused analysis code and share selection helpers

- Reused `available_cases()` and `available_mms()` in the sidebar instead of repeating their Case/MM union logic.
- Removed the uncalled per-curve peak-summary helper and its test, plus an unused SA loader import from the UI module; source parsing remains centralized in `data_loader.py`.
- Shared string conversion for summary and detailed hover arrays and removed a duplicate Max_all hover-template branch.
- Added coverage for Case/MM union results and the Summary curve's governing Run/Fault hover data.
- Full regression suite after cleanup: 64 passed, 5 `openpyxl` warnings.

## 2026-11-05 — hide unavailable SA controls

- Show the SA limits toggle and selector only when a valid curve is mapped to the selected voltage; a valid workbook with curves for another voltage no longer gets an unreadable-workbook message.
- Place the SA All/Clear controls in an equal-width row below their count so the full `Clear` label is visible in the sidebar.
- Keep Cases and MM points in their own main-page tabs above the Summary / All envelopes / Data & references tabs.
- Added regression checks against both a voltage without an SA curve and the actual 05 test-data workbook, which has a curve at 66 kV but not at 33 kV.
- Audited reuse and runtime: the app already shares selection, curve aggregation, IC comparison, chart building and cache helpers. Converted detailed-curve hover metadata once per figure rather than once per curve; 05-data warm All envelopes reruns improved from a 2.235 s median to 1.863 s. Plotly trace construction remains the main Python-side cost; no chart or engineering-data reduction was made because it could change behavior.

## 2026-11-05 — keep controls hidden until project data is ready

- On an empty startup or incomplete required upload, leave only the project-file controls and source feedback in the sidebar; show voltage, IC, SA and envelope controls after non-empty LG, LL and MM data are loaded.
- Mount the plot-width sensor only when those required inputs are available. The plot-width sensor declares `setStateValue`; selection chips declare and use `setTriggerValue` for click events.
- Added empty-startup, partial-upload and regression checks for both component setters. Confirmed a fresh browser session shows only the upload interface with no browser errors.
- Updated the 05 test-data SA curve row expectation from 491 to the current workbook's 241 populated points. Full suite: 61 passed, 5 warnings.

## 2026-11-05 — use only the SA mapping and curve

- Made `SA_Curves` and `MM_Assignment` the only required SA sheets. The app no longer validates, filters or plots from `SA_Types`; optional metadata and calculation sheets are ignored.
- Scoped available SA choices to curves assigned to MM points at the selected nominal voltage, using `MM_Assignment.MM_ID` → `MM_blocks.Group` → `Un`. Selected MM assignments are checked by default; users may add other curves mapped to that voltage.
- Removed the old `SAs` conversion workflow and changed the downloadable template to the two required sheets.
- Added parser, export, UI and real `05_Test_data/SA.xlsx` checks for the supplied curve and mapping format.

## 2026-11-05 — correct the on-page Summary legend

- Fixed the Streamlit Summary page so `Maximum envelope` is visible in the curve legend, with IC/SA limits still on their separate row below.
- Reduced the Summary-only gap between the plot and its legend rows; detailed-envelope page spacing is unchanged.
- Restored report PNG legend placement to the earlier approved layout after comparing the prior and changed downloads. The report export layout is independent of this page fix.
- Added regression coverage for the Summary page legend and report PNG placement.

## 2026-11-05 — add A4-ready report chart downloads

- Added one report-chart ZIP action beside the workbook action on each analysis view. It contains separate fixed-size 1800 × 1050 px LG and LL PNGs; at 17 cm wide, both fit on an A4 portrait page with captions.
- Summary exports keep curve and limit labels in one legend below the chart. All envelopes exports keep only the IC/SA limit labels in that legend.
- The Summary export includes the `Maximum envelope` label. Report PNG legend spacing preserves the approved layout.
- Added Kaleido and Chromium deployment dependencies and regression checks for fixed PNG dimensions, ZIP contents and export-only legend behavior.

## 2026-11-05 — keep voltage and channel pills label-sized

- Set the shared Voltage level and Envelope channel pill widgets to content width, so each chip follows its label instead of stretching to fill a row. Reduced horizontal padding on the channel pills so all four choices fit on one row at the standard sidebar width and wrap only when the sidebar is narrower.
- Kept the All envelopes channel options on the shared single-select pill helper and retained the AppTest check for its four options, Max_all default, single-select mode and wrapping.

## 2026-11-05 — optimize the 05 test-data All envelopes workflow

- Group detailed plot rows by Case/MM once, calculate the full/SFO/TOV IC comparisons together per measurement, and reuse the results for the violation tables and workbook.
- Store constant Case/MM hover labels once per Plotly trace while retaining point-level Run/Fault and phase identity.
- On the 05 dataset at 66 kV, the AppTest All envelopes rerun decreased from 11.458 s to 3.262 s, and row-selection rerun from 11.405 s to 3.161 s. The two serialized figures decreased from 19.22 MiB to 12.31 MiB. Browser drawing and network time are unmeasured; see [PERFORMANCE.md](PERFORMANCE.md).
- Added a regression check for the compact hover data and reran the full test suite.

## 2026-11-05 — split IC violations and compact the controls and legend

- Split All envelopes IC results into SFO (`Index_s < 0.020 s`) and TOV (`Index_s >= 0.020 s`) tables below both plots. Both follow the selected Withstand or Safety margin reference; each table ranks only its own segment and keeps grouped `Run (Fault_type)` labels.
- Changed voltage level from a segmented control to wrapping single-select pills, so additional levels flow onto new rows without stretching the last option.
- Bounded native Plotly legend heights and placed the IC/SA legend below the curve legend. Long curve lists scroll within the legend rather than extending the figure to show every label.
- Deferred SA violation calculations until actual exposure-time data is available. SA `Duration_s` values cannot be compared as violations against the envelope's ranked index, and source points are not interpolated.
- Added regression coverage for the exact 20 ms split, both legend-height bounds, wrapping voltage pills across all four 05-project levels, and the deferred SA comparison.

## 2026-11-05 — support both PSCAD workbook versions and repeated exports

- Recognize both `Input_Data_PSCAD_Python_v11*.xlsx` and `Input_Data_PSCAD_Python_0.11*.xlsx` input workbooks.
- Remove exact duplicate CSV rows during load and show a warning; different values sharing the same Case/MM/index still block plotting.
- Added regression coverage for the 05 second-project archive, its four voltage levels, and duplicate cleanup.
- Enable local Streamlit source reruns. `run_app.bat` starts a fresh server on the first free port from 8501 to 8510 and keeps its command window open for logs and Ctrl+C shutdown; it does not reuse an older server process.

## 2026-11-04 — remove redundant project-file actions

- Removed the project-level Reload and Clear buttons. Uploaded content is held in memory, so changed files already get a new content signature and load automatically; Reload only forced the same bytes through parsing again.
- Use the file uploader's X beside selected files to remove them. Case and MM point All/Clear controls remain with their respective selectors.

## 2026-11-04 — audit simplification and performance

- Reused the All envelopes LG/LL selections for manual-axis bounds and figures, avoiding a second filter/sort pass. The same AppTest workload improved from a 0.963 s to a 0.797 s median.
- Applied workbook formatting through the existing `ExcelWriter` workbook and removed the reopen/resave pass. The app-equivalent export improved from a 14.220 s to a 6.487 s median; sheet data and required formatting remain covered by tests.
- Removed the unused nearest-reference-crossing helper and unused imports/temporary figure dictionaries. Refreshed the performance, architecture and validation records and added a workbook-format regression check.
- The adaptive legend was not changed; its actual column layout still needs multi-width browser verification.

## 2026-11-04 — revised sidebar and upload workflow

- Restored both supported hosted input paths: one project ZIP or individual CSV/XLSX files, with mixed uploads rejected.
- Kept Voltage and IC reference in the left sidebar; Cases and MM points use separate bordered, equal-width chip sections on the main page. SA limits remain in the sidebar, are scoped to the selected voltage, and default compatible curves appear on the Summary LG plot.
- Replaced the manual Limits annotation row with native Plotly legend entries. Envelope curves come first; IC/SA limits follow with matching font and alignment. IC Withstand is reddish and Safety margin amber.
- Shortened the plot axis to `Envelope index (s)` and removed extra CSV and chart-image downloads, including Plotly's PNG camera button. Each analysis view has one results-workbook action; zoom and pan remain available.
- Simplified workbook assessment status to `Reference comparison on envelope index`, removing the longer time/compliance explanation from the exported report.
- Added AppTests for empty startup, ZIP and individual uploads, sidebar defaults and chip actions. Updated app reference, source contract, traceability, validation and performance records; refreshed Graphify after these changes.
- Kept SA selection scoped to project and voltage so changing the main-page MM selection does not reset the selected SA limits.
- Moved the All envelopes exceedance table below both plots and replaced its ranked-sample display with a grouped list of violating `Run (Fault_type)` pairs for `Max_all` rows.
- Replaced the guessed fractional legend sizing with a hidden responsive width sensor. Pixel entry widths now use the rendered chart width and the longest label, capped at three columns; IC/SA limits remain aligned on a separate row below all curves.

## 2026-11-04 — initial hosted upload and compact-control layout (superseded)

- Replaced the local server-folder fallback and multi-file uploader with one in-memory project ZIP containing LGp, LLp, the PSCAD input workbook and optional SA.xlsx / SA_*.xlsx.
- Put short Reload and Clear buttons together. Source ZIP discovery and parsed project data remain content-keyed; Reload changes only the active session's project-load key.
- Moved shared Voltage level and IC reference chips into the sidebar. Stacked Cases and MM points in distinct bordered, equal-width checkbox grids, with All/Clear beside each section title.
- Removed curve-peak tables from the app. Added an All envelopes exceedance table ranked by integrated excess above the selected IC reference on the ranked index; row selection highlights the matching plot curve.
- Made case/MM legend labels compact and put IC/SA names in a dedicated Limits row. Removed assignment/comparison qualifiers and source-document filenames from the plot key and tooltip.
- Removed the synthetic SA example download and raw normalized source-point table from the UI. Kept supplied SA points in the results workbook and hid `Source_Document` in the app table.
- Updated app reference, data contract, architecture, traceability, validation and performance documentation; Graphify map refreshed after validation.

## 2026-11-04 — MPE sidebar branding

- Added the MPE wordmark to the top of the left sidebar, matching the Harmonics dashboard.

## 2026-11-04 — first implementation

- Created a standalone Streamlit/Plotly app under `01_App` with read-only source loading, source-aware cache, grouped validation, detailed and independent summary views, MM-specific IC references, explicit SA import/assignment, legacy conversion, and exports.
- Added blank and synthetic SA workbook helpers for development and tests; the synthetic example is not part of the final app UI.
- Added regression tests and documentation for source/index semantics and unknown SDPF/legacy SA basis.
- Deferred: chronological TOV reconstruction/compliance, SA V–I and energy calculations, manufacturer datasheet digitisation, and inferred/extrapolated sub-0.1 s withstand values.

## 2026-11-04 — Summary-first UI and revised SA/IC contract

- Made Summary the default view; moved individual envelopes to a separate tab and source/reference/validation detail to the final tab.
- Replaced voltage, case and MM dropdowns with visible choices; increased chart height and moved phase/index/manual-axis controls into the detailed view.
- Switched the SA parser to the wide `SA_Curves` contract, kept exact IDs and blanks, retained all 14 `SA_Types` fields, and reduced required assignments to exact `MM_ID`/`SA_ID`.
- Removed WLs from source discovery and used only `MM_blocks` for IC. Added upload-set replacement and a clear action.
- Made the results workbook the single primary export and included the supplied SA source values when available; CSV and chart images are in More downloads.
- Added traceability across source evidence, modules, tests and browser acceptance checks.
