# Validation and acceptance record

## Source inspection results

Verified against the read-only `../02_Excel_Example` files on 4 November 2026:

- LG and LL each contain 77,000 rows and all 12 required columns.
- Six cases, 27 result MM points and 31 configured `MM_blocks.Group` values.
- Four configured 22.8 kV points are absent from results. Eight C3 case/MM combinations (two cases × four 230 kV points) are missing and remain absent.
- No duplicate Case/MM/index keys; all required numeric fields are finite; `Max_all` matches `max(Max_A, Max_B, Max_C)` within 1e-8.
- LG and LL are loaded independently. Phase MM labels match `MM_name_all` in this sample.
- IC regression with the 1.15 safety margin gives zero LG and 444 LL ranked samples above the reference across 16 case/MM combinations. Raw withstand comparison gives zero for both measurements. The older 30/32 ms boundary is not used.
- 230 kV sample LG values: SIWL margin 730.4348 kV peak; SDPF converted to 650.5382 kV peak; SDPF margin 565.6854 kV peak. Index 0.018 s selects SIWL; exactly 0.020 s selects SDPF.
- Legacy SAs has 1,000 rows for two elements; source basis and assignment remain unknown. No automatic mapping is created.

## Checks

Run `run_checks.bat` or `.venv\Scripts\python.exe -m pytest -q`. Unit/regression tests cover source keys and counts, formula boundary and factors, summary winners/provenance, reference crossing counts, SA legacy/new-format conversion and no-extrapolation, workbook replacement, export metadata, and short/long legend output.

The actual UI browser smoke test, startup/reload/cache replacement and measured performance are recorded in `PERFORMANCE.md` after execution. Environment: Windows, local project `.venv`, CPython 3.12.13, Streamlit 1.66.1.
