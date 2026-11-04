"""Surge-arrester workbook import, validation and conversion helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
import re
from typing import Any

import numpy as np
import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from validation import make_issue


SA_TYPE_COLUMNS = (
    "SA_ID",
    "System_kV",
    "Manufacturer",
    "Model",
    "Curve_Type",
    "Duty_Condition",
    "Valid_From_s",
    "Valid_To_s",
    "Source_Document",
    "Verification_Status",
    "Voltage_Basis",
)
SA_CURVE_COLUMNS = ("SA_ID", "Duration_s", "Voltage_kV_peak")
SA_ASSIGNMENT_COLUMNS = ("MM_ID", "SA_ID", "Installation_Status", "Notes")
SA_SHEETS = ("SA_Types", "SA_Curves", "MM_Assignment")
INSTALLATION_STATUSES = ("Installed", "Not installed", "Unknown")
VERIFICATION_STATUSES = ("Verified", "Unverified", "Unknown")


@dataclass
class SAData:
    kind: str
    types: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=SA_TYPE_COLUMNS))
    curves: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=SA_CURVE_COLUMNS))
    assignments: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=SA_ASSIGNMENT_COLUMNS))
    legacy: pd.DataFrame = field(default_factory=pd.DataFrame)
    source_name: str = ""
    issues: list[dict[str, object]] = field(default_factory=list)


def _source_for_excel(source: str | bytes | bytearray) -> Any:
    return BytesIO(source) if isinstance(source, (bytes, bytearray)) else source


def _read_sheet(source: str | bytes | bytearray, sheet_name: str) -> pd.DataFrame:
    with pd.ExcelFile(_source_for_excel(source), engine="openpyxl") as workbook:
        return pd.read_excel(workbook, sheet_name=sheet_name)


def _empty_sa_data(kind: str, source_name: str, issues: list[dict[str, object]]) -> SAData:
    return SAData(kind=kind, source_name=source_name, issues=issues)


def _legacy_sa_id(element: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", element).strip("_").upper()
    return f"LEGACY_{slug or 'SA'}"


def load_sa_workbook(source: str | bytes | bytearray, source_name: str) -> SAData:
    """Load either the validated three-sheet format or the legacy SAs sheet.

    Excel handles are closed before returning. Legacy data is preserved as a
    visual comparison with unknown basis and no inferred MM assignments.
    """
    issues: list[dict[str, object]] = []
    try:
        with pd.ExcelFile(_source_for_excel(source), engine="openpyxl") as workbook:
            sheet_names = set(workbook.sheet_names)
            if set(SA_SHEETS).issubset(sheet_names):
                types = pd.read_excel(workbook, sheet_name="SA_Types")
                curves = pd.read_excel(workbook, sheet_name="SA_Curves")
                assignments = pd.read_excel(workbook, sheet_name="MM_Assignment")
                return _validate_new_sa(types, curves, assignments, source_name)
            legacy_sheet = next((name for name in workbook.sheet_names if name.casefold() == "sas"), None)
            if legacy_sheet is not None:
                legacy = pd.read_excel(workbook, sheet_name=legacy_sheet)
            else:
                return _empty_sa_data(
                    "invalid",
                    source_name,
                    [make_issue("Error", "SA workbook", "missing_sheets", f"Expected sheets {', '.join(SA_SHEETS)} or a legacy SAs sheet.")],
                )
    except Exception as exc:
        return _empty_sa_data(
            "invalid",
            source_name,
            [make_issue("Error", "SA workbook", "read_error", f"Could not read the workbook: {exc}")],
        )

    legacy.columns = [str(column).strip() for column in legacy.columns]
    required = ("Time (s)", "Element", "TOV capability")
    missing = [column for column in required if column not in legacy.columns]
    if missing:
        return _empty_sa_data(
            "invalid",
            source_name,
            [make_issue("Error", "Legacy SA workbook", "missing_legacy_columns", f"Missing legacy columns: {', '.join(missing)}.")],
        )

    legacy = legacy.loc[:, list(required)].copy()
    legacy["Time (s)"] = pd.to_numeric(legacy["Time (s)"], errors="coerce")
    legacy["TOV capability"] = pd.to_numeric(legacy["TOV capability"], errors="coerce")
    invalid = legacy["Time (s)"].isna() | legacy["TOV capability"].isna()
    if invalid.any():
        issues.append(
            make_issue(
                "Error",
                "Legacy SA workbook",
                "invalid_legacy_numeric",
                f"{int(invalid.sum())} legacy rows have non-numeric duration or voltage values.",
            )
        )
    legacy = legacy.loc[~invalid].copy()
    legacy["Element"] = legacy["Element"].astype(str).str.strip()
    empty_elements = legacy["Element"].eq("")
    if empty_elements.any():
        issues.append(make_issue("Error", "Legacy SA workbook", "blank_legacy_element", f"{int(empty_elements.sum())} legacy rows have a blank Element."))
        legacy = legacy.loc[~empty_elements].copy()

    types_rows: list[dict[str, object]] = []
    curve_frames: list[pd.DataFrame] = []
    duplicate_count = int(legacy.duplicated(["Element", "Time (s)"]).sum())
    if duplicate_count:
        issues.append(make_issue("Error", "Legacy SA workbook", "duplicate_legacy_duration", f"{duplicate_count} duplicate Element/Time rows were found."))
    for element, group in legacy.groupby("Element", sort=False):
        sa_id = _legacy_sa_id(str(element))
        group = group.copy()
        if not group["Time (s)"].is_monotonic_increasing:
            issues.append(make_issue("Error", "Legacy SA workbook", "unordered_legacy_duration", f"Durations for {element} are not ordered."))
        types_rows.append(
            {
                "SA_ID": sa_id,
                "System_kV": np.nan,
                "Manufacturer": "Unknown",
                "Model": str(element),
                "Curve_Type": "TOV_withstand",
                "Duty_Condition": "Legacy duty condition not documented",
                "Valid_From_s": float(group["Time (s)"].min()),
                "Valid_To_s": float(group["Time (s)"].max()),
                "Source_Document": source_name,
                "Verification_Status": "Unknown",
                "Voltage_Basis": "Unknown",
            }
        )
        curve_frames.append(
            pd.DataFrame(
                {
                    "SA_ID": sa_id,
                    "Duration_s": group["Time (s)"].to_numpy(dtype=float),
                    "Voltage_kV_peak": group["TOV capability"].to_numpy(dtype=float),
                }
            )
        )
    issues.append(
        make_issue(
            "Warning",
            "Legacy SA workbook",
            "legacy_unknown_basis",
            "Legacy curves are retained as supplied. Voltage basis, manufacturer validation, duty conditions and MM assignments are unknown; no assignment is inferred.",
        )
    )
    types = pd.DataFrame(types_rows, columns=SA_TYPE_COLUMNS)
    curves = pd.concat(curve_frames, ignore_index=True) if curve_frames else pd.DataFrame(columns=SA_CURVE_COLUMNS)
    return SAData(
        kind="legacy",
        types=types,
        curves=curves,
        assignments=pd.DataFrame(columns=SA_ASSIGNMENT_COLUMNS),
        legacy=legacy,
        source_name=source_name,
        issues=issues,
    )


def _validate_new_sa(
    types: pd.DataFrame, curves: pd.DataFrame, assignments: pd.DataFrame, source_name: str
) -> SAData:
    issues: list[dict[str, object]] = []
    types = types.copy()
    curves = curves.copy()
    assignments = assignments.copy()
    types.columns = [str(column).strip() for column in types.columns]
    curves.columns = [str(column).strip() for column in curves.columns]
    assignments.columns = [str(column).strip() for column in assignments.columns]
    missing_types = [column for column in SA_TYPE_COLUMNS if column not in types.columns]
    missing_curves = [column for column in SA_CURVE_COLUMNS if column not in curves.columns]
    missing_assignments = [column for column in SA_ASSIGNMENT_COLUMNS[:3] if column not in assignments.columns]
    if missing_types or missing_curves or missing_assignments:
        parts = []
        if missing_types:
            parts.append(f"SA_Types: {', '.join(missing_types)}")
        if missing_curves:
            parts.append(f"SA_Curves: {', '.join(missing_curves)}")
        if missing_assignments:
            parts.append(f"MM_Assignment: {', '.join(missing_assignments)}")
        return _empty_sa_data(
            "invalid",
            source_name,
            [make_issue("Error", "SA workbook", "missing_sa_columns", "Missing required columns: " + "; ".join(parts) + ".")],
        )
    if "Notes" not in assignments.columns:
        assignments["Notes"] = ""

    for frame, id_column, name in ((types, "SA_ID", "SA_Types"), (curves, "SA_ID", "SA_Curves")):
        frame[id_column] = frame[id_column].fillna("").astype(str).str.strip()
        if frame[id_column].eq("").any():
            issues.append(make_issue("Error", "SA workbook", f"blank_{name.casefold()}_id", f"{name} contains blank SA_ID values."))
    duplicate_types = types.loc[types["SA_ID"].duplicated(keep=False), "SA_ID"].unique().tolist()
    if duplicate_types:
        issues.append(make_issue("Error", "SA workbook", "duplicate_sa_id", f"SA_ID must be unique: {', '.join(map(str, duplicate_types[:8]))}."))

    for column in ("System_kV", "Valid_From_s", "Valid_To_s"):
        types[column] = pd.to_numeric(types[column], errors="coerce")
        bad = types[column].isna() | ~np.isfinite(types[column].to_numpy(dtype=float, na_value=np.nan))
        if bad.any():
            issues.append(make_issue("Error", "SA workbook", f"invalid_type_{column.casefold()}", f"{int(bad.sum())} SA_Types rows have invalid {column} values."))
    for column in ("Duration_s", "Voltage_kV_peak"):
        curves[column] = pd.to_numeric(curves[column], errors="coerce")
        bad = curves[column].isna() | ~np.isfinite(curves[column].to_numpy(dtype=float, na_value=np.nan))
        if bad.any():
            issues.append(make_issue("Error", "SA workbook", f"invalid_curve_{column.casefold()}", f"{int(bad.sum())} SA_Curves rows have invalid {column} values."))

    duplicate_points = int(curves.duplicated(["SA_ID", "Duration_s"]).sum())
    if duplicate_points:
        issues.append(make_issue("Error", "SA workbook", "duplicate_sa_duration", f"{duplicate_points} duplicate SA_ID/Duration_s curve points were found."))
    for sa_id, group in curves.groupby("SA_ID", sort=False):
        if not group["Duration_s"].is_monotonic_increasing:
            issues.append(make_issue("Error", "SA workbook", "unordered_sa_duration", f"Durations for {sa_id} must be strictly ordered as supplied."))
        if (group["Duration_s"] <= 0).any():
            issues.append(make_issue("Error", "SA workbook", "nonpositive_sa_duration", f"Durations for {sa_id} must be positive."))
        if (group["Voltage_kV_peak"] <= 0).any():
            issues.append(make_issue("Error", "SA workbook", "nonpositive_sa_voltage", f"Voltages for {sa_id} must be positive."))

    type_ids = set(types["SA_ID"])
    curve_ids = set(curves["SA_ID"])
    for sa_id in sorted(type_ids - curve_ids):
        issues.append(make_issue("Warning", "SA workbook", "missing_sa_curve", f"SA type {sa_id} has no curve and cannot be plotted."))
    for sa_id in sorted(curve_ids - type_ids):
        issues.append(make_issue("Error", "SA workbook", "orphan_sa_curve", f"Curve SA_ID {sa_id} has no matching SA_Types row."))

    type_lookup = types.set_index("SA_ID", drop=False)
    for sa_id, group in curves.groupby("SA_ID", sort=False):
        if sa_id not in type_lookup.index:
            continue
        type_row = type_lookup.loc[sa_id]
        if isinstance(type_row, pd.DataFrame):
            type_row = type_row.iloc[0]
        outside = group["Duration_s"].lt(type_row["Valid_From_s"]) | group["Duration_s"].gt(type_row["Valid_To_s"])
        if outside.any():
            issues.append(make_issue("Error", "SA workbook", "curve_outside_valid_range", f"{int(outside.sum())} points for {sa_id} lie outside Valid_From_s/Valid_To_s."))

    statuses = types["Verification_Status"].fillna("").astype(str).str.strip()
    invalid_status = ~statuses.isin(VERIFICATION_STATUSES)
    if invalid_status.any():
        issues.append(make_issue("Warning", "SA workbook", "unknown_verification_status", f"{int(invalid_status.sum())} SA_Types rows have an empty or unrecognised Verification_Status."))
    bases = types["Voltage_Basis"].fillna("").astype(str).str.strip().str.casefold()
    unknown_basis = ~bases.eq("kv_peak")
    if unknown_basis.any():
        issues.append(make_issue("Warning", "SA workbook", "unknown_voltage_basis", f"{int(unknown_basis.sum())} SA types do not declare Voltage_Basis as kV_peak and are hidden from default overlays."))
    unsupported = types["Curve_Type"].fillna("").astype(str).str.strip().ne("TOV_withstand")
    if unsupported.any():
        issues.append(make_issue("Warning", "SA workbook", "unsupported_curve_type", f"{int(unsupported.sum())} SA types are not TOV_withstand and are not plotted."))

    assignments["MM_ID"] = assignments["MM_ID"].fillna("").astype(str).str.strip()
    assignments["SA_ID"] = assignments["SA_ID"].fillna("").astype(str).str.strip()
    assignments["Installation_Status"] = assignments["Installation_Status"].fillna("").astype(str).str.strip()
    invalid_installation = ~assignments["Installation_Status"].isin(INSTALLATION_STATUSES)
    if invalid_installation.any():
        issues.append(make_issue("Error", "SA assignments", "invalid_installation_status", f"{int(invalid_installation.sum())} assignments have an invalid Installation_Status."))
    duplicate_mms = assignments.loc[assignments["MM_ID"].duplicated(keep=False) & assignments["MM_ID"].ne(""), "MM_ID"].unique().tolist()
    if duplicate_mms:
        issues.append(make_issue("Error", "SA assignments", "duplicate_mm_assignment", f"MM_ID assignments must be unique: {', '.join(duplicate_mms[:8])}."))
    invalid_refs = sorted(set(assignments.loc[assignments["SA_ID"].ne(""), "SA_ID"]) - type_ids)
    if invalid_refs:
        issues.append(make_issue("Error", "SA assignments", "unknown_assigned_sa", f"Assignments refer to unknown SA_ID values: {', '.join(invalid_refs[:8])}."))
    installed_empty = assignments["Installation_Status"].eq("Installed") & assignments["SA_ID"].eq("")
    if installed_empty.any():
        issues.append(make_issue("Warning", "SA assignments", "installed_without_sa", f"{int(installed_empty.sum())} MM points are marked Installed with no SA_ID."))

    return SAData(
        kind="new",
        types=types.loc[:, list(SA_TYPE_COLUMNS)],
        curves=curves.loc[:, list(SA_CURVE_COLUMNS)],
        assignments=assignments.loc[:, list(SA_ASSIGNMENT_COLUMNS)],
        source_name=source_name,
        issues=issues,
    )


def validate_sa_compatibility(sa: SAData | None, mm_blocks: pd.DataFrame | None) -> list[dict[str, object]]:
    if sa is None or sa.kind != "new" or mm_blocks is None or "Group" not in mm_blocks.columns:
        return []
    issues: list[dict[str, object]] = []
    mm_lookup = mm_blocks.set_index("Group", drop=False)
    type_lookup = sa.types.set_index("SA_ID", drop=False)
    for _, assignment in sa.assignments.iterrows():
        mm_id = str(assignment["MM_ID"])
        sa_id = str(assignment["SA_ID"])
        if not mm_id or not sa_id:
            continue
        if mm_id not in mm_lookup.index:
            issues.append(make_issue("Warning", "SA assignments", "unknown_assigned_mm", f"Assignment MM_ID {mm_id} is absent from MM_blocks."))
            continue
        if sa_id not in type_lookup.index:
            continue
        mm_row = mm_lookup.loc[mm_id]
        sa_row = type_lookup.loc[sa_id]
        if isinstance(mm_row, pd.DataFrame):
            mm_row = mm_row.iloc[0]
        if isinstance(sa_row, pd.DataFrame):
            sa_row = sa_row.iloc[0]
        if pd.notna(mm_row.get("Un")) and pd.notna(sa_row.get("System_kV")) and not np.isclose(float(mm_row["Un"]), float(sa_row["System_kV"]), rtol=0.0, atol=1e-6):
            issues.append(make_issue("Error", "SA assignments", "sa_voltage_mismatch", f"Assigned SA {sa_id} is {sa_row['System_kV']:g} kV but MM point {mm_id} is {mm_row['Un']:g} kV."))
    return issues


def interpolate_sa(
    curves: pd.DataFrame,
    sa_id: str,
    index_s: np.ndarray,
    valid_from_s: float,
    valid_to_s: float,
) -> np.ndarray:
    """Interpolate a prepared SA reference only within its validated range."""
    points = curves.loc[curves["SA_ID"].astype(str).eq(str(sa_id))].sort_values("Duration_s")
    x = points["Duration_s"].to_numpy(dtype=float)
    y = points["Voltage_kV_peak"].to_numpy(dtype=float)
    query = np.asarray(index_s, dtype=float)
    output = np.full(query.shape, np.nan, dtype=float)
    if len(x) < 2:
        return output
    inside = (
        (query >= max(float(valid_from_s), float(x[0])))
        & (query <= min(float(valid_to_s), float(x[-1])))
    )
    output[inside] = np.interp(query[inside], x, y)
    return output


def write_sa_workbook(
    types: pd.DataFrame,
    curves: pd.DataFrame,
    assignments: pd.DataFrame,
) -> bytes:
    """Write a professional, three-sheet SA workbook; formulas are not used."""
    frames = {
        "SA_Types": types.reindex(columns=SA_TYPE_COLUMNS),
        "SA_Curves": curves.reindex(columns=SA_CURVE_COLUMNS),
        "MM_Assignment": assignments.reindex(columns=SA_ASSIGNMENT_COLUMNS),
    }
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for sheet, frame in frames.items():
            frame.to_excel(writer, sheet_name=sheet, index=False)
    buffer.seek(0)
    workbook = load_workbook(buffer)
    comments = {
        "SA_Types": {
            "System_kV": "Nominal system voltage used to check compatibility with MM_blocks.Un.",
            "Curve_Type": "Use TOV_withstand for prepared temporary-overvoltage withstand references.",
            "Valid_From_s": "Minimum supported curve duration in seconds. No extrapolation is performed.",
            "Valid_To_s": "Maximum supported curve duration in seconds. No extrapolation is performed.",
            "Verification_Status": "Verified, Unverified or Unknown. This is source validation metadata, not a compliance result.",
            "Voltage_Basis": "Use kV_peak for curves that are confirmed on the app's plotted voltage basis.",
        },
        "SA_Curves": {
            "Duration_s": "Strictly increasing duration points in seconds. Curve points are linearly interpolated only within the supported range.",
            "Voltage_kV_peak": "Prepared TOV withstand limit in kV peak when Voltage_Basis is kV_peak.",
        },
        "MM_Assignment": {
            "MM_ID": "Exact MM_blocks.Group value. Assignments are never inferred from voltage alone.",
            "Installation_Status": "Installed, Not installed or Unknown.",
        },
    }
    for ws in workbook.worksheets:
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        ws.sheet_view.showGridLines = False
        for cell in ws[1]:
            cell.font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1F4E78")
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            if cell.value in comments.get(ws.title, {}):
                cell.comment = Comment(comments[ws.title][cell.value], "Voltage envelope dashboard")
        ws.row_dimensions[1].height = 32
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.font = Font(name="Arial", size=10, color="1F2937")
                if isinstance(cell.value, float):
                    cell.number_format = "0.000"
        for column_cells in ws.columns:
            letter = column_cells[0].column_letter
            max_len = max((len(str(cell.value)) for cell in column_cells if cell.value is not None), default=10)
            ws.column_dimensions[letter].width = min(max(max_len + 2, 12), 42)
    assignment_ws = workbook["MM_Assignment"]
    status_validation = DataValidation(type="list", formula1='"Installed,Not installed,Unknown"', allow_blank=True)
    assignment_ws.add_data_validation(status_validation)
    status_validation.add("C2:C1000")
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def create_blank_template() -> bytes:
    empty_types = pd.DataFrame(columns=SA_TYPE_COLUMNS)
    empty_curves = pd.DataFrame(columns=SA_CURVE_COLUMNS)
    empty_assignments = pd.DataFrame(columns=SA_ASSIGNMENT_COLUMNS)
    return write_sa_workbook(empty_types, empty_curves, empty_assignments)


def create_synthetic_example() -> bytes:
    types = pd.DataFrame(
        [
            {
                "SA_ID": "SYN_230_A",
                "System_kV": 230.0,
                "Manufacturer": "Synthetic",
                "Model": "Example A",
                "Curve_Type": "TOV_withstand",
                "Duty_Condition": "Synthetic example only",
                "Valid_From_s": 0.01,
                "Valid_To_s": 1.0,
                "Source_Document": "Synthetic data; not an engineering limit",
                "Verification_Status": "Unknown",
                "Voltage_Basis": "kV_peak",
            }
        ],
        columns=SA_TYPE_COLUMNS,
    )
    curves = pd.DataFrame(
        {
            "SA_ID": ["SYN_230_A"] * 5,
            "Duration_s": [0.01, 0.02, 0.05, 0.1, 1.0],
            "Voltage_kV_peak": [650.0, 610.0, 560.0, 520.0, 480.0],
        },
        columns=SA_CURVE_COLUMNS,
    )
    assignments = pd.DataFrame(
        [{"MM_ID": "MM_230_EXAMPLE", "SA_ID": "SYN_230_A", "Installation_Status": "Unknown", "Notes": "Synthetic mapping example only"}],
        columns=SA_ASSIGNMENT_COLUMNS,
    )
    return write_sa_workbook(types, curves, assignments)


def convert_legacy_to_new(
    sa_data: SAData,
    mm_blocks: pd.DataFrame,
    mapping: dict[str, dict[str, str]],
) -> bytes:
    """Export a legacy curve set after explicit per-element MM mapping."""
    if sa_data.kind != "legacy":
        raise ValueError("The selected SA workbook is not a legacy SAs workbook.")
    elements = sorted(sa_data.legacy["Element"].dropna().astype(str).unique())
    if any(element not in mapping or mapping[element].get("MM_ID") in (None, "", "Unassigned") for element in elements):
        raise ValueError("Assign every legacy Element to an MM point before exporting.")
    mm_ids = [mapping[element]["MM_ID"] for element in elements]
    if len(mm_ids) != len(set(mm_ids)):
        raise ValueError("Each legacy Element must map to a different MM point.")
    mm_lookup = mm_blocks.set_index("Group", drop=False)
    if any(mm_id not in mm_lookup.index for mm_id in mm_ids):
        raise ValueError("Every selected MM_ID must match an MM_blocks.Group value.")

    type_rows: list[dict[str, object]] = []
    assignment_rows: list[dict[str, object]] = []
    curve_frames: list[pd.DataFrame] = []
    type_lookup = sa_data.types.set_index("Model", drop=False)
    for element in elements:
        mm_id = mapping[element]["MM_ID"]
        status = mapping[element].get("Installation_Status", "Unknown")
        if status not in INSTALLATION_STATUSES:
            raise ValueError(f"Invalid installation status for {element}: {status}")
        source_type = type_lookup.loc[element]
        if isinstance(source_type, pd.DataFrame):
            source_type = source_type.iloc[0]
        sa_id = str(source_type["SA_ID"])
        curve = sa_data.curves.loc[sa_data.curves["SA_ID"].eq(sa_id)].copy()
        if curve.empty:
            raise ValueError(f"No legacy curve points were loaded for {element}.")
        mm_row = mm_lookup.loc[mm_id]
        if isinstance(mm_row, pd.DataFrame):
            mm_row = mm_row.iloc[0]
        type_rows.append(
            {
                "SA_ID": sa_id,
                "System_kV": float(mm_row["Un"]),
                "Manufacturer": "Unknown",
                "Model": element,
                "Curve_Type": "TOV_withstand",
                "Duty_Condition": "Legacy duty condition not documented",
                "Valid_From_s": float(curve["Duration_s"].min()),
                "Valid_To_s": float(curve["Duration_s"].max()),
                "Source_Document": sa_data.source_name,
                "Verification_Status": "Unknown",
                "Voltage_Basis": "Unknown",
            }
        )
        curve_frames.append(curve.loc[:, list(SA_CURVE_COLUMNS)])
        assignment_rows.append(
            {
                "MM_ID": mm_id,
                "SA_ID": sa_id,
                "Installation_Status": status,
                "Notes": "Explicit legacy mapping; source validation and voltage basis remain unknown.",
            }
        )
    types = pd.DataFrame(type_rows, columns=SA_TYPE_COLUMNS)
    curves = pd.concat(curve_frames, ignore_index=True)
    assignments = pd.DataFrame(assignment_rows, columns=SA_ASSIGNMENT_COLUMNS)
    return write_sa_workbook(types, curves, assignments)
