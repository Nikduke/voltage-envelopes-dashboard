# Changelog and deferred work

## 2026-11-04 — first implementation

- Created a standalone Streamlit/Plotly app under `01_App` with read-only source loading, source-aware cache, grouped validation, detailed and independent summary views, MM-specific IC references, explicit SA import/assignment, legacy conversion, and exports.
- Added blank and synthetic SA workbook downloads; static versions are included in `templates/`.
- Added regression tests and documentation for source/index semantics and unknown SDPF/legacy SA basis.
- Deferred: chronological TOV reconstruction/compliance, SA V–I and energy calculations, manufacturer datasheet digitisation, and inferred/extrapolated sub-0.1 s withstand values.
