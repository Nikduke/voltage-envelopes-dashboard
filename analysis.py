"""Pure selection, aggregation and reference-comparison functions."""

from __future__ import annotations

import numpy as np
import pandas as pd

from limits import CHANGEOVER_S, ic_curve, reference_label


CHANNEL_COLUMNS = {
    "Max_all": "Max_all",
    "Max_A": "Max_A",
    "Max_B": "Max_B",
    "Max_C": "Max_C",
}


def available_cases(lg: pd.DataFrame | None, ll: pd.DataFrame | None) -> list[str]:
    frames = [frame for frame in (lg, ll) if frame is not None and "Case" in frame]
    return sorted(set().union(*(set(frame["Case"].dropna().astype(str)) for frame in frames))) if frames else []


def available_mms(lg: pd.DataFrame | None, ll: pd.DataFrame | None) -> list[str]:
    frames = [frame for frame in (lg, ll) if frame is not None and "MM_name_all" in frame]
    return sorted(set().union(*(set(frame["MM_name_all"].dropna().astype(str)) for frame in frames))) if frames else []


def nominal_voltages(mm_blocks: pd.DataFrame | None, mms: list[str] | None = None) -> list[float]:
    if mm_blocks is None or not {"Group", "Un"}.issubset(mm_blocks.columns):
        return []
    rows = mm_blocks
    if mms is not None:
        rows = rows.loc[rows["Group"].astype(str).isin(set(mms))]
    return sorted(pd.to_numeric(rows["Un"], errors="coerce").dropna().unique().astype(float).tolist())


def mms_at_voltage(mm_blocks: pd.DataFrame | None, mms: list[str], voltage: float | None) -> list[str]:
    if mm_blocks is None or "Group" not in mm_blocks or "Un" not in mm_blocks:
        return sorted(mms)
    rows = mm_blocks.loc[mm_blocks["Group"].astype(str).isin(set(mms))]
    if voltage is not None:
        rows = rows.loc[pd.to_numeric(rows["Un"], errors="coerce").sub(float(voltage)).abs().le(1e-6)]
    return sorted(rows["Group"].dropna().astype(str).unique().tolist())


def select_curves(
    frame: pd.DataFrame | None,
    cases: list[str],
    mms: list[str],
    index_range: tuple[float, float] | None,
    channel: str = "Max_all",
) -> pd.DataFrame:
    """Return selected rows, sorted by case/MM/index, preserving source columns."""
    if frame is None or frame.empty or not cases or not mms or channel not in CHANNEL_COLUMNS:
        return pd.DataFrame()
    required = {"Case", "MM_name_all", "Time (s)", CHANNEL_COLUMNS[channel]}
    if not required.issubset(frame.columns):
        return pd.DataFrame()
    selected = frame.loc[
        frame["Case"].astype(str).isin(set(cases))
        & frame["MM_name_all"].astype(str).isin(set(mms))
    ].copy()
    if index_range is not None:
        low, high = sorted(map(float, index_range))
        selected = selected.loc[pd.to_numeric(selected["Time (s)"], errors="coerce").between(low, high)]
    selected["Voltage_kV_peak"] = pd.to_numeric(selected[CHANNEL_COLUMNS[channel]], errors="coerce")
    selected["Case"] = selected["Case"].astype(str)
    selected["MM_name_all"] = selected["MM_name_all"].astype(str)
    selected = selected.rename(columns={"MM_name_all": "MM_ID", "Time (s)": "Index_s"})
    return selected.sort_values(["Case", "MM_ID", "Index_s"], kind="stable").reset_index(drop=True)


def summary_envelope(selected: pd.DataFrame, channel: str = "Max_all") -> pd.DataFrame:
    """Find the true per-index maximum and retain the winning source row."""
    if selected.empty or "Index_s" not in selected or "Voltage_kV_peak" not in selected:
        return pd.DataFrame()
    order = selected.sort_values(["Case", "MM_ID"], kind="stable").reset_index(drop=True)
    winner_positions = order.groupby("Index_s", sort=True)["Voltage_kV_peak"].idxmax()
    result = order.loc[winner_positions].sort_values("Index_s", kind="stable").reset_index(drop=True)
    # Run and Fault_type describe the governing Max_all source sample only.
    if channel != "Max_all":
        result = result.drop(columns=[column for column in ("Run", "Fault_type") if column in result], errors="ignore")
    return result


def crossing_summary(
    selected: pd.DataFrame,
    mm_blocks: pd.DataFrame | None,
    measurement: str,
    reference: str,
    channel: str = "Max_all",
    part: str = "all",
) -> pd.DataFrame:
    """Summarize one ranked-index segment; this is not a compliance result."""
    if part not in {"all", "SFO", "TOV"}:
        raise ValueError("part must be 'all', 'SFO', or 'TOV'")
    return _crossing_summaries(selected, mm_blocks, measurement, reference, channel, (part,))[part]


def crossing_summaries(
    selected: pd.DataFrame,
    mm_blocks: pd.DataFrame | None,
    measurement: str,
    reference: str,
    channel: str = "Max_all",
) -> dict[str, pd.DataFrame]:
    """Calculate full, SFO and TOV comparisons in one pass over the curves."""
    return _crossing_summaries(selected, mm_blocks, measurement, reference, channel, ("all", "SFO", "TOV"))


def _crossing_summaries(
    selected: pd.DataFrame,
    mm_blocks: pd.DataFrame | None,
    measurement: str,
    reference: str,
    channel: str,
    parts: tuple[str, ...],
) -> dict[str, pd.DataFrame]:
    columns = [
        "Measurement",
        "Case",
        "MM_ID",
        "Reference",
        "Ranked samples above reference",
        "Runs with exceedance",
        "Peak excess (kV)",
        "Over-limit area (kV·ranked-index s)",
        "Assessment",
    ]
    empty = {part: pd.DataFrame(columns=columns) for part in parts}
    if selected.empty or mm_blocks is None or "Group" not in mm_blocks:
        return empty
    limits = mm_blocks.drop_duplicates("Group").set_index("Group", drop=False)
    records: dict[str, list[dict[str, object]]] = {part: [] for part in parts}
    for (case, mm_id), group in selected.groupby(["Case", "MM_ID"], sort=True):
        if mm_id not in limits.index:
            continue
        row = limits.loc[mm_id]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        ordered = group.sort_values("Index_s", kind="stable")
        x = ordered["Index_s"].to_numpy(dtype=float)
        try:
            values = ic_curve(row, measurement, x, reference)
        except (KeyError, TypeError, ValueError):
            continue
        difference = ordered["Voltage_kV_peak"].to_numpy(dtype=float) - values
        finite = np.isfinite(x) & np.isfinite(difference)
        runs = ordered["Run"].to_numpy() if channel == "Max_all" and "Run" in ordered else None
        faults = ordered["Fault_type"].to_numpy() if runs is not None and "Fault_type" in ordered else None
        for part in parts:
            if part == "SFO":
                mask = x < CHANGEOVER_S
            elif part == "TOV":
                mask = x >= CHANGEOVER_S
            else:
                mask = np.ones(len(x), dtype=bool)
            part_x = x[mask]
            part_difference = difference[mask]
            part_finite = finite[mask]
            above = part_finite & (part_difference > 1e-9)
            widths = np.diff(part_x)
            left, right = part_difference[:-1], part_difference[1:]
            valid_pairs = (widths > 0) & part_finite[:-1] & part_finite[1:]
            both_positive = valid_pairs & (left > 0) & (right > 0)
            left_positive = valid_pairs & (left > 0) & (right <= 0)
            right_positive = valid_pairs & (left <= 0) & (right > 0)
            area_segments = np.zeros(len(widths), dtype=float)
            area_segments[both_positive] = 0.5 * (left[both_positive] + right[both_positive]) * widths[both_positive]
            area_segments[left_positive] = (
                0.5 * left[left_positive] * widths[left_positive]
                * left[left_positive] / (left[left_positive] - right[left_positive])
            )
            area_segments[right_positive] = (
                0.5 * right[right_positive] * widths[right_positive]
                * right[right_positive] / (right[right_positive] - left[right_positive])
            )
            area = float(area_segments.sum())
            run_labels: list[str] = []
            if runs is not None:
                seen_labels: set[str] = set()
                positions = np.flatnonzero(mask)[above]
                run_values = runs[positions]
                fault_values = faults[positions] if faults is not None else [""] * len(positions)
                for run, fault_value in zip(run_values, fault_values):
                    if pd.isna(run):
                        continue
                    run_text = str(run).strip()
                    try:
                        run_number = float(run)
                        if run_number.is_integer():
                            run_text = str(int(run_number))
                    except (TypeError, ValueError):
                        pass
                    fault = str(fault_value).strip()
                    run_label = f"{run_text} ({fault})" if fault and fault.casefold() != "nan" else run_text
                    if run_label not in seen_labels:
                        run_labels.append(run_label)
                        seen_labels.add(run_label)
            records[part].append(
                {
                    "Measurement": measurement,
                    "Case": case,
                    "MM_ID": mm_id,
                    "Reference": reference_label(reference),
                    "Ranked samples above reference": int(above.sum()),
                    "Runs with exceedance": ", ".join(dict.fromkeys(run_labels)),
                    "Peak excess (kV)": float(np.max(part_difference[part_finite])) if part_finite.any() else np.nan,
                    "Over-limit area (kV·ranked-index s)": float(area),
                    "Assessment": "Numerical ranked-index comparison only; not a chronological compliance assessment",
                }
            )
    return {part: pd.DataFrame(rows, columns=columns) for part, rows in records.items()}
