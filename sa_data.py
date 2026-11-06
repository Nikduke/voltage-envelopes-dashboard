"""Surge-arrester curve and MM assignment workbook import."""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

import numpy as np
import pandas as pd
from openpyxl import load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill

from validation import make_issue


SA_CURVE_COLUMNS = ("SA_ID", "Duration_s", "Voltage_kV_peak")
SA_ASSIGNMENT_COLUMNS = ("MM_ID", "SA_ID")
SA_SHEETS = ("SA_Curves", "MM_Assignment")


@dataclass
class SAData:
    kind: str
    curves: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=SA_CURVE_COLUMNS))
    assignments: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=SA_ASSIGNMENT_COLUMNS))
    source_name: str = ""
    issues: list[dict[str, object]] = field(default_factory=list)


def _source_for_excel(source: str | bytes | bytearray) -> Any:
    return BytesIO(source) if isinstance(source, (bytes, bytearray)) else source


def _empty_sa_data(kind: str, source_name: str, issues: list[dict[str, object]]) -> SAData:
    return SAData(kind=kind, source_name=source_name, issues=issues)


def _cell_text(value: object) -> str:
    return "" if pd.isna(value) else str(value)


def _read_wide_curves(source: str | bytes | bytearray) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    """Read raw headers before pandas can rename duplicate Excel column labels."""
    workbook = load_workbook(_source_for_excel(source), read_only=True, data_only=True)
    try:
        if "SA_Curves" not in workbook.sheetnames:
            return pd.DataFrame(), [make_issue("Error", "SA workbook", "missing_curve_sheet", "The workbook has no SA_Curves worksheet.")]
        worksheet = workbook["SA_Curves"]
        rows = list(worksheet.iter_rows(values_only=True))
    finally:
        workbook.close()

    while rows and all(value is None for value in rows[-1]):
        rows.pop()
    if not rows:
        return pd.DataFrame(), [make_issue("Error", "SA workbook", "empty_curve_sheet", "SA_Curves has no header row.")]

    headers = [_cell_text(value) for value in rows[0]]
    while headers and headers[-1] == "":
        headers.pop()
    issues: list[dict[str, object]] = []
    if not headers or headers[0] != "Duration_s":
        issues.append(make_issue("Error", "SA workbook", "invalid_curve_header", "SA_Curves must start with a Duration_s column."))
    blank_headers = [index + 1 for index, header in enumerate(headers[1:], start=1) if not header]
    if blank_headers:
        issues.append(make_issue("Error", "SA workbook", "blank_curve_header", f"SA_Curves contains blank SA_ID headers at column(s) {', '.join(map(str, blank_headers))}."))
    duplicate_headers = sorted({header for header in headers[1:] if header and headers[1:].count(header) > 1})
    if duplicate_headers:
        issues.append(make_issue("Error", "SA workbook", "duplicate_curve_header", f"SA_Curves SA_ID headers must be unique: {', '.join(duplicate_headers[:8])}."))

    body = [list(row[:len(headers)]) + [None] * max(0, len(headers) - len(row)) for row in rows[1:]]
    frame = pd.DataFrame(body, columns=headers if len(headers) else None)
    return frame, issues


def load_sa_workbook(source: str | bytes | bytearray, source_name: str) -> SAData:
    """Load SA curves and exact MM assignments; optional metadata sheets are ignored."""
    try:
        with pd.ExcelFile(_source_for_excel(source), engine="openpyxl") as workbook:
            sheet_names = set(workbook.sheet_names)
            if not set(SA_SHEETS).issubset(sheet_names):
                return _empty_sa_data(
                    "invalid",
                    source_name,
                    [make_issue("Error", "SA workbook", "missing_sheets", f"Required sheets: {', '.join(SA_SHEETS)}.")],
                )
            assignments = pd.read_excel(workbook, sheet_name="MM_Assignment")
        curves, header_issues = _read_wide_curves(source)
        return _validate_new_sa(curves, assignments, source_name, header_issues)
    except Exception as exc:
        return _empty_sa_data(
            "invalid",
            source_name,
            [make_issue("Error", "SA workbook", "read_error", f"Could not read the workbook: {exc}")],
        )


def _validate_new_sa(
    wide_curves: pd.DataFrame,
    assignments: pd.DataFrame,
    source_name: str,
    header_issues: list[dict[str, object]],
) -> SAData:
    issues = list(header_issues)
    structural_header_errors = {"invalid_curve_header", "blank_curve_header", "duplicate_curve_header"}
    if any(issue.get("Code") in structural_header_errors for issue in issues):
        return _empty_sa_data("invalid", source_name, issues)
    assignments = assignments.copy()
    assignments.columns = [str(column) for column in assignments.columns]
    missing_assignments = [column for column in SA_ASSIGNMENT_COLUMNS if column not in assignments.columns]
    curve_ids = [str(column) for column in wide_curves.columns[1:]] if len(wide_curves.columns) > 1 else []
    if "Duration_s" not in wide_curves.columns:
        missing_curve_header = True
        curve_ids = []
    else:
        missing_curve_header = False
    if missing_assignments or missing_curve_header or not curve_ids:
        parts = []
        if missing_assignments:
            parts.append(f"MM_Assignment: {', '.join(missing_assignments)}")
        if missing_curve_header or not curve_ids:
            parts.append("SA_Curves: Duration_s and at least one SA voltage column")
        issues.append(make_issue("Error", "SA workbook", "missing_sa_columns", "Required workbook fields are missing: " + "; ".join(parts) + "."))
        return _empty_sa_data("invalid", source_name, issues)

    duration = pd.to_numeric(wide_curves["Duration_s"], errors="coerce")
    invalid_duration = duration.isna() | ~np.isfinite(duration.to_numpy(dtype=float, na_value=np.nan))
    if invalid_duration.any():
        issues.append(make_issue("Error", "SA workbook", "invalid_curve_duration", f"{int(invalid_duration.sum())} SA_Curves row(s) have non-numeric or non-finite Duration_s."))
    valid_duration = duration.loc[~invalid_duration]
    if valid_duration.duplicated().any():
        issues.append(make_issue("Error", "SA workbook", "duplicate_sa_duration", f"{int(valid_duration.duplicated().sum())} duplicate Duration_s point(s) were found."))
    if not valid_duration.is_monotonic_increasing:
        issues.append(make_issue("Error", "SA workbook", "unordered_sa_duration", "SA_Curves Duration_s values must be strictly increasing in source order."))
    if valid_duration.lt(0).any():
        issues.append(make_issue("Error", "SA workbook", "negative_sa_duration", "SA_Curves Duration_s values cannot be negative."))

    curve_frames: list[pd.DataFrame] = []
    for sa_id in curve_ids:
        raw = wide_curves[sa_id]
        values = pd.to_numeric(raw, errors="coerce")
        invalid_text = raw.notna() & values.isna()
        nonfinite = values.notna() & ~np.isfinite(values.to_numpy(dtype=float, na_value=np.nan))
        nonpositive = values.notna() & values.le(0)
        if invalid_text.any() or nonfinite.any() or nonpositive.any():
            issues.append(make_issue("Error", "SA workbook", "invalid_curve_voltage", f"{int((invalid_text | nonfinite | nonpositive).sum())} supplied voltage value(s) for {sa_id} are non-numeric, non-finite or non-positive."))
        frame = pd.DataFrame(
            {
                "SA_ID": sa_id,
                "Duration_s": duration,
                "Voltage_kV_peak": values,
            }
        ).loc[~invalid_duration]
        if frame["Voltage_kV_peak"].notna().sum() == 0:
            issues.append(make_issue("Warning", "SA workbook", "empty_sa_curve", f"SA {sa_id} has no supplied voltage points and cannot be plotted."))
        curve_frames.append(frame)
    curves = pd.concat(curve_frames, ignore_index=True) if curve_frames else pd.DataFrame(columns=SA_CURVE_COLUMNS)

    assignments["MM_ID"] = assignments["MM_ID"].map(_cell_text)
    assignments["SA_ID"] = assignments["SA_ID"].map(_cell_text)
    source_ids = set(curve_ids)
    for sa_id in sorted(set(assignments.loc[assignments["SA_ID"].ne(""), "SA_ID"]) - source_ids):
        issues.append(make_issue("Error", "SA assignments", "unknown_assigned_sa", f"Assignment refers to SA_ID {sa_id}, which has no matching SA_Curves column."))
    for sa_id in sorted(source_ids - set(assignments.loc[assignments["SA_ID"].ne(""), "SA_ID"])):
        issues.append(make_issue("Warning", "SA curves", "unassigned_sa_curve", f"SA curve {sa_id} has no MM assignment and will not be offered for plotting."))

    blank_mms = assignments["MM_ID"].eq("")
    if blank_mms.any():
        issues.append(make_issue("Error", "SA assignments", "blank_mm_assignment", f"{int(blank_mms.sum())} assignment row(s) have blank MM_ID."))
    duplicate_mms = sorted(set(assignments.loc[assignments["MM_ID"].duplicated(keep=False), "MM_ID"]) - {""})
    if duplicate_mms:
        issues.append(make_issue("Error", "SA assignments", "duplicate_mm_assignment", f"MM_ID assignments must be unique: {', '.join(duplicate_mms[:8])}."))
    return SAData(
        kind="invalid" if any(issue.get("Severity") == "Error" for issue in issues) else "new",
        curves=curves.loc[:, list(SA_CURVE_COLUMNS)],
        assignments=assignments.loc[:, list(SA_ASSIGNMENT_COLUMNS)],
        source_name=source_name,
        issues=issues,
    )


def validate_sa_compatibility(sa: SAData | None, mm_blocks: pd.DataFrame | None) -> list[dict[str, object]]:
    if sa is None or sa.kind not in {"new", "invalid"} or mm_blocks is None or "Group" not in mm_blocks.columns:
        return []
    issues: list[dict[str, object]] = []
    known_mms = set(mm_blocks["Group"].dropna().astype(str))
    for _, assignment in sa.assignments.iterrows():
        mm_id, sa_id = str(assignment["MM_ID"]), str(assignment["SA_ID"])
        if not mm_id or not sa_id:
            continue
        if mm_id not in known_mms:
            issues.append(make_issue("Warning", "SA assignments", "unknown_assigned_mm", f"Assignment MM_ID {mm_id} is absent from MM_blocks."))
    return issues


def _wide_curve_frame(curves: pd.DataFrame) -> pd.DataFrame:
    if curves.empty or not {"SA_ID", "Duration_s", "Voltage_kV_peak"}.issubset(curves.columns):
        return pd.DataFrame(columns=["Duration_s"])
    wide = curves.pivot(index="Duration_s", columns="SA_ID", values="Voltage_kV_peak")
    preferred = [str(value) for value in curves["SA_ID"].dropna().drop_duplicates().tolist()]
    present = list(wide.columns)
    order = [column for column in preferred if column in present] + [column for column in present if column not in preferred]
    wide = wide.reindex(columns=order).reset_index()
    wide.columns.name = None
    return wide


def write_sa_workbook(curves: pd.DataFrame, assignments: pd.DataFrame) -> bytes:
    """Write the two required SA inputs: wide curves and exact MM assignments."""
    frames = {
        "SA_Curves": _wide_curve_frame(curves),
        "MM_Assignment": assignments.reindex(columns=SA_ASSIGNMENT_COLUMNS),
    }
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for sheet, frame in frames.items():
            frame.to_excel(writer, sheet_name=sheet, index=False)
    buffer.seek(0)
    workbook = load_workbook(buffer)
    comments = {
        "SA_Curves": {
            "Duration_s": "Source durations are elapsed time. The 0 s source point is retained as supplied, not treated as physical zero-duration capability.",
        },
        "MM_Assignment": {
            "MM_ID": "Exact MM_blocks.Group value. No mapping is inferred.",
            "SA_ID": "Exact matching SA_Curves column header. Blank means no SA curve is assigned.",
        },
    }
    for worksheet in workbook.worksheets:
        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = worksheet.dimensions
        worksheet.sheet_view.showGridLines = False
        for cell in worksheet[1]:
            cell.font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1F4E78")
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            if cell.value in comments.get(worksheet.title, {}):
                cell.comment = Comment(comments[worksheet.title][cell.value], "Voltage envelope dashboard")
        worksheet.row_dimensions[1].height = 32
        for row in worksheet.iter_rows(min_row=2):
            for cell in row:
                cell.font = Font(name="Arial", size=10, color="1F2937")
                if isinstance(cell.value, float):
                    cell.number_format = "0.000"
        for column_cells in worksheet.columns:
            letter = column_cells[0].column_letter
            max_len = max((len(str(cell.value)) for cell in column_cells if cell.value is not None), default=10)
            worksheet.column_dimensions[letter].width = min(max(max_len + 2, 12), 42)
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def create_blank_template() -> bytes:
    return write_sa_workbook(
        pd.DataFrame(columns=SA_CURVE_COLUMNS),
        pd.DataFrame(columns=SA_ASSIGNMENT_COLUMNS),
    )
