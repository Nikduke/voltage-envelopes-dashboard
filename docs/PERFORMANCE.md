# Performance record

## Environment and method

Windows; project-local CPython 3.12.13 environment; Streamlit 1.66.1; pandas 3.1.0; NumPy 2.5.4; Plotly 7.1.0; sample source `LGp.csv` and `LLp.csv` (77,000 rows each), `Input_Data_PSCAD_Python_v11.xlsx`, and `SAs.xlsx`. UI timings are the app's server-side computation/render-preparation values and exclude browser drawing. Export timings use the app's Python export functions on the same local environment. No optimization claim is made without an equivalent before/after comparison.

## Measured results

| Operation | Result | Method |
|---|---:|---|
| Cold app start to first chart | Not timed | The Streamlit process was already running for the browser smoke test. |
| Source scan and parse | 0.001 s scan; 0.48 s parse and validation | Values reported in the app after loading all selected sources. |
| Warm summary view | 0.755 s server preparation; 109,238-byte payload | Summary view, one case and one 66 kV MM point; two visible charts. Excludes browser drawing. |
| Detailed view, broad selection | 3.319 s server preparation; 760,664-byte payload | Six cases and eight 66 kV MM points; 48 result curves plus eight IC references per measurement, across LG and LL. Excludes browser drawing. |
| Summary figure JSON | 148,042 bytes | Python figure JSON for one measurement with six cases and eight 66 kV MM points. |
| PNG export, one case/MM | 3.194 s; 40,802 bytes; 1400 × 450 px | First conversion in this measurement sequence; detailed curve plus IC reference. |
| PNG export, six cases/eight MMs | 2.536 s; 51,707 bytes; 1400 × 476 px | Summary curve plus eight IC references. |
| CSV export, 24,000 selected rows | 0.167 s; 9,837,601 bytes | Selected data with filters and assessment metadata. |
| XLSX export, 24,000 selected rows | 7.704 s; 1,094,782 bytes | Five-sheet workbook with provenance metadata. |
| SVG export | Not timed | Automated export test verified SVG output and all short/long legend names. |

The detailed and summary charts rendered in the browser. The app reports server preparation separately from browser drawing; no browser-only draw duration was captured. See the validation record for the dataset and interpretation constraints.
