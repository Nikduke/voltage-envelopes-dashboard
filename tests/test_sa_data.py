from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd
import pytest

from data_loader import discover_sources, load_project_data
from sa_data import (
    SA_ASSIGNMENT_COLUMNS,
    SA_CURVE_COLUMNS,
    SA_TYPE_COLUMNS,
    convert_legacy_to_new,
    create_blank_template,
    create_synthetic_example,
    interpolate_sa,
    load_sa_workbook,
    write_sa_workbook,
)


def test_sample_legacy_sa_is_unknown_and_unassigned():
    root = Path(__file__).resolve().parents[2] / "02_Excel_Example"
    candidates = discover_sources(root)
    sa_source = candidates["sa"][0]
    loaded = load_sa_workbook(sa_source.path, sa_source.filename)
    assert loaded.kind == "legacy"
    assert len(loaded.legacy) == 1000
    assert loaded.types["Verification_Status"].eq("Unknown").all()
    assert loaded.types["Voltage_Basis"].eq("Unknown").all()
    assert loaded.assignments.empty
    assert any(issue["Code"] == "legacy_unknown_basis" for issue in loaded.issues)


def test_new_format_roundtrip_and_explicit_legacy_conversion():
    root = Path(__file__).resolve().parents[2] / "02_Excel_Example"
    candidates = discover_sources(root)
    sa_source = candidates["sa"][0]
    legacy = load_sa_workbook(sa_source.path, sa_source.filename)
    mm = pd.read_excel(candidates["mm"][0].path, sheet_name="MM_blocks")
    elements = sorted(legacy.legacy["Element"].unique())
    mm_candidates = mm.loc[mm["Un"].eq(230), "Group"].tolist()
    mapping = {
        elements[0]: {"MM_ID": mm_candidates[0], "Installation_Status": "Unknown"},
        elements[1]: {"MM_ID": mm_candidates[1], "Installation_Status": "Installed"},
    }
    converted = convert_legacy_to_new(legacy, mm, mapping)
    loaded = load_sa_workbook(converted, "converted.xlsx")
    assert loaded.kind == "new"
    assert len(loaded.assignments) == 2
    assert set(loaded.assignments["MM_ID"]) == set(mm_candidates[:2])
    assert loaded.types["Voltage_Basis"].eq("Unknown").all()
    assert loaded.types["Verification_Status"].eq("Unknown").all()
    assert len(loaded.curves) == 1000
    assert load_sa_workbook(create_blank_template(), "template.xlsx").kind == "new"
    example = load_sa_workbook(create_synthetic_example(), "synthetic.xlsx")
    assert example.kind == "new" and len(example.curves) == 5
    with pytest.raises(ValueError, match="Assign every"):
        convert_legacy_to_new(legacy, mm, {})


def test_interpolation_does_not_extrapolate():
    curves = pd.DataFrame({"SA_ID": ["A"] * 3, "Duration_s": [0.1, 0.2, 0.4], "Voltage_kV_peak": [100.0, 80.0, 60.0]})
    values = interpolate_sa(curves, "A", np.array([0.05, 0.1, 0.15, 0.4, 0.5]), 0.1, 0.4)
    assert np.isnan(values[[0, 4]]).all()
    assert values[1:4].tolist() == pytest.approx([100.0, 90.0, 60.0])


def test_bad_curve_points_are_flagged():
    types = pd.DataFrame(
        [{"SA_ID": "A", "System_kV": 230, "Manufacturer": "M", "Model": "X", "Curve_Type": "TOV_withstand", "Duty_Condition": "duty", "Valid_From_s": 0.1, "Valid_To_s": 0.3, "Source_Document": "source", "Verification_Status": "Verified", "Voltage_Basis": "kV_peak"}],
        columns=SA_TYPE_COLUMNS,
    )
    curves = pd.DataFrame({"SA_ID": ["A", "A", "A"], "Duration_s": [0.1, 0.1, 0.05], "Voltage_kV_peak": [100.0, 90.0, 80.0]}, columns=SA_CURVE_COLUMNS)
    assignments = pd.DataFrame(columns=SA_ASSIGNMENT_COLUMNS)
    loaded = load_sa_workbook(write_sa_workbook(types, curves, assignments), "bad.xlsx")
    codes = {issue["Code"] for issue in loaded.issues}
    assert "duplicate_sa_duration" in codes
    assert "unordered_sa_duration" in codes
    assert "curve_outside_valid_range" in codes


def test_excel_file_can_be_replaced_after_loading():
    test_root = Path(__file__).resolve().parents[1] / ".test-temp"
    test_root.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=test_root) as work:
        workdir = Path(work)
        path = workdir / "sa.xlsx"
        path.write_bytes(create_synthetic_example())
        loaded = load_sa_workbook(path, path.name)
        assert loaded.kind == "new"
        moved = workdir / "sa-replaced.xlsx"
        path.replace(moved)
        assert moved.exists() and not path.exists()
