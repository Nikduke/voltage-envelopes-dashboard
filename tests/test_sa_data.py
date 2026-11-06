from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd
import pytest
from openpyxl import Workbook, load_workbook

from analysis import select_curves
from data_loader import classify_filename, discover_sources, load_project_data
from plots import build_envelope_figure
from sa_data import (
    SA_ASSIGNMENT_COLUMNS,
    SA_CURVE_COLUMNS,
    create_blank_template,
    load_sa_workbook,
    validate_sa_compatibility,
    write_sa_workbook,
)


def _type(sa_id="A", **overrides):
    row = {
        "SA_ID": sa_id,
        "System_kV": 230.0,
        "Manufacturer": "Example manufacturer",
        "Model": f"Model {sa_id}",
        "Curve_Type": "TOV_capability_reference",
        "Duty_Condition": "reference",
        "Valid_From_s": np.nan,
        "Valid_To_s": np.nan,
        "Source_Document": "Example datasheet",
        "Verification_Status": "Unverified_Engineering_Reference",
        "Voltage_Basis": "kV_peak",
        "Data_From_s": 0.0,
        "Data_To_s": 0.2,
        "Notes": "Example",
    }
    row.update(overrides)
    return row


def _wide_workbook(types, headers, rows, assignments=None):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "SA_Types"
    type_headers = list(types[0].keys()) if types else ["SA_ID"]
    sheet.append(type_headers)
    for row in types:
        sheet.append([row.get(column) for column in type_headers])
    curve_sheet = workbook.create_sheet("SA_Curves")
    curve_sheet.append(headers)
    for row in rows:
        curve_sheet.append(row)
    assignment_sheet = workbook.create_sheet("MM_Assignment")
    assignment_sheet.append(list(SA_ASSIGNMENT_COLUMNS))
    for row in assignments or []:
        assignment_sheet.append([row.get(column) for column in SA_ASSIGNMENT_COLUMNS])
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


def _sample_sa_workbook():
    curves = pd.DataFrame(
        {
            "SA_ID": ["TEST_A"] * 5,
            "Duration_s": [0.0, 0.02, 0.05, 0.1, 1.0],
            "Voltage_kV_peak": [650.0, 610.0, 560.0, 520.0, 480.0],
        },
        columns=SA_CURVE_COLUMNS,
    )
    assignments = pd.DataFrame([{"MM_ID": "MM_TEST", "SA_ID": "TEST_A"}], columns=SA_ASSIGNMENT_COLUMNS)
    return write_sa_workbook(curves, assignments)


def test_actual_test_data_wide_sa_values_and_assignments():
    root = Path(__file__).resolve().parents[2] / "04_Test_data"
    candidates = discover_sources([(path.name, path.read_bytes()) for path in root.iterdir() if path.is_file() and path.suffix.casefold() != ".zip"])
    assert [candidate.filename for candidate in candidates["lg"]] == ["LGp.csv"]
    assert [candidate.filename for candidate in candidates["ll"]] == ["LLp.csv"]
    assert [candidate.filename for candidate in candidates["sa"]] == ["SA.xlsx"]
    sa = load_sa_workbook(candidates["sa"][0].source(), "SA.xlsx")
    assert sa.kind == "new"
    assert set(sa.curves["SA_ID"]) == {"230 OnS SA", "230 OSS SA"}
    for sa_id in ("230 OnS SA", "230 OSS SA"):
        curve = sa.curves.loc[sa.curves["SA_ID"].eq(sa_id)]
        assert len(curve) == 500
        assert curve["Voltage_kV_peak"].notna().sum() == 500
    expected = {
        ("230 OnS SA", 0.000): 379.2,
        ("230 OnS SA", 0.004): 373.6,
        ("230 OnS SA", 0.998): 329.5,
        ("230 OSS SA", 0.000): 381.1,
        ("230 OSS SA", 0.004): 374.8,
        ("230 OSS SA", 0.998): 323.9,
    }
    for (sa_id, duration), voltage in expected.items():
        value = sa.curves.loc[sa.curves["SA_ID"].eq(sa_id) & sa.curves["Duration_s"].eq(duration), "Voltage_kV_peak"].iloc[0]
        assert value == pytest.approx(voltage)
    assert set(sa.assignments.columns) == {"MM_ID", "SA_ID"}
    assert dict(zip(
        sa.assignments.loc[sa.assignments["SA_ID"].ne(""), "MM_ID"],
        sa.assignments.loc[sa.assignments["SA_ID"].ne(""), "SA_ID"],
    )) == {
        "MM_230_ONS1": "230 OnS SA",
        "MM_230_ONS2": "230 OnS SA",
        "MM_230_OSS1": "230 OSS SA",
        "MM_230_OSS2": "230 OSS SA",
    }
    assert "WLs.xlsx" not in " ".join(candidate.filename for role in candidates.values() for candidate in role)


def test_05_project_sa_workbook_uses_mapping_and_curve_without_sa_types():
    path = Path(__file__).resolve().parents[2] / "05_Test_data" / "SA.xlsx"
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet_names = set(workbook.sheetnames)
        assert {"SA_Types", "SA_Curves", "MM_Assignment"}.issubset(sheet_names)
        type_headers = [cell.value for cell in next(workbook["SA_Types"].iter_rows(min_row=1, max_row=1))]
        curve_headers = [cell.value for cell in next(workbook["SA_Curves"].iter_rows(min_row=1, max_row=1))]
        assignment_headers = [cell.value for cell in next(workbook["MM_Assignment"].iter_rows(min_row=1, max_row=1))]
    finally:
        workbook.close()

    sa = load_sa_workbook(path.read_bytes(), path.name)
    assert sa.kind == "new"
    assert curve_headers == ["Duration_s", "66 WTT SA"]
    assert assignment_headers == ["MM_ID", "SA_ID"]
    assert "SA_VI_Calculated" in sheet_names
    assert type_headers[0] == "SA_ID"
    assert sa.curves["SA_ID"].nunique() == 1
    assert sa.curves["SA_ID"].unique().tolist() == ["66 WTT SA"]
    assert sa.curves["Voltage_kV_peak"].notna().sum() == 241
    mapped = sa.assignments.loc[sa.assignments["SA_ID"].ne(""), "SA_ID"]
    assert len(mapped) == 40
    assert set(mapped) == {"66 WTT SA"}
    assert not any(issue["Severity"] == "Error" for issue in sa.issues)


def test_new_sa_filename_contract_is_case_insensitive_and_excludes_legacy_names():
    assert classify_filename("SA.xlsx") == "sa"
    assert classify_filename("sa_Project_A.XLSX") == "sa"
    assert classify_filename("SA_Formosa4.xlsx") == "sa"
    assert classify_filename("SA_Project.xlsm") is None
    assert classify_filename("SAs.xlsx") is None
    assert classify_filename("SAs(1).xlsx") is None
    assert classify_filename("SA analysis CIGRE method.xlsx") is None
    assert classify_filename("~$SA.xlsx") is None


def test_wide_format_preserves_blank_points_ids_and_roundtrips():
    raw = _wide_workbook(
        [_type("A"), _type("B")],
        ["Duration_s", "A", "B"],
        [[0.0, 100.0, 90.0], [0.1, None, 80.0], [0.2, 70.0, 60.0]],
        [{"MM_ID": "MM_A", "SA_ID": "A"}, {"MM_ID": "MM_B", "SA_ID": ""}],
    )
    loaded = load_sa_workbook(raw, "SA.xlsx")
    assert loaded.kind == "new"
    missing = loaded.curves.loc[loaded.curves["SA_ID"].eq("A") & loaded.curves["Duration_s"].eq(0.1), "Voltage_kV_peak"].iloc[0]
    assert pd.isna(missing)
    assert loaded.assignments.loc[1, "SA_ID"] == ""
    exported = write_sa_workbook(loaded.curves, loaded.assignments)
    reloaded = load_sa_workbook(exported, "roundtrip.xlsx")
    assert reloaded.kind == "new"
    assert reloaded.curves.equals(loaded.curves)
    assert reloaded.assignments.equals(loaded.assignments)


def test_sa_workbook_requires_only_curves_and_mm_assignments():
    raw = write_sa_workbook(
        pd.DataFrame({"SA_ID": ["A", "A"], "Duration_s": [0.0, 0.1], "Voltage_kV_peak": [100.0, 90.0]}),
        pd.DataFrame([{"MM_ID": "MM_A", "SA_ID": "A"}]),
    )
    loaded = load_sa_workbook(raw, "minimal.xlsx")
    assert loaded.kind == "new"
    assert loaded.curves["Voltage_kV_peak"].tolist() == [100.0, 90.0]
    assert loaded.assignments.iloc[0].to_dict() == {"MM_ID": "MM_A", "SA_ID": "A"}


def test_invalid_assignment_and_curve_data_are_reported_but_metadata_is_ignored():
    duplicate_assignments = _wide_workbook(
        [_type("A")],
        ["Duration_s", "A"],
        [[0.0, 100.0], [0.1, 90.0]],
        [{"MM_ID": "MM_A", "SA_ID": "A"}, {"MM_ID": "MM_A", "SA_ID": "A"}],
    )
    duplicate_loaded = load_sa_workbook(duplicate_assignments, "duplicate.xlsx")
    assert "duplicate_mm_assignment" in {issue["Code"] for issue in duplicate_loaded.issues}

    optional_metadata = _wide_workbook(
        [_type(Voltage_Basis="kV RMS")],
        ["Duration_s", "A"],
        [[0.0, 100.0], [0.1, 90.0]],
        [{"MM_ID": "MM_A", "SA_ID": "A"}],
    )
    metadata_loaded = load_sa_workbook(optional_metadata, "metadata_ignored.xlsx")
    assert metadata_loaded.kind == "new"
    assert not metadata_loaded.issues

    malformed_points = _wide_workbook(
        [_type()],
        ["Duration_s", "A"],
        [[0.1, 100.0], [0.1, 90.0], [0.0, 80.0]],
        [],
    )
    malformed = load_sa_workbook(malformed_points, "bad_duration.xlsx")
    codes = {issue["Code"] for issue in malformed.issues}
    assert {"duplicate_sa_duration", "unordered_sa_duration"}.issubset(codes)


def test_duplicate_curve_headers_and_orphan_headers_are_not_silently_renamed():
    duplicate = _wide_workbook(
        [_type("A")],
        ["Duration_s", "A", "A"],
        [[0.0, 100.0, 95.0]],
        [],
    )
    result = load_sa_workbook(duplicate, "duplicate_header.xlsx")
    assert "duplicate_curve_header" in {issue["Code"] for issue in result.issues}

    orphan = _wide_workbook(
        [_type("A")],
        ["Duration_s", "A"],
        [[0.0, 100.0]],
        [{"MM_ID": "MM_NOT_IN_CATALOGUE", "SA_ID": "B"}],
    )
    result = load_sa_workbook(orphan, "orphan.xlsx")
    assert "unknown_assigned_sa" in {issue["Code"] for issue in result.issues}
    mm_blocks = pd.DataFrame([{"Group": "MM_OTHER", "Un": 230.0}])
    compatibility = validate_sa_compatibility(result, mm_blocks)
    assert "unknown_assigned_mm" in {issue["Code"] for issue in compatibility}


def test_sa_types_metadata_does_not_gate_exact_mm_mapping():
    raw = _wide_workbook(
        [_type("A", System_kV=230.0)],
        ["Duration_s", "A"],
        [[0.0, 100.0]],
        [{"MM_ID": "MM_A", "SA_ID": "A"}],
    )
    sa = load_sa_workbook(raw, "mismatch.xlsx")
    issues = validate_sa_compatibility(sa, pd.DataFrame([{"Group": "MM_A", "Un": 66.0}]))
    assert not issues


def test_test_data_assignments_select_the_exact_lg_reference_only():
    root = Path(__file__).resolve().parents[2] / "04_Test_data"
    candidates = discover_sources([(path.name, path.read_bytes()) for path in root.iterdir() if path.is_file() and path.suffix.casefold() != ".zip"])
    selected = {role: items[0] if len(items) == 1 else None for role, items in candidates.items()}
    project = load_project_data(selected)
    cases = [str(project.lg["Case"].dropna().iloc[0])]
    for mm_id, sa_id in (("MM_230_ONS1", "230 OnS SA"), ("MM_230_OSS1", "230 OSS SA")):
        rows = select_curves(project.lg, cases, [mm_id], None, "Max_all")
        assert not rows.empty
        figure = build_envelope_figure(
            rows, "LG", "Max_all", "detailed", project.mm_blocks, "Withstand",
            show_ic=False, sa_data=project.sa, sa_by_mm={mm_id: [sa_id]},
        )
        references = [trace for trace in figure.data if sa_id in trace.name]
        assert len(references) == 1
        assert len(references[0].x) == 500
        assert references[0].x[0] == 0.0 and references[0].x[-1] == 0.998
        assert "SA ID:" in references[0].hovertemplate
        ll = build_envelope_figure(
            rows, "LL", "Max_all", "detailed", project.mm_blocks, "Withstand",
            show_ic=False, sa_data=project.sa, sa_by_mm={mm_id: [sa_id]},
        )
        assert not any(sa_id in trace.name for trace in ll.data)
    unassigned = project.sa.assignments.loc[project.sa.assignments["MM_ID"].eq("MM_230_ONT1"), "SA_ID"].iloc[0]
    assert unassigned == ""


def test_two_sheet_template_and_old_sas_workbook_is_not_accepted():
    for template_bytes in (
        create_blank_template(),
        (Path(__file__).resolve().parents[1] / "templates" / "SA_characteristics_template.xlsx").read_bytes(),
    ):
        template = load_workbook(BytesIO(template_bytes), read_only=True, data_only=True)
        try:
            assert template.sheetnames == ["SA_Curves", "MM_Assignment"]
            assert next(template["SA_Curves"].iter_rows(values_only=True)) == ("Duration_s",)
            assert next(template["MM_Assignment"].iter_rows(values_only=True)) == ("MM_ID", "SA_ID")
        finally:
            template.close()
    example = load_sa_workbook(_sample_sa_workbook(), "test_reference.xlsx")
    assert example.kind == "new" and len(example.curves) == 5

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame({"Time (s)": [0.0, 0.1, 0.2], "Element": ["SA A"] * 3, "TOV capability": [100.0, 90.0, 80.0]}).to_excel(writer, sheet_name="SAs", index=False)
    old_format = load_sa_workbook(buffer.getvalue(), "SAs.xlsx")
    assert old_format.kind == "invalid"


def test_excel_file_can_be_replaced_after_loading():
    test_root = Path(__file__).resolve().parents[1] / ".test-temp"
    test_root.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=test_root) as work:
        path = Path(work) / "SA.xlsx"
        path.write_bytes(_sample_sa_workbook())
        assert load_sa_workbook(path, path.name).kind == "new"
        moved = path.with_name("SA-replaced.xlsx")
        path.replace(moved)
        assert moved.exists() and not path.exists()
