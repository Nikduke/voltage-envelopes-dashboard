# Data contract and interpretation

## Representative-envelope CSVs

`LGp.csv` and `LLp.csv` each require `Time (s)`, `Max_A`, `Max_B`, `Max_C`, `MM_name_A`, `MM_name_B`, `MM_name_C`, `Max_all`, `Case`, `Run`, `Fault_type`, and `MM_name_all`. Values are imported without filling missing combinations. A curve is identified by exact `(Case, MM_name_all, Time (s))` keys; duplicates and non-finite numeric values block result plotting. Curves are sorted by index before display.

The sample's `Max_all` equals the row-wise maximum of its three phase values. Run and fault type can change across ranked rows. They are included in hover/export only for `Max_all`; they do not identify a continuous waveform and are never attached to separately selected phase maxima.

The `Time (s)` values are the representative-envelope ranked index produced by the upstream reduction. They are not chronological exposure time. The `Input_Data` final duration of 0.5 s is a separate PSCAD setting and does not make a 0.998 s ranked index invalid.

## IC catalogue

`Input_Data_PSCAD_Python_v11*.xlsx` must include `MM_blocks` columns `Group`, `Un`, `Um`, `SDPF_LG`, `SDPF_LL`, `SIWL_LG`, `SIWL_LL`, and `LIWL`. `Group` joins exactly to CSV `MM_name_all`. Missing MM/case combinations stay absent. Unmatched result MMs receive no IC line.

Project-specific reference convention:

- Ranked index `< 0.020 s`: SIWL, already treated as kV peak.
- Ranked index `>= 0.020 s`: SDPF converted from the assumed kV RMS basis to kV peak by `sqrt(2)` exactly once.
- Safety-margin references divide the selected raw reference by `1.15`.

The source workbook does not state SDPF units; kV RMS is a documented but unverified project convention. The 20 ms transition is also project-specific, not a universal IEC declaration. Input workbook name and factors accompany exports.

## Surge-arrester workbook

`SA_characteristics.xlsx` has three sheets:

- `SA_Types`: SA_ID, System_kV, Manufacturer, Model, Curve_Type, Duty_Condition, Valid_From_s, Valid_To_s, Source_Document, Verification_Status, Voltage_Basis.
- `SA_Curves`: long-form SA_ID, Duration_s, Voltage_kV_peak, strictly increasing and uniquely keyed by SA_ID/duration.
- `MM_Assignment`: exact MM_ID, SA_ID and Installation_Status (`Installed`, `Not installed`, `Unknown`), plus optional Notes.

Only `TOV_withstand` curves with declared `kV_peak` basis are eligible for default plotting. Interpolation is linear within the intersection of supplied points and declared validity bounds; extrapolation is not performed. Only `Installed` exact MM assignments are default. Alternative curves are marked comparison-only. Voltage compatibility is checked against MM_blocks.Un. Unknown verification status is metadata, not a compliance finding.

Legacy `SAs.xlsx` input uses `Time (s)`, `Element`, `TOV capability`. It stays unknown for verification, voltage basis and MM assignment until the user maps each element. Conversion exports a new workbook and leaves the source untouched. Values stay unchanged and unknown-basis; enabling raw-value display does not certify kV peak.

## Other sample sources

`WLs.xlsx` has `Time (s)`, `System`, `IC limit`, but is treated as a non-authoritative legacy comparison. The supplied Excel dashboard's internal pivot/model cache is inspected only as a functional reference and is not read at runtime.
