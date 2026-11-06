"""Fixed-size report chart export helpers."""

from __future__ import annotations

from collections.abc import Mapping
from io import BytesIO
from math import ceil
from zipfile import ZIP_STORED, ZipFile

import plotly.graph_objects as go

from plots import _legend_column_layout


REPORT_PNG_WIDTH = 1800
REPORT_PNG_HEIGHT = 1050
REPORT_LEGEND_ROW_HEIGHT = 36
REPORT_LEGEND_MAX_ROWS = 9
REPORT_LEGEND_TOP_OFFSET = 120
REPORT_LEGEND_BOTTOM_PADDING = 20
REPORT_MARGIN_LEFT = 110
REPORT_MARGIN_RIGHT = 40
REPORT_MARGIN_TOP = 75


def prepare_report_figure(figure: go.Figure, include_curve_legend: bool) -> go.Figure:
    """Clone an app figure and fit it to the fixed report layout."""
    report = go.Figure(figure.to_plotly_json())
    for trace in report.data:
        if (trace.legendrank or 0) < 1000 and not include_curve_legend:
            trace.showlegend = False
        elif trace.showlegend is not False:
            # App figures split envelope and limit labels into two legends.
            # Report exports use one legend so it can be placed reliably below
            # the chart at the fixed page size.
            trace.legend = "legend"

    curve_labels = [
        trace.name
        for trace in report.data
        if trace.showlegend is not False and (trace.legendrank or 0) < 1000
    ]
    limit_labels = [
        trace.name
        for trace in report.data
        if trace.showlegend is not False and (trace.legendrank or 0) >= 1000
    ]
    labels = curve_labels + limit_labels
    available_width = REPORT_PNG_WIDTH - REPORT_MARGIN_LEFT - REPORT_MARGIN_RIGHT
    columns, entry_width = _legend_column_layout(labels, available_width)
    legend_rows = ceil(len(labels) / columns) if labels else 0
    legend_height = (
        min(
            REPORT_LEGEND_ROW_HEIGHT * REPORT_LEGEND_MAX_ROWS,
            max(REPORT_LEGEND_ROW_HEIGHT, legend_rows * REPORT_LEGEND_ROW_HEIGHT),
        )
        if labels
        else 0
    )
    bottom_margin = (
        REPORT_LEGEND_TOP_OFFSET + legend_height + REPORT_LEGEND_BOTTOM_PADDING
        if labels
        else 60
    )
    plot_area_height = REPORT_PNG_HEIGHT - REPORT_MARGIN_TOP - bottom_margin
    legend = (
        {
            "orientation": "h",
            "x": 0,
            "xanchor": "left",
            "y": -REPORT_LEGEND_TOP_OFFSET / plot_area_height,
            "yanchor": "top",
            "font": {"size": 20},
            "groupclick": "togglegroup",
            "tracegroupgap": 0,
            "entrywidth": entry_width,
            "entrywidthmode": "pixels",
            "maxheight": max(REPORT_LEGEND_ROW_HEIGHT, legend_height),
        }
        if labels
        else None
    )
    report.update_layout(
        width=REPORT_PNG_WIDTH,
        height=REPORT_PNG_HEIGHT,
        margin={
            "l": REPORT_MARGIN_LEFT,
            "r": REPORT_MARGIN_RIGHT,
            "t": REPORT_MARGIN_TOP,
            "b": bottom_margin,
        },
        font={"family": "Arial, sans-serif", "size": 26, "color": "#1F2937"},
        title_font={"size": 30},
        legend=legend,
        legend2=None,
    )
    report.update_xaxes(tickfont={"size": 22}, title_font={"size": 24})
    report.update_yaxes(tickfont={"size": 22}, title_font={"size": 24})
    return report


def export_report_charts_zip(
    figures: Mapping[str, go.Figure],
    *,
    include_curve_legend: bool,
    filename_prefix: str,
) -> bytes:
    """Export fixed-size LG and LL PNGs in one download archive."""
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_STORED) as archive:
        for measurement in ("LG", "LL"):
            report = prepare_report_figure(figures[measurement], include_curve_legend)
            image_bytes = report.to_image(
                format="png",
                width=REPORT_PNG_WIDTH,
                height=REPORT_PNG_HEIGHT,
            )
            archive.writestr(f"{filename_prefix}_{measurement}.png", image_bytes)
    return output.getvalue()
