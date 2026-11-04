# Voltage Envelopes App

- Keep all app code, configuration, docs and synthetic fixtures inside `01_App`.
- Treat `../02_Excel_Example` and other user-selected source folders as read-only.
- Use the local `.venv`; install only from the pinned `requirements.txt`.
- Preserve source Case/MM/index identity and governing provenance. `Time (s)` is a ranked representative-envelope index, not exposure time.
- Keep IC calculations in `limits.py`, grouping/provenance in `analysis.py`, and plotting in `plots.py`; do not add compliance conclusions from the representative CSVs.
- Do not infer SA assignments or voltage basis. Only compare SA curve values on a confirmed basis by default; any unknown-basis display must be explicitly marked comparison-only.
- Run `run_checks.bat` after app code changes and update the factual docs when behavior or data contracts change.
- Never write exports or converted workbooks into a source folder.
