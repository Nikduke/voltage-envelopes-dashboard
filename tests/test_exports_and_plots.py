from io import BytesIO

import pandas as pd
from PIL import Image
from openpyxl import load_workbook

from exports import export_xlsx_bytes, figure_image_bytes, selected_csv_bytes
from plots import build_envelope_figure
from sa_data import SAData


def _curve_frame(trace_count: int) -> pd.DataFrame:
    rows = []
    for index in range(trace_count):
        for sample, x in enumerate((0.0, 0.02, 0.1)):
            rows.append({"Case": f"Case {index:03d}", "MM_ID": f"MM_{index:03d}", "Index_s": x, "Voltage_kV_peak": 500 + index + sample, "Run": 1, "Fault_type": "synthetic"})
    return pd.DataFrame(rows)


def test_csv_carries_filters_and_assessment_metadata():
    frame = _curve_frame(1)
    output = selected_csv_bytes(frame, {"Cases": ["C1", "C2"], "Units": "kV peak"})
    read = pd.read_csv(BytesIO(output))
    assert read["_Metadata_Cases"].eq("C1, C2").all()
    assert read["_Metadata_Units"].eq("kV peak").all()
    assert read["Assessment_Status"].str.contains("not a chronological").all()


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
        assert set(workbook.sheetnames) == {"Selected data", "Envelope summary", "Reference comparison", "Validation", "Metadata"}
        summary_rows = list(workbook["Envelope summary"].values)
        assert summary_rows[1][0:3] == ("Case 000", "MM_000", 502)
        metadata_rows = list(workbook["Metadata"].values)
        metadata = {row[0]: row[1] for row in metadata_rows[1:]}
        assert metadata["Units"] == "kV peak"
        assert metadata["IC factor"] == "1.15"
        assert "not a chronological" in metadata["Assessment status"]
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
        types=pd.DataFrame(
            [
                {"SA_ID": "ASSIGNED", "System_kV": 230, "Manufacturer": "M", "Model": "A", "Curve_Type": "TOV_withstand", "Duty_Condition": "duty A", "Valid_From_s": 0.0, "Valid_To_s": 0.1, "Source_Document": "source A", "Verification_Status": "Verified", "Voltage_Basis": "kV_peak"},
                {"SA_ID": "ALT", "System_kV": 230, "Manufacturer": "M", "Model": "B", "Curve_Type": "TOV_withstand", "Duty_Condition": "duty B", "Valid_From_s": 0.0, "Valid_To_s": 0.1, "Source_Document": "source B", "Verification_Status": "Unverified", "Voltage_Basis": "kV_peak"},
                {"SA_ID": "UNKNOWN", "System_kV": 230, "Manufacturer": "?", "Model": "C", "Curve_Type": "TOV_withstand", "Duty_Condition": "unknown", "Valid_From_s": 0.0, "Valid_To_s": 0.1, "Source_Document": "source C", "Verification_Status": "Unknown", "Voltage_Basis": "Unknown"},
            ]
        ),
        curves=pd.DataFrame(
            [{"SA_ID": sa_id, "Duration_s": x, "Voltage_kV_peak": y} for sa_id, y in (("ASSIGNED", 200), ("ALT", 180), ("UNKNOWN", 160)) for x in (0.0, 0.1)]
        ),
        assignments=pd.DataFrame([{"MM_ID": "MM_000", "SA_ID": "ASSIGNED", "Installation_Status": "Installed", "Notes": "explicit"}]),
        source_name="test.xlsx",
    )
    lg = build_envelope_figure(phase, "LG", "Max_A", "detailed", None, "Withstand", False, sa, {"MM_000": ["ASSIGNED", "ALT", "UNKNOWN"]}, False)
    names = [trace.name for trace in lg.data]
    assert any("assigned" in name for name in names)
    assert any("Comparison only" in name for name in names)
    assert not any("UNKNOWN" in name for name in names)
    envelope = lg.data[0]
    assert "Run" not in envelope.hovertemplate and "Fault type" not in envelope.hovertemplate
    assert "MM_name_A" in envelope.hovertemplate
    ll = build_envelope_figure(phase, "LL", "Max_A", "detailed", None, "Withstand", False, sa, {"MM_000": ["ASSIGNED"]})
    assert not any("ASSIGNED" in trace.name for trace in ll.data)
    unknown = build_envelope_figure(phase, "LG", "Max_A", "detailed", None, "Withstand", False, sa, {"MM_000": ["UNKNOWN"]}, True)
    assert any("basis unknown" in trace.name for trace in unknown.data)


def test_png_svg_export_keeps_short_and_long_legends():
    for trace_count in (2, 30):
        frame = _curve_frame(trace_count)
        figure = build_envelope_figure(frame, "LG", "Max_all", "detailed", None, "Withstand", show_ic=False, uirevision="test")
        png = figure_image_bytes(figure, "png")
        image = Image.open(BytesIO(png)).convert("RGB")
        assert image.width == 1400
        assert image.height >= 450
        pixels = image.load()
        bottom = image.crop((0, int(image.height * 0.72), image.width, image.height))
        assert len(bottom.getcolors(maxcolors=1_000_000) or []) > 10
        svg = figure.to_image(format="svg", width=1400, height=figure.layout.height).decode("utf-8")
        for index in range(trace_count):
            assert f"Case {index:03d} · MM_{index:03d}" in svg
