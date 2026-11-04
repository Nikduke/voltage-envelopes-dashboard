from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from analysis import crossing_summary, curve_summary, select_curves, summary_envelope
from data_loader import discover_sources, load_project_data
from limits import CHANGEOVER_S, SAFETY_FACTOR, ic_curve, ic_values


def test_ic_calculation_and_exact_changeover():
    mm = {
        "SIWL_LG": 840.0,
        "SDPF_LG": 460.0,
        "SIWL_LL": 800.0,
        "SDPF_LL": 400.0,
    }
    values = ic_values(mm, "LG")
    assert values["SIWL_peak"] == 840.0
    assert values["SDPF_peak"] == pytest.approx(460.0 * np.sqrt(2.0))
    assert values["SIWL_margin_peak"] == pytest.approx(840.0 / SAFETY_FACTOR)
    assert values["SDPF_margin_peak"] == pytest.approx(460.0 * np.sqrt(2.0) / SAFETY_FACTOR)
    indices = np.array([0.018, 0.020, 0.030, 0.032])
    result = ic_curve(mm, "LG", indices, "Withstand")
    assert result.tolist() == pytest.approx([840.0, 460.0 * np.sqrt(2.0), 460.0 * np.sqrt(2.0), 460.0 * np.sqrt(2.0)])
    assert CHANGEOVER_S == 0.020
    assert ic_curve(mm, "LL", np.array([0.020]), "Withstand")[0] == pytest.approx(400.0 * np.sqrt(2.0))


def test_summary_uses_per_index_winner_and_only_max_all_provenance():
    rows = pd.DataFrame(
        [
            {"Case": "C1", "MM_ID": "MM_A", "Index_s": 0.0, "Voltage_kV_peak": 10.0, "Run": 1, "Fault_type": "A"},
            {"Case": "C2", "MM_ID": "MM_B", "Index_s": 0.0, "Voltage_kV_peak": 12.0, "Run": 2, "Fault_type": "B"},
            {"Case": "C1", "MM_ID": "MM_A", "Index_s": 1.0, "Voltage_kV_peak": 15.0, "Run": 1, "Fault_type": "C"},
            {"Case": "C2", "MM_ID": "MM_B", "Index_s": 1.0, "Voltage_kV_peak": 14.0, "Run": 2, "Fault_type": "D"},
        ]
    )
    maximum = summary_envelope(rows, "Max_all")
    assert maximum["Voltage_kV_peak"].tolist() == [12.0, 15.0]
    assert maximum["Case"].tolist() == ["C2", "C1"]
    assert maximum["MM_ID"].tolist() == ["MM_B", "MM_A"]
    assert maximum["Run"].tolist() == [2, 1]
    assert maximum["Fault_type"].tolist() == ["B", "C"]
    phase = summary_envelope(rows, "Max_A")
    assert "Run" not in phase and "Fault_type" not in phase


def test_limit_join_uses_exact_mm_group_even_at_same_voltage():
    mm = pd.DataFrame(
        [
            {"Group": "MM_A", "Un": 230, "SIWL_LG": 100, "SDPF_LG": 100, "SIWL_LL": 110, "SDPF_LL": 110},
            {"Group": "MM_B", "Un": 230, "SIWL_LG": 200, "SDPF_LG": 200, "SIWL_LL": 210, "SDPF_LL": 210},
        ]
    )
    selected = pd.DataFrame(
        [
            {"Case": "C1", "MM_ID": "MM_A", "Index_s": 0.020, "Voltage_kV_peak": 150},
            {"Case": "C1", "MM_ID": "MM_B", "Index_s": 0.020, "Voltage_kV_peak": 150},
        ]
    )
    counts = crossing_summary(selected, mm, "LG", "Withstand")
    by_mm = counts.set_index("MM_ID")["Ranked samples above reference"]
    assert by_mm.to_dict() == {"MM_A": 1, "MM_B": 0}


def test_empty_filter_does_not_create_zero_rows():
    frame = pd.DataFrame(
        [{"Case": "C1", "MM_name_all": "MM_A", "Time (s)": 0.0, "Max_all": 10.0}]
    )
    assert select_curves(frame, [], ["MM_A"], None).empty
    assert select_curves(frame, ["C2"], ["MM_A"], None).empty
    empty = curve_summary(pd.DataFrame(), "Max_all")
    assert empty.empty
    assert "Peak Run" in empty.columns and "Peak Fault_type" in empty.columns


def test_sample_regression_counts_and_ranked_reference_comparison():
    root = Path(__file__).resolve().parents[2] / "02_Excel_Example"
    candidates = discover_sources(root)
    selected = {role: items[0] if len(items) == 1 else None for role, items in candidates.items()}
    project = load_project_data(selected)
    assert project.lg is not None and project.ll is not None and project.mm_blocks is not None
    for frame in (project.lg, project.ll):
        assert len(frame) == 77_000
        assert frame["Case"].nunique() == 6
        assert frame["MM_name_all"].nunique() == 27
        assert frame[["Time (s)", "Max_A", "Max_B", "Max_C", "Max_all", "Run"]].apply(np.isfinite).all().all()
        assert np.allclose(frame["Max_all"], frame[["Max_A", "Max_B", "Max_C"]].max(axis=1), atol=1e-8)
        assert not frame.duplicated(["Case", "MM_name_all", "Time (s)"]).any()
    assert project.mm_blocks["Group"].nunique() == 31
    configured_absence = [issue for issue in project.issues if issue["Code"] == "configured_mm_without_results"]
    assert configured_absence and "4 configured MM points" in configured_absence[0]["Message"]
    c3_missing = [issue for issue in project.issues if issue["Code"] == "missing_case_mm_combinations"]
    assert c3_missing and "8 case/MM combinations" in c3_missing[0]["Message"]
    unrepresented_22 = project.mm_blocks.loc[project.mm_blocks["Un"].eq(22.8), "Group"].tolist()
    result_mms = set(project.lg["MM_name_all"].astype(str)) | set(project.ll["MM_name_all"].astype(str))
    assert len(unrepresented_22) == 4
    assert set(unrepresented_22).isdisjoint(result_mms)
    for measurement, frame, expected in (("LG", project.lg, 0), ("LL", project.ll, 444)):
        selected_rows = select_curves(frame, sorted(frame["Case"].unique()), sorted(frame["MM_name_all"].unique()), None)
        counts = crossing_summary(selected_rows, project.mm_blocks, measurement, "Safety margin")
        assert int(counts["Ranked samples above reference"].sum()) == expected
        assert counts["Ranked samples above reference"].gt(0).sum() == (16 if expected else 0)
        assert counts["Assessment"].str.contains("not a chronological").all()
        raw = crossing_summary(selected_rows, project.mm_blocks, measurement, "Withstand")
        assert int(raw["Ranked samples above reference"].sum()) == 0
