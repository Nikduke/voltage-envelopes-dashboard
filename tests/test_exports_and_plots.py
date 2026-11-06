from io import BytesIO
from pathlib import Path
from struct import unpack
from zipfile import ZipFile

import pandas as pd
import pytest
from openpyxl import load_workbook

from exports import export_xlsx_bytes
from chart_exports import (
    REPORT_LEGEND_BOTTOM_PADDING,
    REPORT_LEGEND_TOP_OFFSET,
    REPORT_PNG_HEIGHT,
    REPORT_PNG_WIDTH,
    export_report_charts_zip,
    prepare_report_figure,
)
from plots import build_envelope_figure
from sa_data import SAData, load_sa_workbook
from data_loader import discover_sources


def _curve_frame(trace_count: int) -> pd.DataFrame:
    rows = []
    for index in range(trace_count):
        for sample, x in enumerate((0.0, 0.02, 0.1)):
            rows.append({"Case": f"Case {index:03d}", "MM_ID": f"MM_{index:03d}", "Index_s": x, "Voltage_kV_peak": 500 + index + sample, "Run": 1, "Fault_type": "synthetic"})
    return pd.DataFrame(rows)


def test_xlsx_export_has_selected_values_and_provenance_metadata():
    selected = _curve_frame(1).assign(Measurement="LG")
    reference = pd.DataFrame([{"MM_ID": "MM_000", "Ranked samples above reference": 0}])
    workbook_bytes = export_xlsx_bytes(
        selected,
        pd.DataFrame([{"Case": "Case 000", "MM_ID": "MM_000", "Peak (kV peak)": 502}]),
        reference,
        pd.DataFrame([{"Severity": "Note", "Code": "sample"}]),
        {"Cases": ["Case 000"], "Units": "kV peak", "IC factor": 1.15},
    )
    workbook = load_workbook(BytesIO(workbook_bytes), read_only=True, data_only=True)
    try:
        assert set(workbook.sheetnames) == {"Selected data", "Limit exceedances", "Reference comparison", "Validation", "Metadata"}
        summary_rows = list(workbook["Limit exceedances"].values)
        assert summary_rows[1][0:3] == ("Case 000", "MM_000", 502)
        metadata_rows = list(workbook["Metadata"].values)
        metadata = {row[0]: row[1] for row in metadata_rows[1:]}
        assert metadata["Units"] == "kV peak"
        assert metadata["IC factor"] == "1.15"
        assert metadata["Assessment status"] == "Reference comparison on envelope index"
    finally:
        workbook.close()


def test_xlsx_export_keeps_sheet_formatting():
    workbook_bytes = export_xlsx_bytes(
        _curve_frame(1),
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        {},
    )
    workbook = load_workbook(BytesIO(workbook_bytes), read_only=False, data_only=False)
    try:
        worksheet = workbook["Selected data"]
        assert worksheet.freeze_panes == "A2"
        assert worksheet.auto_filter.ref == worksheet.dimensions
        assert worksheet.sheet_view.showGridLines is False
        assert worksheet["A1"].font.bold is True
        assert worksheet["A1"].fill.fgColor.rgb.endswith("1F4E78")
        assert worksheet["A1"].alignment.wrap_text is True
        assert worksheet.row_dimensions[1].height == 28
        assert worksheet.column_dimensions["A"].width >= 12
    finally:
        workbook.close()


def test_xlsx_export_includes_all_sa_source_points_and_blank_gaps():
    curves = pd.DataFrame({
        "SA_ID": ["A", "A", "A"],
        "Duration_s": [0.0, 0.1, 0.2],
        "Voltage_kV_peak": [379.2, float("nan"), 329.5],
    })
    output = export_xlsx_bytes(
        pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), {},
        sa_curves=curves,
        sa_assignments=pd.DataFrame([{"MM_ID": "MM_A", "SA_ID": "A"}]),
    )
    workbook = load_workbook(BytesIO(output), read_only=True, data_only=True)
    try:
        assert {"SA source points", "SA assignments"}.issubset(workbook.sheetnames)
        assert "SA types" not in workbook.sheetnames
        points = list(workbook["SA source points"].values)
        assert len(points) == 4
        assert points[1] == ("A", 0.0, 379.2)
        assert points[2][1] == 0.1 and points[2][2] is None
        assert points[3] == ("A", 0.2, 329.5)
    finally:
        workbook.close()


def test_gap_stays_blank_in_sa_plot():
    sa = SAData(
        kind="new",
        curves=pd.DataFrame({"SA_ID": ["A", "A", "A"], "Duration_s": [0.0, 0.1, 0.2], "Voltage_kV_peak": [100.0, float("nan"), 80.0]}),
        assignments=pd.DataFrame([{"MM_ID": "MM_000", "SA_ID": "A"}]),
    )
    figure = build_envelope_figure(
        _curve_frame(1), "LG", "Max_all", "detailed", None, "Withstand", False,
        sa, {"MM_000": ["A"]},
    )
    source_trace = figure.data[1]
    assert list(source_trace.x) == [0.0, 0.1, 0.2]
    assert source_trace.y[1] is None or pd.isna(source_trace.y[1])
    assert source_trace.connectgaps is False


def test_actual_sa_source_points_are_all_in_results_export():
    root = Path(__file__).resolve().parents[2] / "04_Test_data"
    sa_path = root / "SA.xlsx"
    source = discover_sources([(sa_path.name, sa_path.read_bytes())])["sa"][0]
    sa = load_sa_workbook(source.source(), source.filename)
    output = export_xlsx_bytes(
        pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), {"SA workbook": source.filename},
        sa_curves=sa.curves, sa_assignments=sa.assignments,
    )
    workbook = load_workbook(BytesIO(output), read_only=True, data_only=True)
    try:
        rows = list(workbook["SA source points"].values)
        assert len(rows) == 1001
        values = pd.DataFrame(rows[1:], columns=rows[0])
        assert values.groupby("SA_ID")["Duration_s"].size().to_dict() == {"230 OSS SA": 500, "230 OnS SA": 500}
        assert values.loc[values["SA_ID"].eq("230 OnS SA") & values["Duration_s"].eq(0.004), "Voltage_kV_peak"].iloc[0] == 373.6
        assert values.loc[values["SA_ID"].eq("230 OSS SA") & values["Duration_s"].eq(0.998), "Voltage_kV_peak"].iloc[0] == 323.9
    finally:
        workbook.close()


def test_phase_chart_omits_run_fault_provenance_and_sa_is_lg_only():
    frame = _curve_frame(1)
    frame["MM_name_A"] = "MM_PHASE_A"
    frame["Max_A"] = frame["Voltage_kV_peak"] - 4
    phase = frame.rename(columns={"Voltage_kV_peak": "Max_all"})
    phase["Voltage_kV_peak"] = phase["Max_A"]
    sa = SAData(
        kind="new",
        curves=pd.DataFrame(
            [{"SA_ID": "ASSIGNED", "Duration_s": x, "Voltage_kV_peak": y} for x, y in ((0.0, 200), (0.1, 180))]
        ),
        assignments=pd.DataFrame([{"MM_ID": "MM_000", "SA_ID": "ASSIGNED"}]),
        source_name="test.xlsx",
    )
    lg = build_envelope_figure(phase, "LG", "Max_A", "detailed", None, "Withstand", False, sa, {"MM_000": ["ASSIGNED"]})
    names = [trace.name for trace in lg.data]
    assert not any("Assigned visual reference" in name or "Comparison only" in name for name in names)
    assert all(trace.showlegend is True for trace in lg.data[1:])
    assert not lg.layout.annotations
    assert {trace.name for trace in lg.data[1:]} == {"ASSIGNED"}
    assert not any("UNKNOWN" in name for name in names)
    envelope = lg.data[0]
    assert "Run" not in envelope.hovertemplate and "Fault type" not in envelope.hovertemplate
    assert "MM_name_A" in envelope.hovertemplate
    ll = build_envelope_figure(phase, "LL", "Max_A", "detailed", None, "Withstand", False, sa, {"MM_000": ["ASSIGNED"]})
    assert not any("ASSIGNED" in trace.name for trace in ll.data)
    assert not any("UNKNOWN" in trace.name for trace in build_envelope_figure(phase, "LG", "Max_A", "detailed", None, "Withstand", False, sa, {"MM_000": ["UNKNOWN"]}).data)
    assigned = next(trace for trace in lg.data if trace.name == "ASSIGNED")
    assert list(assigned.x) == [0.0, 0.1]
    assert "Source duration" in assigned.hovertemplate
    assert "Source document" not in assigned.hovertemplate


def test_native_legend_orders_curves_before_ic_and_sa_limits():
    frame = _curve_frame(2)
    mm_blocks = pd.DataFrame(
        [
            {"Group": f"MM_{index:03d}", "Un": 230, "SDPF_LG": 460, "SDPF_LL": 460, "SIWL_LG": 840, "SIWL_LL": 840}
            for index in range(2)
        ]
    )
    sa = SAData(
        kind="new",
        curves=pd.DataFrame([
            {"SA_ID": sa_id, "Duration_s": duration, "Voltage_kV_peak": voltage}
            for sa_id, voltage in (("SA A", 380), ("SA B", 370))
            for duration in (0.0, 0.1)
        ]),
        assignments=pd.DataFrame([{"MM_ID": "MM_000", "SA_ID": "SA A"}, {"MM_ID": "MM_001", "SA_ID": "SA B"}]),
    )
    figure = build_envelope_figure(
        frame,
        "LG",
        "Max_all",
        "detailed",
        mm_blocks,
        "Withstand",
        sa_data=sa,
        sa_by_mm={"MM_000": ["SA A"], "MM_001": ["SA B"]},
        highlight_curve=("Case 001", "MM_001"),
    )
    selected = next(trace for trace in figure.data if trace.name == "Case 001 · MM_001")
    context = next(trace for trace in figure.data if trace.name == "Case 000 · MM_000")
    assert selected.line.width == 3.6 and selected.opacity == 1
    assert context.line.width == 1.1 and context.opacity == 0.2
    visible = [trace for trace in figure.data if trace.showlegend is not False]
    assert [trace.name for trace in visible] == [
        "Case 000 · MM_000", "Case 001 · MM_001", "IC Withstand", "SA A", "SA B"
    ]
    assert [trace.legendrank for trace in visible] == [10, 10, 1000, 2000, 2000]
    assert figure.data[2].line.color == "#C2413B"
    assert [trace.legend for trace in visible] == [None, None, "legend2", "legend2", "legend2"]
    assert figure.layout.legend.font.size == 12
    assert figure.layout.legend.entrywidthmode == "pixels"
    assert figure.layout.legend.entrywidth == pytest.approx(1300 / 3 - 50)
    assert figure.layout.legend.maxheight == 40
    assert figure.layout.legend.y == pytest.approx(-78 / 460)
    assert figure.layout.legend2.font.size == figure.layout.legend.font.size
    assert figure.layout.legend2.x == figure.layout.legend.x == 0
    assert figure.layout.legend2.entrywidthmode == "pixels"
    assert figure.layout.legend2.entrywidth == figure.layout.legend.entrywidth
    assert figure.layout.legend2.maxheight == 40
    assert figure.layout.legend2.y == pytest.approx(-(78 + 40 + 18) / 460)
    assert not figure.layout.annotations
    assert figure.layout.margin.b > 100
    assert figure.layout.xaxis.title.text == "Envelope index (s)"
    columns = round(1300 / (figure.layout.legend.entrywidth + 50))
    assert columns == 3
    margin_figure = build_envelope_figure(frame, "LG", "Max_all", "detailed", mm_blocks, "Safety margin")
    margin = next(trace for trace in margin_figure.data if trace.name == "IC Safety margin" and trace.showlegend is not False)
    assert margin.line.color == "#D28B00"


def test_native_legend_handles_short_and_long_curve_lists():
    for trace_count in (2, 30):
        frame = _curve_frame(trace_count)
        figure = build_envelope_figure(frame, "LG", "Max_all", "detailed", None, "Withstand", show_ic=False, uirevision="test")
        legend_names = [trace.name for trace in figure.data if trace.showlegend is not False]
        assert len(legend_names) == trace_count
        assert legend_names[0] == "Case 000 · MM_000"
        assert legend_names[-1] == f"Case {trace_count - 1:03d} · MM_{trace_count - 1:03d}"
        assert len(figure.to_json()) > 0

    from plots import LEGEND_MAX_HEIGHT

    long_list = build_envelope_figure(_curve_frame(30), "LG", "Max_all", "detailed", None, "Withstand", show_ic=False)
    very_long_list = build_envelope_figure(_curve_frame(300), "LG", "Max_all", "detailed", None, "Withstand", show_ic=False)
    assert long_list.layout.legend.maxheight == LEGEND_MAX_HEIGHT
    assert very_long_list.layout.legend.maxheight == LEGEND_MAX_HEIGHT
    assert very_long_list.layout.height == long_list.layout.height


def test_detailed_curve_hover_keeps_identity_out_of_repeated_point_data():
    figure = build_envelope_figure(
        _curve_frame(1), "LG", "Max_all", "detailed", None, "Withstand", show_ic=False
    )
    trace = figure.data[0]

    assert list(trace.meta) == ["Case 000", "MM_000"]
    assert "Case: %{meta[0]}" in trace.hovertemplate
    assert "MM: %{meta[1]}" in trace.hovertemplate
    assert trace.customdata.tolist() == [["1", "synthetic"]] * 3


def test_detailed_curve_hover_data_stays_aligned_for_multiple_unsorted_curves():
    frame = _curve_frame(2).iloc[[3, 0, 4, 1, 5, 2]].reset_index(drop=True)
    figure = build_envelope_figure(frame, "LG", "Max_all", "detailed", None, "Withstand", show_ic=False)

    for trace in figure.data:
        case, mm_id = trace.meta
        expected = frame.loc[frame["Case"].eq(case) & frame["MM_ID"].eq(mm_id)]
        assert trace.x.tolist() == expected["Index_s"].tolist()
        assert trace.customdata.tolist() == expected[["Run", "Fault_type"]].astype(str).to_numpy().tolist()


def test_legend_column_count_uses_width_not_curve_count_divisibility():
    frame = _curve_frame(5)
    case_names = ["C1_S1_230OnS2", "C3_S1_230OnS2", "C5_S1_230OnS2", "C7_S1_230OnS2", "C9_S1_230OnS2"]
    frame["Case"] = frame["Case"].map({f"Case {index:03d}": name for index, name in enumerate(case_names)})
    frame["MM_ID"] = "MM_230_VSR2"
    mm_blocks = pd.DataFrame(
        [{"Group": "MM_230_VSR2", "Un": 230, "SDPF_LG": 460, "SDPF_LL": 460, "SIWL_LG": 840, "SIWL_LL": 840}]
    )
    figure = build_envelope_figure(frame, "LG", "Max_all", "detailed", mm_blocks, "Withstand")
    curve_count = len([trace for trace in figure.data if trace.legend != "legend2" and trace.showlegend is not False])
    columns = round(1300 / (figure.layout.legend.entrywidth + 50))

    assert curve_count == 5
    assert columns == 3
    assert figure.layout.legend2 is not None
    assert figure.layout.legend2.entrywidthmode == "pixels"
    assert figure.layout.legend2.y == pytest.approx(-(78 + 40 + 18) / 460)


def test_legend_column_count_changes_with_available_width():
    from plots import _legend_column_layout

    labels = [
        "C5_S1_230OnS2 · MM_230_VSR2",
        "C1_S1_230OnS2 · MM_230_VSR2",
        "C3_S1_230OnS2 · MM_230_VSR2",
        "IC Safety margin",
        "230 OSS SA",
    ]
    assert _legend_column_layout(labels, available_width=956)[0] == 3
    assert _legend_column_layout(labels, available_width=600)[0] == 2
    assert _legend_column_layout(labels, available_width=1200)[0] == 3


def test_legend_pixel_width_tracks_the_rendered_plot_width():
    narrow = build_envelope_figure(
        _curve_frame(5), "LG", "Max_all", "detailed", None, "Withstand", show_ic=False,
        plot_container_width=1050,
    )
    wide = build_envelope_figure(
        _curve_frame(5), "LG", "Max_all", "detailed", None, "Withstand", show_ic=False,
        plot_container_width=1600,
    )

    assert narrow.layout.legend.entrywidthmode == "pixels"
    assert narrow.layout.width == 1050
    assert wide.layout.width == 1600
    assert narrow.layout.legend.entrywidth < wide.layout.legend.entrywidth
    assert round((1050 - 100) / (narrow.layout.legend.entrywidth + 50)) == 3
    assert round((1600 - 100) / (wide.layout.legend.entrywidth + 50)) == 3


def test_report_figures_keep_summary_curves_and_only_detailed_limits_in_legend():
    mm_blocks = pd.DataFrame(
        [
            {"Group": f"MM_{index:03d}", "Un": 230, "SDPF_LG": 460, "SDPF_LL": 460, "SIWL_LG": 840, "SIWL_LL": 840}
            for index in range(2)
        ]
    )
    detailed = build_envelope_figure(_curve_frame(2), "LG", "Max_all", "detailed", mm_blocks, "Withstand")
    report_detail = prepare_report_figure(detailed, include_curve_legend=False)
    visible_detail = [trace.name for trace in report_detail.data if trace.showlegend is not False]

    summary = build_envelope_figure(_curve_frame(1), "LG", "Max_all", "summary", mm_blocks, "Withstand")
    report_summary = prepare_report_figure(summary, include_curve_legend=True)
    visible_summary = [trace.name for trace in report_summary.data if trace.showlegend is not False]

    assert visible_detail == ["IC Withstand"]
    assert [trace.name for trace in detailed.data if trace.showlegend is not False][:2] == [
        "Case 000 · MM_000",
        "Case 001 · MM_001",
    ]
    assert visible_summary == ["Maximum envelope", "IC Withstand"]
    assert report_detail.layout.width == report_summary.layout.width == REPORT_PNG_WIDTH
    assert report_detail.layout.height == report_summary.layout.height == REPORT_PNG_HEIGHT
    assert not report_detail.layout.legend2.to_plotly_json()
    assert not report_summary.layout.legend2.to_plotly_json()
    assert all(trace.legend == "legend" for trace in report_summary.data if trace.showlegend is not False)
    assert report_summary.layout.legend.y == pytest.approx(
        -REPORT_LEGEND_TOP_OFFSET
        / (REPORT_PNG_HEIGHT - 75 - REPORT_LEGEND_TOP_OFFSET - 36 - REPORT_LEGEND_BOTTOM_PADDING)
    )
    assert report_summary.layout.margin.b == (
        REPORT_LEGEND_TOP_OFFSET + 36 + REPORT_LEGEND_BOTTOM_PADDING
    )
    assert summary.data[0].legend == "legend"
    assert summary.data[1].legend == "legend2"
    assert summary.layout.legend2.y < 0


def test_summary_page_figure_shows_maximum_envelope_in_its_curve_legend():
    mm_blocks = pd.DataFrame(
        [{"Group": "MM_000", "Un": 230, "SDPF_LG": 460, "SDPF_LL": 460, "SIWL_LG": 840, "SIWL_LL": 840}]
    )
    summary = build_envelope_figure(
        _curve_frame(1), "LL", "Max_all", "summary", mm_blocks, "Safety margin"
    )

    curve = summary.data[0]
    assert curve.name == "Maximum envelope"
    assert curve.showlegend is True
    assert curve.legend == "legend"
    expected = _curve_frame(1)[["Case", "MM_ID", "Run", "Fault_type"]].astype(str).to_numpy().tolist()
    assert curve.customdata.tolist() == expected
    assert "Governing Run: %{customdata[2]}" in curve.hovertemplate
    assert "Fault type: %{customdata[3]}" in curve.hovertemplate
    assert summary.layout.legend2 is not None
    assert summary.layout.legend2.y == pytest.approx(-(48 + 40 + 18) / 460)
    assert summary.layout.legend.y == pytest.approx(-48 / 460)


def test_report_chart_zip_contains_two_fixed_size_pngs():
    figures = {
        measurement: build_envelope_figure(
            _curve_frame(1), measurement, "Max_all", "detailed", None, "Withstand", show_ic=False
        )
        for measurement in ("LG", "LL")
    }

    output = export_report_charts_zip(
        figures,
        include_curve_legend=False,
        filename_prefix="all_envelopes",
    )

    with ZipFile(BytesIO(output)) as archive:
        assert archive.namelist() == ["all_envelopes_LG.png", "all_envelopes_LL.png"]
        for name in archive.namelist():
            image = archive.read(name)
            assert image[:8] == b"\x89PNG\r\n\x1a\n"
            assert unpack(">II", image[16:24]) == (REPORT_PNG_WIDTH, REPORT_PNG_HEIGHT)
