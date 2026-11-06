"""Plotly builders for detailed and pointwise maximum envelope views."""

from __future__ import annotations

import math
from hashlib import sha256

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

from limits import CHANGEOVER_S, ic_curve
from sa_data import SAData


CASE_COLOURS = px.colors.qualitative.Safe
LINE_DASHES = ("solid", "dash", "dot", "dashdot", "longdash", "longdashdot")
LEGEND_REFERENCE_WIDTH = 1400
LEGEND_HORIZONTAL_MARGINS = 100
LEGEND_AVAILABLE_WIDTH = LEGEND_REFERENCE_WIDTH - LEGEND_HORIZONTAL_MARGINS
LEGEND_MAX_COLUMNS = 3
LEGEND_ITEM_GAP = 50
LEGEND_ROW_HEIGHT = 20
LEGEND_MAX_VISIBLE_ROWS = 9
LEGEND_MAX_HEIGHT = LEGEND_ROW_HEIGHT * LEGEND_MAX_VISIBLE_ROWS
LEGEND_LIMIT_MAX_HEIGHT = 80
LEGEND_TOP_OFFSET = 78
SUMMARY_LEGEND_TOP_OFFSET = 48
LEGEND_GAP = 18
LEGEND_BOTTOM_PADDING = 24


def _mm_row_lookup(mm_blocks: pd.DataFrame | None) -> dict[str, pd.Series]:
    if mm_blocks is None or "Group" not in mm_blocks:
        return {}
    rows = mm_blocks.drop_duplicates("Group", keep="first")
    return {str(row["Group"]): row for _, row in rows.iterrows()}


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
    uirevision: str = "",
    reference_mms: list[str] | None = None,
    envelope_source: str = "",
    mm_source: str = "",
    highlight_curve: tuple[str, str] | None = None,
    plot_container_width: int | None = None,
    show_sa: bool = True,
    x_range: tuple[float, float] | None = None,
) -> go.Figure:
    """Build one measurement figure. `data` is already filtered by the UI."""
    figure = go.Figure()
    is_summary = mode == "summary"
    if x_range is not None:
        x_range = tuple(sorted(map(float, x_range)))
    if data.empty:
        figure.update_layout(
            title=f"{measurement} representative envelope — no selected rows",
            xaxis_title="Envelope index (s)",
            yaxis_title="Voltage (kV peak)",
        )
        return _style_figure(figure, measurement, uirevision, plot_container_width, is_summary, x_range)

    mm_lookup = _mm_row_lookup(mm_blocks)
    all_x = np.sort(pd.to_numeric(data["Index_s"], errors="coerce").dropna().unique())
    if len(all_x) == 0:
        return _style_figure(figure, measurement, uirevision, plot_container_width, is_summary, x_range)

    if is_summary:
        custom = _customdata(data, channel, include_identity=True)
        figure.add_trace(
            go.Scatter(
                x=data["Index_s"],
                y=data["Voltage_kV_peak"],
                mode="lines",
                name="Maximum envelope",
                line={"color": "#17365D", "width": 2.7},
                legend="legend",
                showlegend=True,
                legendrank=10,
                customdata=custom,
                hovertemplate=_hover_template(channel, summary=True, source=envelope_source),
                legendgroup="summary",
            )
        )
    else:
        cases = data["Case"].astype(str)
        mms = data["MM_ID"].astype(str)
        case_values = sorted(cases.unique())
        mm_values = sorted(mms.unique())
        case_colours = {
            case: CASE_COLOURS[int(sha256(case.encode("utf-8")).hexdigest()[:8], 16) % len(CASE_COLOURS)]
            for case in case_values
        }
        mm_indices = {mm_id: index for index, mm_id in enumerate(mm_values)}
        phase_identity = f"MM_name_{channel[-1]}" if channel in {"Max_A", "Max_B", "Max_C"} else None
        curve_customdata = _curve_customdata(data, channel, phase_identity=phase_identity)
        groups = data.groupby([cases, mms], sort=True)
        for (case, mm_id), positions in groups.indices.items():
            group = data.iloc[positions]
            custom = curve_customdata[positions]
            is_highlighted = highlight_curve == (case, mm_id)
            figure.add_trace(
                go.Scatter(
                    x=group["Index_s"],
                    y=group["Voltage_kV_peak"],
                    mode="lines",
                    name=f"{case} · {mm_id}",
                    line={
                        "color": case_colours[case],
                        "width": 3.6 if is_highlighted else (1.8 if highlight_curve is None else 1.1),
                        "dash": LINE_DASHES[mm_indices[mm_id] % len(LINE_DASHES)],
                    },
                    opacity=1 if is_highlighted or highlight_curve is None else 0.2,
                    legendrank=10,
                    customdata=custom,
                    meta=[case, mm_id],
                    hovertemplate=_curve_hover_template(
                        channel, phase_identity, source=envelope_source
                    ),
                    legendgroup=f"{case}|{mm_id}",
                )
            )

    data_mms = sorted(data["MM_ID"].astype(str).unique()) if "MM_ID" in data else []
    selected_mms = sorted(reference_mms) if reference_mms is not None else data_mms
    if show_ic and mm_lookup:
        ic_colour = "#C2413B" if reference == "Withstand" else "#D28B00"
        ic_legend_added = False
        if is_summary:
            # The summary takes the IC reference from the MM that governs each
            # envelope point, so different MMs retain their independent limits.
            governing_mms = data.set_index("Index_s")["MM_ID"].astype(str)
            y = np.full(len(all_x), np.nan, dtype=float)
            for mm_id in governing_mms.unique():
                row = mm_lookup.get(mm_id)
                positions = np.flatnonzero(governing_mms.reindex(all_x).to_numpy() == mm_id)
                if row is None or not len(positions):
                    continue
                try:
                    y[positions] = ic_curve(row, measurement, all_x[positions], reference)
                except (KeyError, TypeError, ValueError):
                    continue
            figure.add_trace(
                go.Scatter(
                    x=all_x,
                    y=y,
                    mode="lines",
                    name=f"IC {reference}",
                    legend="legend2",
                    line={"color": ic_colour, "width": 1.8, "dash": "dash" if reference == "Safety margin" else "dot"},
                    legendrank=1000,
                    hovertemplate=(
                        f"IC {reference}<br>Index: %{{x:.4f}} s<br>Voltage: %{{y:.2f}} kV peak<br>"
                        "Reference follows the MM governing the envelope at this index.<br>"
                        f"Input workbook: {mm_source}<br>SDPF RMS → peak: ×√2; safety factor: 1.15<extra></extra>"
                    ),
                    legendgroup="ic|summary",
                )
            )
        else:
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
                        name=f"IC {reference}",
                        legend="legend2",
                        line={"color": ic_colour, "width": 1.8, "dash": "dash" if reference == "Safety margin" else "dot"},
                        showlegend=not ic_legend_added,
                        legendrank=1000,
                        hovertemplate=(
                            f"MM: {mm_id}<br>IC {reference}<br>Index: %{{x:.4f}} s<br>"
                            f"Voltage: %{{y:.2f}} kV peak<br>Un: {un} kV<br>Input workbook: {mm_source}<br>"
                            "SDPF RMS → peak: ×√2; safety factor: 1.15<extra></extra>"
                        ),
                        legendgroup=f"ic|{mm_id}",
                    )
                )
                ic_legend_added = True

    if show_sa and measurement == "LG" and sa_data is not None and sa_data.kind == "new" and sa_by_mm:
        curve_frame = sa_data.curves
        curves_to_plot: set[str] = set()
        for mm_id, sa_ids in sa_by_mm.items():
            if mm_id not in selected_mms:
                continue
            for sa_id in sa_ids:
                curves_to_plot.add(str(sa_id))
        for sa_id in sorted(curves_to_plot):
            points = curve_frame.loc[curve_frame["SA_ID"].astype(str).eq(sa_id)].copy()
            if points.empty or not points["Voltage_kV_peak"].notna().any():
                continue
            points = points.sort_values("Duration_s", kind="stable")
            figure.add_trace(
                go.Scatter(
                    x=points["Duration_s"],
                    y=points["Voltage_kV_peak"],
                    mode="lines",
                    connectgaps=False,
                    name=sa_id,
                    legend="legend2",
                    line={"color": "#A33B20", "width": 1.8, "dash": "dashdot"},
                    showlegend=True,
                    legendrank=2000,
                    hovertemplate=(
                        f"SA ID: {sa_id}<br>Source duration: %{{x:.3f}} s<br>"
                        "Source voltage: %{y:.2f} kV peak<extra></extra>"
                    ),
                    legendgroup=f"sa|{sa_id}",
                )
            )

    title = f"{measurement} representative envelope — {channel}"
    if is_summary:
        title = f"Maximum selected {measurement} representative envelope"
    figure.update_layout(
        title={"text": title, "x": 0.01, "xanchor": "left"},
        xaxis_title="Envelope index (s)",
        yaxis_title="Voltage (kV peak)",
        hovermode="closest",
        uirevision=uirevision,
    )
    return _style_figure(figure, measurement, uirevision, plot_container_width, is_summary, x_range)


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
    return _string_customdata(frame, columns)


def _curve_customdata(
    frame: pd.DataFrame,
    channel: str,
    phase_identity: str | None = None,
) -> np.ndarray:
    """Keep only point-varying hover fields; case and MM are trace metadata."""
    columns = [phase_identity] if phase_identity and phase_identity in frame else []
    if channel == "Max_all":
        columns.extend(column for column in ("Run", "Fault_type") if column in frame)
    return _string_customdata(frame, columns)


def _string_customdata(frame: pd.DataFrame, columns: list[str]) -> np.ndarray:
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
    if channel == "Max_all":
        template += f"<br>Governing Run: %{{customdata[{offset}]}}<br>Fault type: %{{customdata[{offset + 1}]}}"
    template += f"<br>Source: {source or 'selected envelope CSV'}<extra></extra>"
    return template


def _curve_hover_template(channel: str, phase_identity: str | None = None, source: str = "") -> str:
    template = (
        "Index: %{x:.4f} s<br>Voltage: %{y:.2f} kV peak"
        "<br>Case: %{meta[0]}<br>MM: %{meta[1]}"
    )
    offset = 0
    if phase_identity:
        template += f"<br>{phase_identity}: %{{customdata[{offset}]}}"
        offset += 1
    if channel == "Max_all":
        template += f"<br>Governing Run: %{{customdata[{offset}]}}<br>Fault type: %{{customdata[{offset + 1}]}}"
    template += f"<br>Source: {source or 'selected envelope CSV'}<extra></extra>"
    return template


def _legend_column_layout(
    labels: list[str], available_width: int = LEGEND_AVAILABLE_WIDTH
) -> tuple[int, float]:
    if not labels:
        return 1, max(0.0, available_width - LEGEND_ITEM_GAP)
    longest = max(map(len, labels))
    item_width = max(180.0, 45.0 + 7.0 * longest)
    columns = max(1, min(LEGEND_MAX_COLUMNS, len(labels), int(available_width // item_width)))
    entry_width = max(0.0, available_width / columns - LEGEND_ITEM_GAP)
    return columns, entry_width


def _style_figure(
    figure: go.Figure,
    measurement: str,
    uirevision: str,
    plot_container_width: int | None = None,
    is_summary: bool = False,
    x_range: tuple[float, float] | None = None,
) -> go.Figure:
    curve_labels = [trace.name for trace in figure.data if trace.showlegend is not False and trace.legendrank < 1000]
    limit_labels = [trace.name for trace in figure.data if trace.showlegend is not False and trace.legendrank >= 1000]
    all_labels = curve_labels + limit_labels
    container_width = plot_container_width or LEGEND_REFERENCE_WIDTH
    available_width = max(1, container_width - LEGEND_HORIZONTAL_MARGINS)
    columns, entry_width = _legend_column_layout(all_labels, available_width)
    curve_rows = math.ceil(len(curve_labels) / columns) if curve_labels else 0
    limit_rows = math.ceil(len(limit_labels) / columns) if limit_labels else 0
    plot_area_height = 460
    legend_top_offset = SUMMARY_LEGEND_TOP_OFFSET if is_summary else LEGEND_TOP_OFFSET
    curve_legend_height = min(LEGEND_MAX_HEIGHT, max(40, curve_rows * LEGEND_ROW_HEIGHT)) if curve_labels else 0
    limit_legend_height = min(LEGEND_LIMIT_MAX_HEIGHT, max(40, limit_rows * LEGEND_ROW_HEIGHT)) if limit_labels else 0
    bottom_margin = (
        legend_top_offset
        + curve_legend_height
        + (LEGEND_GAP + limit_legend_height if limit_labels else 0)
        + LEGEND_BOTTOM_PADDING
    )
    height = max(620, 66 + plot_area_height + bottom_margin)
    legend_style = {
        "orientation": "h",
        "x": 0,
        "xanchor": "left",
        "yanchor": "top",
        "font": {"size": 12},
        "groupclick": "togglegroup",
        "tracegroupgap": 0,
        "entrywidth": entry_width,
        "entrywidthmode": "pixels",
        "maxheight": max(40, curve_legend_height),
    }
    legend = {**legend_style, "y": -legend_top_offset / plot_area_height}
    legend2 = (
        {
            **legend_style,
            "maxheight": limit_legend_height,
            "y": -(legend_top_offset + curve_legend_height + LEGEND_GAP) / plot_area_height,
        }
        if limit_labels
        else None
    )
    figure.update_layout(
        template="plotly_white",
        width=container_width,
        height=height,
        margin={"l": 72, "r": 28, "t": 66, "b": bottom_margin},
        font={"family": "Arial, sans-serif", "size": 12, "color": "#1F2937"},
        paper_bgcolor="#FFFFFF",
        plot_bgcolor="#FFFFFF",
        legend=legend,
        legend2=legend2,
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
    if x_range is not None:
        figure.update_xaxes(uirevision=f"{uirevision}|xrange:{x_range[0]:.12g}:{x_range[1]:.12g}")
    if x_range is not None and x_range[0] < x_range[1]:
        figure.update_xaxes(range=list(x_range), autorange=False)
    figure.update_yaxes(
        showgrid=True,
        gridcolor="#E5E7EB",
        zeroline=False,
        linecolor="#374151",
        tickfont={"color": "#1F2937"},
        title_font={"color": "#1F2937"},
    )
    return figure
