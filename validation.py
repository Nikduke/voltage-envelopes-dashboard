"""Input validation for voltage-envelope sources."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd


ENVELOPE_COLUMNS = (
    "Time (s)",
    "Max_A",
    "Max_B",
    "Max_C",
    "MM_name_A",
    "MM_name_B",
    "MM_name_C",
    "Max_all",
    "Case",
    "Run",
    "Fault_type",
    "MM_name_all",
)
NUMERIC_ENVELOPE_COLUMNS = ("Time (s)", "Max_A", "Max_B", "Max_C", "Max_all", "Run")
MM_COLUMNS = (
    "Group",
    "Un",
    "Um",
    "SDPF_LG",
    "SDPF_LL",
    "SIWL_LG",
    "SIWL_LL",
    "LIWL",
)


def make_issue(
    severity: str,
    area: str,
    code: str,
    message: str,
    identifier: str = "",
    blocking: bool = False,
) -> dict[str, object]:
    return {
        "Severity": severity,
        "Area": area,
        "Code": code,
        "Message": message,
        "Identifier": identifier,
        "Blocking": blocking,
    }


def validate_envelope(frame: pd.DataFrame, name: str) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    missing = [column for column in ENVELOPE_COLUMNS if column not in frame.columns]
    if missing:
        issues.append(
            make_issue(
                "Error",
                name,
                "missing_columns",
                f"Missing required columns: {', '.join(missing)}.",
                blocking=True,
            )
        )
        return issues

    if frame.empty:
        issues.append(make_issue("Error", name, "empty_file", "The CSV contains no rows.", blocking=True))
        return issues

    extras = [column for column in frame.columns if column not in ENVELOPE_COLUMNS]
    if extras:
        issues.append(
            make_issue(
                "Warning",
                name,
                "extra_columns",
                f"Extra columns are retained in memory but not used: {', '.join(map(str, extras[:8]))}.",
            )
        )

    for column in NUMERIC_ENVELOPE_COLUMNS:
        numeric = pd.to_numeric(frame[column], errors="coerce")
        invalid = numeric.isna() | ~np.isfinite(numeric.to_numpy(dtype=float, na_value=np.nan))
        if invalid.any():
            issues.append(
                make_issue(
                    "Error",
                    name,
                    "invalid_numeric",
                    f"{int(invalid.sum())} rows have blank, non-numeric or non-finite {column} values.",
                    blocking=True,
                )
            )

    for column in ("Case", "MM_name_all"):
        blank = frame[column].isna() | frame[column].astype(str).str.strip().eq("")
        if blank.any():
            issues.append(
                make_issue(
                    "Error",
                    name,
                    f"blank_{column.casefold().replace('_', '')}",
                    f"{int(blank.sum())} rows have a blank {column} identity.",
                    blocking=True,
                )
            )

    duplicate_count = int(frame.duplicated(["Case", "MM_name_all", "Time (s)"]).sum())
    if duplicate_count:
        issues.append(
            make_issue(
                "Error",
                name,
                "duplicate_curve_index",
                f"{duplicate_count} duplicate Case/MM/index rows were found.",
                blocking=True,
            )
        )

    sorted_index = frame.groupby(["Case", "MM_name_all"], sort=False)["Time (s)"].apply(
        lambda values: values.is_monotonic_increasing
    )
    if not sorted_index.all():
        issues.append(
            make_issue(
                "Warning",
                name,
                "unordered_index",
                f"{int((~sorted_index).sum())} curves have unsorted indices; plotted curves are sorted before rendering.",
            )
        )

    phase_mm_columns = [f"MM_name_{phase}" for phase in "ABC"]
    phase_mm_mismatch = pd.concat(
        [frame[column].astype(str).ne(frame["MM_name_all"].astype(str)) for column in phase_mm_columns],
        axis=1,
    ).any(axis=1)
    if phase_mm_mismatch.any():
        issues.append(
            make_issue(
                "Warning",
                name,
                "phase_mm_mismatch",
                f"{int(phase_mm_mismatch.sum())} rows have a phase-specific MM identity different from MM_name_all; both identities are shown in hover/export.",
            )
        )

    numeric = frame.loc[:, ["Max_A", "Max_B", "Max_C", "Max_all"]].apply(pd.to_numeric, errors="coerce")
    expected = numeric[["Max_A", "Max_B", "Max_C"]].max(axis=1)
    mismatch = (numeric["Max_all"] - expected).abs().gt(1e-8) & expected.notna()
    if mismatch.any():
        issues.append(
            make_issue(
                "Error",
                name,
                "max_all_mismatch",
                f"Max_all differs from the row-wise maximum of Max_A/Max_B/Max_C in {int(mismatch.sum())} rows.",
                blocking=True,
            )
        )
    return issues


def validate_mm_blocks(frame: pd.DataFrame | None) -> list[dict[str, object]]:
    if frame is None:
        return [make_issue("Warning", "MM workbook", "missing_mm_blocks", "IC references are unavailable because no MM_blocks sheet was loaded.")]

    issues: list[dict[str, object]] = []
    missing = [column for column in MM_COLUMNS if column not in frame.columns]
    if missing:
        return [
            make_issue(
                "Error",
                "MM workbook",
                "missing_mm_columns",
                f"MM_blocks is missing required columns: {', '.join(missing)}. IC references are disabled.",
            )
        ]
    duplicate_groups = frame.loc[frame["Group"].duplicated(keep=False), "Group"].dropna().astype(str).unique().tolist()
    if duplicate_groups:
        issues.append(
            make_issue(
                "Error",
                "MM workbook",
                "duplicate_mm_group",
                f"MM_blocks Group values must be unique; duplicates: {', '.join(duplicate_groups[:8])}.",
            )
        )
    required_numeric = [column for column in MM_COLUMNS if column != "Group"]
    for column in required_numeric:
        numeric = pd.to_numeric(frame[column], errors="coerce")
        invalid = numeric.isna() | ~np.isfinite(numeric.to_numpy(dtype=float, na_value=np.nan))
        if invalid.any():
            issues.append(
                make_issue(
                    "Error",
                    "MM workbook",
                    "invalid_mm_numeric",
                    f"{int(invalid.sum())} MM_blocks rows have invalid {column} values; those limits are unavailable.",
                )
            )
    if frame["Group"].isna().any() or frame["Group"].astype(str).str.strip().eq("").any():
        issues.append(make_issue("Error", "MM workbook", "blank_mm_group", "MM_blocks contains a blank Group value."))
    return issues


def validate_cross_sources(
    lg: pd.DataFrame | None,
    ll: pd.DataFrame | None,
    mm_blocks: pd.DataFrame | None,
    input_meta: dict[str, object],
) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    if lg is not None and ll is not None and {"Case", "MM_name_all"}.issubset(lg.columns) and {"Case", "MM_name_all"}.issubset(ll.columns):
        lg_keys = set(map(tuple, lg[["Case", "MM_name_all"]].drop_duplicates().itertuples(index=False, name=None)))
        ll_keys = set(map(tuple, ll[["Case", "MM_name_all"]].drop_duplicates().itertuples(index=False, name=None)))
        if lg_keys != ll_keys:
            missing_ll = sorted(lg_keys - ll_keys)
            missing_lg = sorted(ll_keys - lg_keys)
            examples = [f"LL missing {case}/{mm}" for case, mm in missing_ll[:3]] + [f"LG missing {case}/{mm}" for case, mm in missing_lg[:3]]
            issues.append(
                make_issue(
                    "Warning",
                    "LG/LL coverage",
                    "measurement_coverage_differs",
                    f"LG and LL Case/MM coverage differs ({len(missing_ll)} LG-only, {len(missing_lg)} LL-only combinations).",
                    "; ".join(examples),
                )
            )

    result_frames = [frame for frame in (lg, ll) if frame is not None and "MM_name_all" in frame.columns]
    result_mms = set().union(*(set(frame["MM_name_all"].dropna().astype(str)) for frame in result_frames)) if result_frames else set()
    if mm_blocks is not None and "Group" in mm_blocks.columns:
        configured = set(mm_blocks["Group"].dropna().astype(str))
        absent = sorted(configured - result_mms)
        unmatched = sorted(result_mms - configured)
        if absent:
            issues.append(
                make_issue(
                    "Note",
                    "MM coverage",
                    "configured_mm_without_results",
                    f"{len(absent)} configured MM points are absent from LG/LL results; they remain in the catalogue and no empty curves are created.",
                    ", ".join(absent[:10]),
                )
            )
        if unmatched:
            issues.append(
                make_issue(
                    "Warning",
                    "MM coverage",
                    "result_mm_without_limits",
                    f"{len(unmatched)} result MM points have no exact MM_blocks Group match; IC references are unavailable for those points.",
                    ", ".join(unmatched[:10]),
                )
            )

    if mm_blocks is not None and result_frames:
        all_cases = set().union(*(set(frame["Case"].dropna().astype(str)) for frame in result_frames))
        result_pairs = set().union(
            *(set(map(tuple, frame[["Case", "MM_name_all"]].drop_duplicates().itertuples(index=False, name=None))) for frame in result_frames)
        )
        result_mm_list = sorted(result_mms)
        absent_pairs = sorted((case, mm) for case in all_cases for mm in result_mm_list if (case, mm) not in result_pairs)
        if absent_pairs:
            examples = ", ".join(f"{case}/{mm}" for case, mm in absent_pairs[:10])
            issues.append(
                make_issue(
                    "Note",
                    "Case/MM coverage",
                    "missing_case_mm_combinations",
                    f"{len(absent_pairs)} case/MM combinations have no source curve. They are excluded, not filled with zero.",
                    examples,
                )
            )

    if lg is not None and ll is not None and mm_blocks is not None and "Time (s)" in lg and "Time (s)" in ll:
        configured_duration = input_meta.get("final duration")
        try:
            duration = float(configured_duration)
            index_max = max(float(lg["Time (s)"].max()), float(ll["Time (s)"].max()))
        except (TypeError, ValueError):
            duration = float("nan")
            index_max = float("nan")
        if np.isfinite(duration) and np.isfinite(index_max) and index_max > duration:
            issues.append(
                make_issue(
                    "Note",
                    "Index semantics",
                    "index_beyond_final_duration",
                    f"Input_Data Final duration is {duration:g} s while the representative-envelope index reaches {index_max:g} s. These values describe different quantities and are not treated as a duration error.",
                )
            )

    if mm_blocks is not None and "SDPF_LG" in mm_blocks.columns and "SDPF_LL" in mm_blocks.columns:
        issues.append(
            make_issue(
                "Warning",
                "IC basis",
                "sdpf_unit_assumption",
                "MM_blocks does not declare SDPF units. The display uses the project convention that SDPF is kV RMS and converts it to kV peak once with sqrt(2).",
            )
        )
    return issues


def validation_frame(issues: Iterable[dict[str, object]]) -> pd.DataFrame:
    columns = ["Severity", "Area", "Code", "Message", "Identifier", "Blocking"]
    return pd.DataFrame(list(issues), columns=columns)
