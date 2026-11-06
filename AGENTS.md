# Voltage Envelopes App

- Keep all app code, configuration, docs and synthetic fixtures inside `01_App`.
- Treat `../04_Test_data`, `../02_Excel_Example` and all user-selected source folders as read-only.
- Use the local `.venv`; install only from the pinned `requirements.txt`.
- Preserve source Case/MM/index identity and governing provenance. `Time (s)` is a ranked representative-envelope index, not exposure time.
- Keep IC calculations in `limits.py`, grouping/provenance in `analysis.py`, and plotting in `plots.py`; do not add compliance conclusions from the representative CSVs.
- Read SA workbooks only through `SA.xlsx`/`SA_*.xlsx` discovery and the wide `SA_Curves` plus exact `MM_Assignment` contract. Preserve blank source points and gaps; never infer an MM assignment or nominal voltage from curve names or values. Determine voltage availability by joining `MM_Assignment.MM_ID` to `MM_blocks.Group` and reading `MM_blocks.Un`; default SA selections require an exact assignment to the selected MM points.
- Derive IC references from `MM_blocks` only. `WLs.xlsx` is not part of the normal source pipeline.
- Run `run_checks.bat` after app code changes and update the factual docs when behavior or data contracts change.
- Never write exports or converted workbooks into a source folder.
