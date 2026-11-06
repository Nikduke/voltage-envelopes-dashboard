# Voltage Envelopes Dashboard

Streamlit dashboard for comparing PSCAD representative LG/LL voltage envelopes with MM-specific insulation-coordination (IC) references and selected surge-arrester (SA) curves.

## Run locally

Use the project `.venv` and pinned `requirements.txt`. Double-click `run_app.bat`; it starts a fresh Streamlit server on the first available port from 8501 to 8510, opens the browser, and leaves the command window open with live logs. Press Ctrl+C or close that window to stop the server. Closing the browser tab alone leaves the server running. In local development, Streamlit reruns the app when its source files are saved.

```powershell
.\.venv\Scripts\streamlit.exe run .\app.py
```

`run_app.bat` does not install packages. Run `run_checks.bat` to execute the test suite.

## Deploy to Streamlit Community Cloud

Create a private GitHub repository from this app folder and deploy `app.py` from the `master` branch. Choose Python 3.12 to match the local environment. `requirements.txt` installs the pinned Python packages, and `packages.txt` installs Chromium for report PNG exports. The app has no runtime secrets; users upload their own project files in the sidebar. Keep both the repository and Streamlit app private for internal engineering use. Streamlit Community Cloud needs access to the private GitHub repository before deployment.

## Load project inputs

In the sidebar, upload either **one project ZIP** or the usual individual source files:

- `LGp.csv`
- `LLp.csv`
- `Input_Data_PSCAD_Python_v11*.xlsx` or `Input_Data_PSCAD_Python_0.11*.xlsx` with an `MM_blocks` sheet
- optionally `SA.xlsx` or `SA_*.xlsx`

The app reads uploads in memory. Do not combine a ZIP with individual files in the same upload. If several candidates match one source role, choose the intended file in the sidebar. Use the uploader's X beside a file to remove it; a changed upload set is loaded and validated automatically. There is no local or server-folder source.

On a fresh start, the sidebar stays upload-only until non-empty LG, LL and MM data have loaded. Voltage, IC, SA and envelope controls appear after the required project inputs are ready.

An SA workbook needs only `SA_Curves` (`Duration_s` plus one column per SA curve) and `MM_Assignment` (`MM_ID`, `SA_ID`). `SA_Types` and calculation helper sheets are optional and ignored. An SA curve's voltage class comes from joining its MM assignment to `MM_blocks.Group` and reading that row's `Un`. The selector shows curves mapped to the selected voltage; curves mapped to selected MM points are checked by default, and other curves at that voltage can be selected too.

## Dashboard views

- **Summary** is the main view. It plots the pointwise maximum LG and LL envelopes over the selected Cases and MM points.
- **All envelopes** plots individual curves. Below the plots, separate SFO and TOV tables show exceedances for the matching part of the selected IC reference. Each row groups a measurement, Case and MM point; `Max_all` rows list unique `Run (Fault_type)` pairs. Select a row to highlight its curve.
- **Data & references** keeps source details and validation at the bottom, after the analysis views.

The Summary, All envelopes and Data & references tabs appear at the top of the main page. Summary and All envelopes have separate bordered, equal-width Cases and MM chip panels below the active tab; Data & references hides those filters because they do not affect that view. Voltage levels and Envelope channel are label-sized, single-select pills; the four channel options fit on one row at the standard sidebar width and wrap when needed. IC reference remains a two-option segmented control. SA limit chips show curves mapped to the selected voltage. Assignments to selected MM points are checked by default; additional same-voltage curves can be selected for the LG overlay. Envelope controls for index range and channel are near the bottom of the sidebar on All envelopes.

The Plotly legend uses automatic columns (up to three) and a native scroll area with a fixed maximum height. Summary shows `Maximum envelope` in the first legend row; IC and SA references start on a separate row below. IC tables compare ranked-index samples using the selected Withstand or Safety margin basis. SA curves remain visual references; no SA violation table is calculated until actual exposure-time data is available.

Each analysis view has one **results workbook** action and one **report charts (.zip)** action. The workbook contains selected values, exceedances, IC comparisons, validation, metadata, supplied SA assignments and curve points. The ZIP contains separate fixed-size 1800 × 1050 px LG and LL PNGs, sized to fit together on an A4 portrait page with captions when placed at about 17 cm wide. Summary PNGs retain the `Maximum envelope` curve label and limits in one legend below the x-axis title; All envelopes PNGs retain only the IC/SA limit labels there. Report PNGs preserve their original approved legend placement; their layout is independent of the on-page Summary legend spacing. Kaleido is pinned in `requirements.txt`, and `packages.txt` installs Chromium for Streamlit Community Cloud. The two-sheet SA template is available under Data & references; the legacy conversion workflow has been removed.

## Engineering interpretation

The source `Time (s)` is an index used to rank representative envelopes; it is not a reconstructed waveform. The app plots the IC convention from `MM_blocks`: SIWL before 0.020 s, SDPF × √2 from 0.020 s, and Safety margin = withstand peak / 1.15. The SFO table uses indices below 0.020 s; the TOV table includes 0.020 s and later indices. These are numerical comparisons on the ranked index, not chronological compliance results. SA curves use elapsed duration and are not compared to the ranked-index samples. The SDPF RMS basis is a project assumption. SA curves are source references; blanks are preserved, and the 0 s source point is not a physical zero-duration withstand value.

See [traceability](docs/TRACEABILITY.md), [app reference and design principles](docs/APP_REFERENCE.md), [data contract](docs/DATA_CONTRACT.md), [architecture](docs/ARCHITECTURE.md), [validation record](docs/VALIDATION.md), [performance record](docs/PERFORMANCE.md) and [changelog](docs/CHANGELOG.md).
