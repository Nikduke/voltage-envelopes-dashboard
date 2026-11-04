"""Pure selection, aggregation and reference-comparison functions."""

from __future__ import annotations

import numpy as np
import pandas as pd

from limits import ic_curve, reference_label


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


def curve_summary(selected: pd.DataFrame, channel: str = "Max_all") -> pd.DataFrame:
    """Summarize selected curves, retaining only established Max_all provenance."""
    columns = ["Case", "MM_ID", "Samples", "Peak (kV peak)", "Peak index (s)"]
    if channel == "Max_all":
        columns.extend(["Peak Run", "Peak Fault_type"])
    if selected.empty:
        return pd.DataFrame(columns=columns)
    records: list[dict[str, object]] = []
    for (case, mm_id), group in selected.groupby(["Case", "MM_ID"], sort=True):
        peak = group.loc[group["Voltage_kV_peak"].idxmax()]
        record = {
            "Case": case,
            "MM_ID": mm_id,
            "Samples": len(group),
            "Peak (kV peak)": float(peak["Voltage_kV_peak"]),
            "Peak index (s)": float(peak["Index_s"]),
        }
        if channel == "Max_all":
            for column in ("Run", "Fault_type"):
                if column in peak and pd.notna(peak[column]):
                    record[f"Peak {column}"] = peak[column]
        records.append(record)
    return pd.DataFrame(records).reindex(columns=columns)


def crossing_summary(
    selected: pd.DataFrame,
    mm_blocks: pd.DataFrame | None,
    measurement: str,
    reference: str,
    channel: str = "Max_all",
) -> pd.DataFrame:
    """Count ranked samples above a reference; this is not a compliance result."""
    columns = ["Measurement", "Case", "MM_ID", "Reference", "Ranked samples above reference", "Peak excess (kV)", "Assessment"]
    if selected.empty or mm_blocks is None or "Group" not in mm_blocks:
        return pd.DataFrame(columns=columns)
    limits = mm_blocks.drop_duplicates("Group").set_index("Group", drop=False)
    records: list[dict[str, object]] = []
    for (case, mm_id), group in selected.groupby(["Case", "MM_ID"], sort=True):
        if mm_id not in limits.index:
            continue
        row = limits.loc[mm_id]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        try:
            values = ic_curve(row, measurement, group["Index_s"].to_numpy(dtype=float), reference)
        except (KeyError, TypeError, ValueError):
            continue
        difference = group["Voltage_kV_peak"].to_numpy(dtype=float) - values
        above = difference > 1e-9
        records.append(
            {
                "Measurement": measurement,
                "Case": case,
                "MM_ID": mm_id,
                "Reference": reference_label(reference),
                "Ranked samples above reference": int(above.sum()),
                "Peak excess (kV)": float(np.max(difference)) if len(difference) else np.nan,
                "Assessment": "Numerical ranked-index comparison only; not a chronological compliance assessment",
            }
        )
    return pd.DataFrame(records, columns=columns)


def closest_reference_crossing(
    envelope: pd.DataFrame,
    mm_blocks: pd.DataFrame | None,
    measurement: str,
    reference: str,
) -> dict[str, object] | None:
    """Return the nearest sampled sign change with its source identity."""
    if envelope.empty or mm_blocks is None or "Group" not in mm_blocks:
        return None
    limits = mm_blocks.drop_duplicates("Group").set_index("Group", drop=False)
    ordered = envelope.sort_values("Index_s", kind="stable").copy().reset_index(drop=True)
    references = np.full(len(ordered), np.nan, dtype=float)
    for mm_id, positions in ordered.groupby("MM_ID", sort=False).indices.items():
        if mm_id not in limits.index:
            continue
        row = limits.loc[mm_id]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        try:
            limit = ic_curve(row, measurement, ordered.iloc[positions]["Index_s"].to_numpy(dtype=float), reference)
        except (KeyError, TypeError, ValueError):
            continue
        references[positions] = limit
    if not np.isfinite(references).any():
        return None
    compared = ordered.copy()
    compared["Reference_kV_peak"] = references
    compared["Difference_kV"] = compared["Voltage_kV_peak"].to_numpy(dtype=float) - references
    difference = compared["Difference_kV"]
    crossed = difference.abs().le(1e-9)
    crossed |= difference.shift().mul(difference).lt(0) & compared["Reference_kV_peak"].notna() & compared["Reference_kV_peak"].shift().notna()
    candidates = compared.loc[crossed]
    if candidates.empty:
        return None
    candidate = candidates.iloc[(candidates["Difference_kV"].abs()).argmin()]
    result = {
        "Index_s": float(candidate["Index_s"]),
        "Envelope_kV_peak": float(candidate["Voltage_kV_peak"]),
        "Reference_kV_peak": float(candidate["Reference_kV_peak"]),
        "Case": candidate.get("Case", ""),
        "MM_ID": candidate.get("MM_ID", ""),
    }
    for column in ("Run", "Fault_type"):
        if column in candidate.index and pd.notna(candidate[column]):
            result[column] = candidate[column]
    result["Assessment"] = "Numerical ranked-index crossing only; not a duration violation"
    return result
