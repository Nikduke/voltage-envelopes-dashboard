# App purpose and UI decisions

## App purpose

The app answers: **for the selected voltage level, Cases, MM points and references, what do the highest selected LG and LL representative envelopes look like, and which individual envelopes exceed the IC reference?** Summary is the main dashboard and shows one maximum envelope per measurement. All envelopes is the separate investigation view for individual curves and exceedance ranking. Source details and validation live in the final tab.

The app is a hosted, upload-and-inspect dashboard. It reads project snapshots in memory; it does not poll or monitor a live system.

## Primary flow

1. **Sidebar:** upload one project ZIP or the individual LGp/LLp CSVs and a PSCAD workbook named `Input_Data_PSCAD_Python_v11*.xlsx` or `Input_Data_PSCAD_Python_0.11*.xlsx`, optionally with SA.xlsx. Use the uploader's X beside each file to remove it; changed uploads load automatically.
2. **View controls:** choose voltage from wrapping single-select chips and the IC reference from the two-option segmented control in the sidebar. The main page then shows the Cases and MM points panels beneath the view tabs on Summary and All envelopes; these selectors are not shown on Data & references. The SA toggle and limit chips appear in the sidebar only when a valid curve is mapped to an MM point at the selected voltage. The available curves are mapped through `MM_Assignment.MM_ID` → `MM_blocks.Group` and filtered by `MM_blocks.Un`; assignments to selected MM points are checked by default, and same-voltage alternatives can be added. On All envelopes, the index range and envelope channel are inside Envelope controls.
3. **Summary:** read the full-width LG and LL maximum-envelope plots.
4. **All envelopes:** inspect individual curves and the exceedance table. Selecting a table row highlights the matching Case/MM curve.
5. **Data & references:** inspect source details, IC/SA conventions and the two-sheet SA template. Validation is last on this page.

The upload contains `LGp.csv`, `LLp.csv`, and `Input_Data_PSCAD_Python_v11*.xlsx`; it may also contain `SA.xlsx` or `SA_*.xlsx`. Users may upload these individually instead. The app rejects a ZIP mixed with individual files. All sources are read in memory and there is no local-folder control.

On an empty startup, or while required project inputs are incomplete, the sidebar shows only the project upload interface and any source-selection or missing-file feedback. Voltage, IC, SA and envelope controls appear once non-empty LG, LL and MM data are available. The plot-width sensor also mounts only when those dashboard inputs are ready.

Voltage and IC controls are shared across Summary and All envelopes. Moving controls into the sidebar does not change calculation speed: selector changes rerun the Streamlit script, while source discovery and parsed project data are cached by uploaded content identity.

## Selection layout

The Summary / All envelopes / Data & references tabs are at the top of the main page. Summary and All envelopes start with the original Cases and MM points selector panels side by side. Data & references omits these selectors because they do not affect source details or validation. Each analysis panel is bordered; chips keep their natural width and wrap in reading order. Headings show counts inline, for example `Cases (6/6)` and `MM points (8/8)`, with All and Clear beside the relevant heading.

IC reference is a two-option segmented control: Safety margin comes first and is selected by default; Withstand is second. Voltage levels and Envelope channel use wrapping, single-select chips sized to their labels, not stretched to fill a row. Envelope channel uses compact horizontal padding so all four choices fit on one row in the standard sidebar; they wrap only when the available sidebar width is narrower. The SA limits toggle and selector appear only when at least one valid SA curve is mapped to an MM point at the selected voltage. If none is available for that voltage, both controls are hidden. The SA All/Clear buttons use an equal-width row below the count so both labels remain fully visible in the sidebar. Available curves are assigned to any MM point whose `Un` matches the selected voltage. Curves assigned to selected MM points are checked by default; users can add other curves mapped to that voltage. Each selected curve is shown once as an LG reference overlay. SA curves remain LG-only. The complete `MM_Assignment` table is inside a collapsed **MM assignments** section on Data & references. The SA workbook template is generated only when its download is requested.

When compatible SA curves exist, **SA on LGp + IC on LLp** is a third sidebar mode. It clears the two standalone toggles, keeps the SA selector visible, and places selected SA curves on LGp and the selected IC reference on LLp in Summary and All envelopes. Clicking either standalone toggle exits paired mode. If a voltage change leaves no compatible SA curve, paired mode is cleared and IC limits return on.

Envelope controls is a collapsed sidebar section shown on Summary and All envelopes. Its index range is shared by both views; selected bounds filter the plotted ranked-index samples and explicitly set the LG and LL x-axis limits. The Envelope channel chips appear only on All envelopes. Data & references has no envelope controls. There is no advanced chart-axis panel because the app uses automatic voltage bounds.

## Exceedances and legend

All envelopes places the LG and LL plots above two IC tables: **SFO part violations** for `Index_s < 0.020 s` and **TOV part violations** for `Index_s >= 0.020 s`. Both use the selected Withstand or Safety margin basis, and the 20 ms point belongs to TOV. Each table keeps one row per measurement, Case and MM point, even when several runs exceed the reference. For `Max_all`, **Runs with exceedance** lists the unique `Run (Fault_type)` pairs from samples above that part of the IC reference, such as `1 (AG), 12 (ABG)`. The labels come directly from the result CSV; no separate fault-code lookup is inferred. Run/fault labels are omitted for phase-specific channels, consistent with the source contract. Rows are ordered by descending part-specific integrated positive excess, then peak excess. Selecting a row highlights its Case/MM curve in the matching plot. Summary has no curve-peak table.

SA curves remain visual references only. Their `Duration_s` axis is elapsed time, while the envelope x-axis is a ranked index; the app does not report SA violations until actual exposure-time data is available.

Each plot presents one visually aligned key using native Plotly legend rows: envelope curves first, then a limits row for IC and SA traces. The Summary curve row explicitly includes `Maximum envelope`; its legend rows sit closer to the chart than the detailed-view legend rows. A small hidden width sensor reads the main chart container width; the Plotly figure width and pixel entry widths are recalculated from that measurement and the longest visible label, with up to three columns. Each legend has a maximum height and uses Plotly's native scroll when its entries exceed that space, so the chart does not grow to fit every curve label. Both rows start at the same left edge and use the same columns and font. IC Withstand is reddish; IC Safety margin is amber. Clicking a legend item toggles the corresponding trace.

SA references use stable cool colors and distinct line dashes, so selected SA curves differ from each other and from the red/amber IC limits. The same styles are used in report PNGs because export starts from the on-page figures.

The x-axis is labelled `Envelope index (s)`. The underlying source index is not a waveform timeline; that interpretation is documented here and in the data contract rather than in the plot label.

## Report chart downloads

Each analysis view has one **Download report charts (.zip)** action beside the results workbook. The ZIP contains separate LG and LL PNGs at a fixed 1800 × 1050 px size, independent of the browser window. At 17 cm wide each image is about 9.9 cm high, so the pair fits an A4 portrait page with a caption under each. Summary exports retain the `Maximum envelope` curve label and limit labels in one legend below the x-axis title. All envelopes exports keep the IC and SA limit labels in that legend and omit the many Case/MM curve labels. Export layout is prepared on cloned figures and keeps the original approved report-legend placement; on-page Summary spacing is controlled separately.

Static PNG generation uses Kaleido and Chromium. `requirements.txt` pins Kaleido, and `packages.txt` installs Chromium for Streamlit Community Cloud.

## Dashboard principles reused

The implementation selectively reuses layout and interaction patterns observed in the local Harmonics, Load Flow and FS Sweep dashboards. Those projects were inspected read-only on 4 November 2026; their files were not changed.

The browser tab uses the same MPE icon asset as the Load Flow and Harmonics dashboards; the larger MPE wordmark remains in the left sidebar.

| Principle | Reference observed | Applied here |
|---|---|---|
| Put the main analysis first | Harmonics tabs and Load Flow plot-first page hierarchy | Summary opens first and presents two large charts before reference details. |
| Keep controls near the analysis | Load Flow visible equipment selection | Voltage, IC and SA choices are in the left sidebar; Cases and MM chips sit above the views on the main page. |
| Make every choice visible and equal | Load Flow equipment selector | Voltage and Envelope channel use label-sized single-select wrapping chips; channel chip padding keeps four options on one standard-width row. Cases/MM use visible chips and inline counts; no dropdown hides the choices. |
| Keep less-used controls out of the main canvas | Local dashboard control patterns | Additional envelope and axis controls are collapsed at the bottom of the sidebar. |
| Use a responsive native legend | Load Flow automatic sizing, adapted with live chart width measurement | Plotly uses measured chart width and label length to set pixel-width entries, caps legend height with native scrolling, and keeps limits after curves. |
| Keep hosted sources separate from development folders | Harmonics uploader treatment | One ZIP or individual files are uploaded; no server-folder control appears. |
| Keep validation available after analysis | Harmonics grouped validation | Validation stays at the bottom of Data & references. |
| Cache source parsing, not every view state | Harmonics and Load Flow source-cache patterns | Upload discovery and parsed sources are cached; selections and figures are derived from cached frames. |
| Match interactions to data freshness | Dashboard monitoring-vs-analysis principle | No polling is added because project inputs are uploaded snapshots. |
| Keep MPE branding consistent | Harmonics dashboard wordmark | The MPE logo appears above Project files in the left sidebar. |

### Reference files inspected

- Load Flow dashboard controls and legend: `C:\Users\AndreyNikishin\MY_Code\Dashboards\LF_dash_app\Murakami\01_App\equipment_pills.py`, `plotting.py`, and `docs\APP_REFERENCE.md`.
- Harmonics dashboard MPE sidebar wordmark and source/validation treatment: `C:\Users\AndreyNikishin\MY_Code\Dashboards\Harmonics_dash_app\Murakami\01_App\app.py` and `assets\mpe_app_wordmark.png`.
- FS Sweep legend and plot sizing: `C:\Users\AndreyNikishin\MY_Code\Dashboards\FS_Sweep_Visualizer\fs_sweep_app_spline.py`.

These examples informed layout and interaction only. Their calculations, selection semantics and project-specific data handling were not copied.

## Summary meaning

At each source index, Summary takes the highest selected value independently and retains the winning Case/MM/Run/Fault type for hover and export. The IC trace follows the MM governing that point. Selected SA reference curves appear only on LG. The All envelopes tab focuses on individual curves that exceed the selected IC reference.

In paired limit mode, IC appears only on LL and the selected SA reference curves remain on LG.

## Export hierarchy

Each analysis tab has one results workbook download with selected data, exceedances, reference comparisons, validation, metadata, supplied SA assignments and curve points. The main views do not offer separate CSV, PNG or SVG downloads, and Plotly's PNG camera button is hidden while zoom and pan remain available. The two-sheet SA template is available under Data & references; the legacy conversion workflow has been removed.

The app does not expose a synthetic SA example download or the normalized source-point table as a separate view.
