# Architecture

## Data flow

```text
One session ZIP or individual-file upload
    -> data_loader.py (in-memory discovery, strict role matching)
    -> source discovery cache (uploaded file bytes)
    -> project-data cache (selected source content signature)
    -> validation.py (CSV, MM_blocks and cross-source findings)
    -> analysis.py (case/MM/index filtering, pointwise maxima, IC exceedance area)
    -> limits.py (project IC convention)
    -> sa_data.py (wide SA workbook parsing, gaps, exact assignment validation)
    -> plots.py (Summary and individual LG/LL figures, focused curve, native curve/limit legend)
    -> app.py (Summary / All envelopes / Data & references)
    -> exports.py (results workbook)
    -> chart_exports.py (fixed-size report PNGs; app figures are cloned before export)
```

## Module responsibilities

- `data_loader.py` recognizes `LGp.csv`, `LLp.csv`, both `Input_Data_PSCAD_Python_v11*.xlsx` and `Input_Data_PSCAD_Python_0.11*.xlsx`, and only new-format `SA.xlsx`/`SA_*.xlsx`. It reads ZIP members or individual uploads in memory, removes exact duplicate CSV rows while retaining a validation warning, rejects mixing the two input modes and never scans a local folder. Excel reads use context managers. Uploaded-content digests key source identity.
- `validation.py` reports missing input and source integrity findings. Blocking LG/LL CSV errors suppress chart output. SA source errors disable that SA input without blocking envelope/IC use.
- `analysis.py` filters exact Case/MM/index selections, computes pointwise maxima, and calculates ranked-index exceedances. The All envelopes view calculates the full, SFO (`Index_s < 0.020 s`) and TOV (`Index_s >= 0.020 s`) IC comparisons together for each measurement, including part-specific over-limit areas, then reuses those results for tables and workbook output.
- `limits.py` holds the single MM_blocks IC formula and the project-specific 20 ms/1.15 constants. LG and LL columns are independent.
- `sa_data.py` requires only wide `SA_Curves` and exact two-column `MM_Assignment`, preserves blank curve values as missing long-form rows, and ignores `SA_Types` and helper sheets. `app.py` derives SA voltage availability by joining each MM assignment to `MM_blocks.Group` and reading `Un`; it checks curves assigned to selected MMs by default and allows other curves mapped to that voltage. The old `SAs` conversion path has been removed.
- `plots.py` groups detailed envelope rows by Case/MM once per figure and plots supplied SA source points with gaps disconnected and no interpolation. The Summary IC trace follows the governing MM; All envelopes keeps one IC trace per selected MM. Per-trace Case/MM metadata avoids repeating those constant labels for every hover point. Curves, IC and SA limits share aligned native Plotly legends; columns adapt to chart width and labels, while a maximum legend height adds native scrolling for long curve lists.
- `exports.py` carries selected filters, provenance and interpretation metadata into the results workbook. If SA is present, its exact assignments and normalized source points are included. Worksheet formatting is applied before the single workbook save.
- `chart_exports.py` clones the current Plotly figures for report output, fixes their image size to 1800 × 1050 px, and packages LG/LL PNGs into one ZIP. Report charts use one legend below the plot: Summary keeps curve and limit labels; All envelopes hides Case/MM labels but retains IC/SA limit labels. App legends remain unchanged.
- `app.py` owns the ZIP or individual-file uploader, content-width wrapping single-select voltage and envelope-channel pills, compact channel-chip padding, sidebar controls, main-page Cases/MM chips, tab navigation, SFO/TOV table selection and the results-workbook and report-chart actions on each analysis view. SA curves remain visual overlays; no violation calculation is made while envelope x values are ranked indices rather than exposure times.

## Deployment and performance

`.streamlit/config.toml` enables headless hosting and leaves network binding to the host. For local use, `run_app.bat` selects the first available port from 8501–8510, starts a fresh foreground server in the visible command window, and opens the browser. The window shows server logs and owns Ctrl+C shutdown; closing the browser tab does not stop the process. The launcher does not reconnect to or reuse an older server. User uploads remain in Streamlit session state and are not written to the app folder.

Report PNG generation requires Kaleido and Chrome/Chromium. `requirements.txt` pins Kaleido; `packages.txt` installs Chromium on Streamlit Community Cloud. Images are rendered only when the user requests the ZIP download.

ZIP/file discovery and parsed project data are cached for at most three source snapshots. Case/MM option catalogs and the source-derived Data & references tables use the same content signature and three-entry bound, so they are reused across tab reruns and invalidated when any selected project file changes. Data & references does not depend on chart selections and skips the chart-width sensor. Selector changes filter cached frames; the All envelopes selection is shared by its axis controls and figures. Figures are built for the open tab. The app is a manual snapshot viewer and does not poll, create a database/API or parallelize the current workload. The 05 test-data workflows and measured before/after timings are recorded in [PERFORMANCE.md](PERFORMANCE.md).

## Traceability

[TRACEABILITY.md](TRACEABILITY.md) connects UX/engineering requirements to modules, data fields, tests and browser checks.
