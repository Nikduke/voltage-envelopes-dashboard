"""Plotly builders for detailed and pointwise maximum envelope views."""

from __future__ import annotations

import math
from hashlib import sha256

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

from limits import CHANGEOVER_S, ic_curve
from sa_data import SAData, interpolate_sa


CASE_COLOURS = px.colors.qualitative.Safe
LINE_DASHES = ("solid", "dash", "dot", "dashdot", "longdash", "longdashdot")


def _mm_row_lookup(mm_blocks: pd.DataFrame | None) -> dict[str, pd.Series]:
    if mm_blocks is None or "Group" not in mm_blocks:
        return {}
    rows = mm_blocks.drop_duplicates("Group", keep="first")
    return {str(row["Group"]): row for _, row in rows.iterrows()}


def _sa_type_lookup(sa_data: SAData | None) -> dict[str, pd.Series]:
    if sa_data is None or sa_data.types.empty or "SA_ID" not in sa_data.types:
        return {}
    rows = sa_data.types.drop_duplicates("SA_ID", keep="first")
    return {str(row["SA_ID"]): row for _, row in rows.iterrows()}


def build_envelope_figure(
    data: pd.DataFrame,
    measurement: str,
    channel: str,
    mode: str,
    mm_blocks: pd.DataFrame | None,
    reference: str,
    show_ic: bool = True,
    sa_data: SAData | None = None,
    sa_by_mm: dict[str, list[str]] | None = None,
    include_unknown_sa_basis: bool = False,
    manual_y_range: tuple[float, float] | None = None,
    uirevision: str = "",
    reference_mms: list[str] | None = None,
    envelope_source: str = "",
    mm_source: str = "",
    sa_source: str = "",
) -> go.Figure:
    """Build one measurement figure. `data` is already filtered by the UI."""
    figure = go.Figure()
    if data.empty:
        figure.update_layout(
            title=f"{measurement} representative envelope — no selected rows",
            xaxis_title="Representative-envelope index (s; ranked index, not elapsed exposure time)",
            yaxis_title="Voltage (kV peak)",
        )
        return _style_figure(figure, measurement, 0, uirevision, manual_y_range)

    is_summary = mode == "summary"
    mm_lookup = _mm_row_lookup(mm_blocks)
    type_lookup = _sa_type_lookup(sa_data)
    all_x = np.sort(pd.to_numeric(data["Index_s"], errors="coerce").dropna().unique())
    if len(all_x) == 0:
        return _style_figure(figure, measurement, 0, uirevision, manual_y_range)

    if is_summary:
        custom = _customdata(data, channel, include_identity=True)
        figure.add_trace(
            go.Scatter(
                x=data["Index_s"],
                y=data["Voltage_kV_peak"],
                mode="lines",
                name="Maximum selected envelope",
                line={"color": "#17365D", "width": 2.7},
                customdata=custom,
                hovertemplate=_hover_template(channel, summary=True, source=envelope_source),
                legendgroup="summary",
            )
        )
    else:
        cases = sorted(data["Case"].astype(str).unique())
        mms = sorted(data["MM_ID"].astype(str).unique())
        for case in cases:
            for mm_index, mm_id in enumerate(mms):
                group = data.loc[data["Case"].astype(str).eq(case) & data["MM_ID"].astype(str).eq(mm_id)]
                if group.empty:
                    continue
                phase_identity = f"MM_name_{channel[-1]}" if channel in {"Max_A", "Max_B", "Max_C"} else None
                custom = _customdata(group, channel, phase_identity=phase_identity)
                colour_index = int(sha256(case.encode("utf-8")).hexdigest()[:8], 16) % len(CASE_COLOURS)
                colour = CASE_COLOURS[colour_index]
                figure.add_trace(
                    go.Scatter(
                        x=group["Index_s"],
                        y=group["Voltage_kV_peak"],
                        mode="lines",
                        name=f"{case} · {mm_id}",
                        line={"color": colour, "width": 1.8, "dash": LINE_DASHES[mm_index % len(LINE_DASHES)]},
                        customdata=custom,
                        hovertemplate=_hover_template(channel, phase_identity=phase_identity, source=envelope_source),
                        legendgroup=f"{case}|{mm_id}",
                    )
                )

    data_mms = sorted(data["MM_ID"].astype(str).unique()) if "MM_ID" in data else []
    selected_mms = sorted(reference_mms) if reference_mms is not None else data_mms
    if show_ic and mm_lookup:
        xs = np.unique(np.r_[all_x, CHANGEOVER_S])
        xs = xs[(xs >= all_x.min()) & (xs <= all_x.max())]
        for mm_id in selected_mms:
            row = mm_lookup.get(mm_id)
            if row is None:
                continue
            try:
                y = ic_curve(row, measurement, xs, reference)
            except (KeyError, TypeError, ValueError):
                continue
            un = row.get("Un", np.nan)
            figure.add_trace(
                go.Scatter(
                    x=xs,
                    y=y,
                    mode="lines",
                    name=f"{mm_id} · {reference} IC",
                    line={"color": "#222222", "width": 1.7, "dash": "dash" if reference == "Safety margin" else "dot"},
                    hovertemplate=(
                        f"MM: {mm_id}<br>IC {reference}<br>Index: %{{x:.4f}} s<br>"
                        f"Voltage: %{{y:.2f}} kV peak<br>Un: {un} kV<br>Input workbook: {mm_source}<br>"
                        "SDPF RMS → peak: ×√2; safety factor: 1.15<extra></extra>"
                    ),
                    legendgroup=f"ic|{mm_id}",
                )
            )

    if measurement == "LG" and sa_data is not None and sa_by_mm:
        curve_frame = sa_data.curves
        for mm_id, sa_ids in sa_by_mm.items():
            if mm_id not in selected_mms:
                continue
            for sa_id in sa_ids:
                type_row = type_lookup.get(str(sa_id))
                if type_row is None:
                    continue
                basis = str(type_row.get("Voltage_Basis", "Unknown")).strip()
                if basis.casefold() != "kv_peak" and not include_unknown_sa_basis:
                    continue
                if str(type_row.get("Curve_Type", "")).strip() != "TOV_withstand":
                    continue
                support_low = float(type_row.get("Valid_From_s", -np.inf))
                support_high = float(type_row.get("Valid_To_s", np.inf))
                y = interpolate_sa(curve_frame, str(sa_id), all_x, support_low, support_high)
                if not np.isfinite(y).any():
                    continue
                manufacturer = str(type_row.get("Manufacturer", "Unknown"))
                model = str(type_row.get("Model", "Unknown"))
                duty = str(type_row.get("Duty_Condition", "Unknown"))
                status = str(type_row.get("Verification_Status", "Unknown"))
                known = basis.casefold() == "kv_peak"
                installed = bool(
                    sa_data.kind == "new"
                    and (
                        sa_data.assignments["MM_ID"].astype(str).eq(mm_id)
                        & sa_data.assignments["SA_ID"].astype(str).eq(sa_id)
                        & sa_data.assignments["Installation_Status"].astype(str).eq("Installed")
                    ).any()
                )
                qualifier = "assigned" if installed else "Comparison only"
                legend_name = f"{mm_id} · {sa_id} SA TOV ({qualifier})" if known else f"{mm_id} · {sa_id} legacy comparison (basis unknown)"
                custom = np.column_stack((np.repeat(mm_id, len(all_x)), np.repeat(sa_id, len(all_x))))
                figure.add_trace(
                    go.Scatter(
                        x=all_x,
                        y=y,
                        mode="lines",
                        connectgaps=False,
                        name=legend_name,
                        line={"color": "#A33B20", "width": 1.8, "dash": "dashdot"},
                        customdata=custom,
                        hovertemplate=(
                            "MM: %{customdata[0]}<br>SA: %{customdata[1]}<br>"
                            "Index: %{x:.4f} s<br>Source value: %{y:.2f}<br>"
                            f"Model: {model}<br>Manufacturer: {manufacturer}<br>Duty: {duty}<br>"
                            f"Source document: {type_row.get('Source_Document', 'Unknown')}<br>"
                            f"SA workbook: {sa_source}<br>Valid range: {support_low:g}–{support_high:g} s<br>"
                            f"Installation comparison: {qualifier}<br>Verification: {status}<br>Voltage basis: {basis}<extra></extra>"
                        ),
                        legendgroup=f"sa|{mm_id}|{sa_id}",
                    )
                )

    title = f"{measurement} representative envelope — {channel}"
    if is_summary:
        title = f"Maximum selected {measurement} representative envelope"
    unknown_note = " · legacy SA basis unverified" if include_unknown_sa_basis and measurement == "LG" else ""
    figure.update_layout(
        title={"text": title + unknown_note, "x": 0.01, "xanchor": "left"},
        xaxis_title="Representative-envelope index (s; ranked index, not elapsed exposure time)",
        yaxis_title="Voltage (kV peak)" if not unknown_note else "Voltage (kV peak for envelope/IC; legacy SA value basis unknown)",
        hovermode="closest",
        legend={"orientation": "h", "x": 0, "y": -0.22, "xanchor": "left", "yanchor": "top", "font": {"size": 10}, "groupclick": "togglegroup"},
        uirevision=uirevision,
    )
    return _style_figure(figure, measurement, len(figure.data), uirevision, manual_y_range)


def _customdata(
    frame: pd.DataFrame,
    channel: str,
    phase_identity: str | None = None,
    include_identity: bool = False,
) -> np.ndarray:
    columns: list[str] = []
    if "Case" in frame:
        columns.append("Case")
    if "MM_ID" in frame:
        columns.append("MM_ID")
    if phase_identity and phase_identity in frame:
        columns.append(phase_identity)
    if channel == "Max_all":
        columns.extend(column for column in ("Run", "Fault_type") if column in frame)
    if include_identity:
        columns.extend(column for column in ("Run", "Fault_type") if column in frame and column not in columns)
    return frame[columns].astype(str).to_numpy() if columns else np.empty((len(frame), 0), dtype=str)


def _hover_template(channel: str, phase_identity: str | None = None, summary: bool = False, source: str = "") -> str:
    template = "Index: %{x:.4f} s<br>Voltage: %{y:.2f} kV peak"
    if summary:
        template = "Index: %{x:.4f} s<br>Selected maximum: %{y:.2f} kV peak"
    template += "<br>Case: %{customdata[0]}<br>MM: %{customdata[1]}" if not summary else "<br>Governing case: %{customdata[0]}<br>Governing MM: %{customdata[1]}"
    offset = 2
    if phase_identity:
        template += f"<br>{phase_identity}: %{{customdata[{offset}]}}"
        offset += 1
    if channel == "Max_all" and not summary:
        template += f"<br>Governing Run: %{{customdata[{offset}]}}<br>Fault type: %{{customdata[{offset + 1}]}}"
    elif channel == "Max_all" and summary:
        template += f"<br>Governing Run: %{{customdata[{offset}]}}<br>Fault type: %{{customdata[{offset + 1}]}}"
    template += f"<br>Source: {source or 'selected envelope CSV'}<extra></extra>"
    return template


def _style_figure(
    figure: go.Figure,
    measurement: str,
    trace_count: int,
    uirevision: str,
    manual_y_range: tuple[float, float] | None,
) -> go.Figure:
    legend_rows = max(1, math.ceil(trace_count / 5))
    legend_height = 26 * legend_rows
    figure.update_layout(
        template="plotly_white",
        width=1400,
        height=450 + max(0, legend_rows - 1) * 26,
        margin={"l": 72, "r": 28, "t": 66, "b": 88 + legend_height},
        font={"family": "Arial, sans-serif", "size": 12, "color": "#1F2937"},
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        uirevision=uirevision,
    )
    figure.update_xaxes(
        showgrid=True,
        gridcolor="#E5E7EB",
        zeroline=False,
        linecolor="#374151",
        tickfont={"color": "#1F2937"},
        title_font={"color": "#1F2937"},
    )
    figure.update_yaxes(
        showgrid=True,
        gridcolor="#E5E7EB",
        zeroline=False,
        linecolor="#374151",
        tickfont={"color": "#1F2937"},
        title_font={"color": "#1F2937"},
        range=list(manual_y_range) if manual_y_range else None,
    )
    return figure
