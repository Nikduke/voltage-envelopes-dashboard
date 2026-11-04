# Voltage Envelopes Dashboard

Local Streamlit + Plotly viewer for PSCAD representative voltage envelopes, MM-specific insulation-coordination references and imported surge-arrester TOV characteristics.

## Run

The app uses the project-local Python 3.12 environment. From File Explorer, double-click `run_app.bat`; or run:

```powershell
.\.venv\Scripts\streamlit.exe run .\app.py
```

Open `http://127.0.0.1:8501`. `run_app.bat` does not install packages. To create or refresh the environment, install the exact versions in `requirements.txt` into `.venv`. Run checks with `run_checks.bat`.

The initial source folder is the adjacent `../02_Excel_Example`. Change it in the sidebar for another project. If multiple plausible files exist for a role, select the intended file. Session uploads are optional and stay in Streamlit memory; the app never writes to source folders.

## Views and outputs

- **Detailed comparison:** separate LG and LL charts, case/MM/voltage/index/channel filters, IC withstand or 1.15 safety-margin references, assigned SA comparisons, and selected-curve summaries.
- **Overall summary:** pointwise maxima across selected cases and MM points, with the winning source identity retained at each index; peak and reference comparison tables.
- **Limits & assignments:** MM_blocks, assumptions, SA metadata and assignments, legacy SA import/mapping, and the downloadable workbook template and synthetic example.
- Downloads: selected data CSV, multi-sheet XLSX, and PNG/SVG charts. Export metadata carries filters, units, source names, formula settings and assessment status.

## Assessment boundary

`Time (s)` in the result CSVs is the representative-envelope ranking index. It is not elapsed exposure time or a reconstructed waveform. Crossings against IC/SA curves are reference comparisons only. This version does not calculate physical TOV compliance, SA energy duty, SA V–I/energy curves, or manufacturer curve digitisation. MM_blocks does not declare SDPF units; the display uses the documented project assumption of kV RMS and converts once to kV peak with √2.

See [docs/APP_REFERENCE.md](docs/APP_REFERENCE.md), [docs/DATA_CONTRACT.md](docs/DATA_CONTRACT.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/VALIDATION.md](docs/VALIDATION.md), [docs/PERFORMANCE.md](docs/PERFORMANCE.md) and [docs/CHANGELOG.md](docs/CHANGELOG.md).
