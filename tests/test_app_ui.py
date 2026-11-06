import json
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd
from streamlit.testing.v1 import AppTest
from selection_state import selection_after_click


def _project_files(mm_id: str = "MM_A", voltage: float = 66.0) -> dict[str, bytes]:
    return _project_files_for_mms([(mm_id, voltage)])


def _project_files_for_mms(mms: list[tuple[str, float]]) -> dict[str, bytes]:
    rows = []
    for mm_id, nominal_voltage in mms:
        rows.extend(
            {
                "Time (s)": index,
                "Max_A": sample_voltage,
                "Max_B": sample_voltage - 2,
                "Max_C": sample_voltage - 4,
                "MM_name_A": mm_id,
                "MM_name_B": mm_id,
                "MM_name_C": mm_id,
                "Max_all": sample_voltage,
                "Case": "Case 1",
                "Run": 1,
                "Fault_type": "Test",
                "MM_name_all": mm_id,
            }
            for index, sample_voltage in ((0.0, 120.0), (0.02, 125.0), (0.04, 110.0))
        )
    mm = pd.DataFrame(
        [
            {
                "Group": mm_id,
                "Un": voltage,
                "Um": voltage * 1.1,
                "SDPF_LG": 70.0,
                "SDPF_LL": 70.0,
                "SIWL_LG": 100.0,
                "SIWL_LL": 100.0,
                "LIWL": 350.0,
            }
            for mm_id, voltage in mms
        ]
    )
    workbook = BytesIO()
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        mm.to_excel(writer, sheet_name="MM_blocks", index=False)
    return {
        "LGp.csv": pd.DataFrame(rows).to_csv(index=False).encode("utf-8"),
        "LLp.csv": pd.DataFrame(rows).to_csv(index=False).encode("utf-8"),
        "Input_Data_PSCAD_Python_v11.xlsx": workbook.getvalue(),
    }


def _project_zip(files: dict[str, bytes] | None = None) -> bytes:
    archive = BytesIO()
    with ZipFile(archive, "w", ZIP_DEFLATED) as project:
        for name, content in (files or _project_files()).items():
            project.writestr(f"Project/{name}", content)
    return archive.getvalue()


def _run_app_with_uploads(files: list[tuple[str, bytes, str]], timeout: float = 3) -> AppTest:
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    at = AppTest.from_file(str(app_path)).run(timeout=timeout)
    uploader = at.file_uploader(key="project_files")
    for filename, content, mime_type in files:
        uploader.upload(filename, content, mime_type)
    return at.run(timeout=timeout)


def _sa_selection_key(at: AppTest) -> str:
    return next(
        key for key in at.session_state
        if key.startswith("sa_limits_") and not key.endswith(("_options", "_all", "_clear", "_chips"))
    )


def _descendants(element):
    for child in getattr(element, "children", {}).values():
        yield child
        yield from _descendants(child)


def _assert_dashboard_controls(at: AppTest) -> None:
    assert not at.exception
    assert [tab.label for tab in at.tabs] == ["Summary", "All envelopes", "Data & references"]
    assert not {"Cases", "MM points"} & {tab.label for tab in at.tabs}
    segmented = {item.label: item for item in at.get("segmented_control")}
    assert set(segmented) == {"IC reference"}
    assert len(at.get("pills")) == 1
    voltage_pills = next(item for item in at.sidebar.get("pills") if item.label == "Voltage level")
    assert voltage_pills._is_single_select
    assert voltage_pills.proto.wrap is True
    assert not at.main.get("pills")
    assert [item.label for item in at.sidebar.get("pills")] == ["Voltage level"]
    assert at.session_state["selected_cases"] == ["Case 1"]
    assert at.session_state["selected_mms"] == ["MM_A"]
    assert at.session_state["selected_cases_options"] == ["Case 1"]
    assert at.session_state["selected_mms_options"] == ["MM_A"]
    assert [(item.label, item.value) for item in at.get("toggle")] == [("IC limits", True)]
    buttons = at.get("button")
    assert "All" in {item.label for item in buttons}
    button_keys = {item.key for item in buttons}
    assert {"selected_cases_all", "selected_cases_clear", "selected_mms_all", "selected_mms_clear"} <= button_keys
    assert not {"reload_project", "clear_project"} & {item.key for item in buttons}
    assert not at.get("checkbox")
    assert not at.get("text_input")
    assert {item.label for item in at.get("download_button")} == {
        "Download selected results (.xlsx)",
        "Download report charts (.zip)",
    }
    markdown = " ".join(item.value for item in at.markdown)
    assert "Cases (1/1)" in markdown
    assert "MM points (1/1)" in markdown


def test_empty_app_starts_with_upload_prompt_and_dashboard_tabs():
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    assert (app_path.parent / "assets" / "mpe_app_icon.png").is_file()
    at = AppTest.from_file(str(app_path)).run()

    assert not at.exception
    assert at.file_uploader(key="project_files").label == "Project files"
    assert not {"reload_project", "clear_project"} & {item.key for item in at.get("button")}
    assert len(at.get("image")) == 1
    assert not at.sidebar.get("pills")
    assert not at.sidebar.get("segmented_control")
    assert not at.sidebar.get("toggle")
    assert [tab.label for tab in at.tabs] == ["Summary", "All envelopes", "Data & references"]
    assert any("Upload project inputs in the sidebar" in item.value for item in at.info)
    assert not at.warning


def test_sa_template_is_not_built_during_data_reference_render(monkeypatch):
    import sa_data

    calls = []
    monkeypatch.setattr(sa_data, "create_blank_template", lambda: calls.append("built") or b"workbook")
    at = _run_app_with_uploads([("project.zip", _project_zip(), "application/zip")])
    at.session_state["primary_tabs"] = "Data & references"
    at.run()

    assert not at.exception
    assert calls == []
    assert any(item.key == "sa_template_download" for item in at.get("download_button"))


def test_data_references_does_not_mount_the_chart_width_sensor():
    at = _run_app_with_uploads([("project.zip", _project_zip(), "application/zip")])
    assert any(getattr(item, "key", None) == "voltage_envelopes_plot_width" for item in at.main.children.values())

    at.session_state["primary_tabs"] = "Data & references"
    at.run()

    assert not at.exception
    assert not any(getattr(item, "key", None) == "voltage_envelopes_plot_width" for item in at.main.children.values())


def test_source_derived_view_data_cache_reuses_and_invalidates_by_signature(monkeypatch):
    import app

    app.cached_selection_catalogs.clear()
    app.cached_reference_display_data.clear()
    catalog_calls = {"cases": 0, "mms": 0}
    ic_calls = []
    original_cases = app.available_cases
    original_mms = app.available_mms
    original_ic_values = app.ic_values

    def count_cases(lg, ll):
        catalog_calls["cases"] += 1
        return original_cases(lg, ll)

    def count_mms(lg, ll):
        catalog_calls["mms"] += 1
        return original_mms(lg, ll)

    def count_ic_values(row, measurement):
        ic_calls.append(measurement)
        return original_ic_values(row, measurement)

    monkeypatch.setattr(app, "available_cases", count_cases)
    monkeypatch.setattr(app, "available_mms", count_mms)
    monkeypatch.setattr(app, "ic_values", count_ic_values)

    lg_a = pd.DataFrame({"Case": ["Case A"], "MM_name_all": ["MM_A"]})
    ll_a = pd.DataFrame({"Case": ["Case A"], "MM_name_all": ["MM_A"]})
    assert app.cached_selection_catalogs(lg_a, ll_a, "source-a") == (["Case A"], ["MM_A"])
    assert app.cached_selection_catalogs(lg_a, ll_a, "source-a") == (["Case A"], ["MM_A"])
    assert catalog_calls == {"cases": 1, "mms": 1}
    lg_b = pd.DataFrame({"Case": ["Case B"], "MM_name_all": ["MM_B"]})
    ll_b = pd.DataFrame({"Case": ["Case B"], "MM_name_all": ["MM_B"]})
    assert app.cached_selection_catalogs(lg_b, ll_b, "source-b") == (["Case B"], ["MM_B"])
    assert catalog_calls == {"cases": 2, "mms": 2}

    mm_columns = {
        "Un": 66.0,
        "SDPF_LG": 70.0,
        "SDPF_LL": 70.0,
        "SIWL_LG": 100.0,
        "SIWL_LL": 100.0,
        "LIWL": 350.0,
    }
    project_a = app.ProjectData(mm_blocks=pd.DataFrame([{**mm_columns, "Group": "MM_A"}]))
    project_b = app.ProjectData(mm_blocks=pd.DataFrame([{**mm_columns, "Group": "MM_B"}]))
    first = app.cached_reference_display_data(project_a, "source-a")
    repeated = app.cached_reference_display_data(project_a, "source-a")
    updated = app.cached_reference_display_data(project_b, "source-b")

    assert first[1].equals(repeated[1])
    assert ic_calls == ["LG", "LL", "LG", "LL"]
    assert set(updated[1]["MM_ID"]) == {"MM_B"}
    app.cached_selection_catalogs.clear()
    app.cached_reference_display_data.clear()


def test_partial_upload_keeps_dashboard_controls_hidden_until_required_inputs_are_loaded():
    lg_csv = pd.DataFrame(
        {"Time (s)": [0.0], "Max_all": [100.0], "Case": ["Case 1"], "MM_name_all": ["MM_A"]}
    ).to_csv(index=False).encode("utf-8")
    at = _run_app_with_uploads([("LGp.csv", lg_csv, "text/csv")])

    assert not at.exception
    assert not at.sidebar.get("pills")
    assert not at.sidebar.get("segmented_control")
    assert not at.sidebar.get("toggle")
    assert any("Upload or select LGp.csv, LLp.csv and the PSCAD input workbook." in item.value for item in at.warning)


def test_plot_width_component_uses_the_declared_state_setter():
    app_source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")

    assert "const { data, parentElement, setStateValue } = component" in app_source
    assert 'setStateValue("width", width)' in app_source


def test_selection_chip_component_uses_the_declared_trigger_setter():
    app_source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")

    assert "const { data, parentElement, setTriggerValue } = component" in app_source
    assert 'setTriggerValue("clicked", {' in app_source


def test_measured_plot_width_reaches_the_summary_figures():
    at = _run_app_with_uploads([("project.zip", _project_zip(), "application/zip")])
    at.session_state["voltage_envelopes_plot_width"] = {"width": 1212}
    at.run()

    assert not at.exception
    figures = [json.loads(chart.proto.spec) for chart in at.get("plotly_chart")]
    assert len(figures) == 2
    for chart, figure in zip(at.get("plotly_chart"), figures):
        assert figure["layout"]["width"] == 1212
        assert figure["layout"]["legend"]["entrywidthmode"] == "pixels"
        maximum = next(trace for trace in figure["data"] if trace["name"] == "Maximum envelope")
        assert maximum["showlegend"] is True
        assert maximum["legend"] == "legend"
        assert figure["layout"]["legend"]["y"] == -48 / 460
        assert json.loads(chart.proto.config)["modeBarButtonsToRemove"] == ["toImage"]


def test_05_project_zip_renders_current_summary_and_all_views():
    test_data = Path(__file__).resolve().parents[2] / "05_Test_data"
    files = {
        path.name: path.read_bytes()
        for path in test_data.iterdir()
        if path.is_file() and path.suffix.casefold() in {".csv", ".xlsx"}
    }
    at = _run_app_with_uploads([("project.zip", _project_zip(files), "application/zip")], timeout=30)

    assert not at.exception
    assert len(at.get("plotly_chart")) == 2
    assert at.session_state["voltage_level"] == 33.0
    assert not any(item.label == "SA limits" for item in at.get("toggle"))
    assert not any(item.label == "SA limits to apply" for item in at.sidebar.get("pills"))
    assert not any("could not be used" in item.value for item in at.sidebar.get("caption"))
    summary_figures = [json.loads(item.proto.spec) for item in at.get("plotly_chart")]
    assert not any(trace.get("name", "").endswith(" SA") for figure in summary_figures for trace in figure["data"])
    voltage_pills = next(item for item in at.sidebar.get("pills") if item.label == "Voltage level")
    assert voltage_pills.options == ["33 kV", "66 kV", "230 kV", "380 kV"]
    assert voltage_pills.proto.wrap is True
    assert not any("Resolve the blocking LG/LL" in item.value for item in at.info)

    at.session_state["voltage_level"] = 66.0
    at.session_state["primary_tabs"] = "All envelopes"
    at.run(timeout=30)

    assert not at.exception
    assert len(at.get("plotly_chart")) == 2
    assert any(item.label == "SA limits" for item in at.get("toggle"))
    assert any(table.key and table.key.startswith("limit_exceedances_") for table in at.get("dataframe"))
    detailed_figures = [json.loads(item.proto.spec) for item in at.get("plotly_chart")]
    assert any(trace.get("name") == "66 WTT SA" for trace in detailed_figures[0]["data"])
    assert not any(trace.get("name") == "66 WTT SA" for trace in detailed_figures[1]["data"])


def test_sidebar_controls_and_all_envelopes_exceedance_table_with_zip_upload():
    at = _run_app_with_uploads([("project.zip", _project_zip(), "application/zip")])

    _assert_dashboard_controls(at)

    at.session_state["primary_tabs"] = "All envelopes"
    at.run()
    assert not at.exception
    envelope_controls = next(item for item in at.get("expander") if item.label == "Envelope controls")
    assert len(envelope_controls.children) == 2
    assert not any("Advanced chart axis" in item.label for item in at.get("expander"))
    assert not at.get("checkbox") and not at.get("number_input")
    channel_pills = next(item for item in at.sidebar.get("pills") if item.label == "Envelope channel")
    assert channel_pills.options == ["Max_all", "Max_A", "Max_B", "Max_C"]
    assert channel_pills._is_single_select and channel_pills.proto.wrap is True
    assert channel_pills.value == "Max_all"
    assert {item.label for item in at.sidebar.get("segmented_control")} == {"IC reference"}
    tables = at.get("dataframe")
    sfo_table = next(table for table in tables if table.key and "limit_exceedances_sfo_" in table.key)
    tov_table = next(table for table in tables if table.key and "limit_exceedances_tov_" in table.key)
    for table in (sfo_table, tov_table):
        assert list(table.value["Measurement"]) == ["LG", "LL"]
        assert "Runs with exceedance" in table.value.columns
        assert "Ranked samples above reference" not in table.value.columns
        assert set(table.value["Runs with exceedance"]) == {"1 (Test)"}
        assert table.value["Peak excess (kV)"].iloc[0] > 0
    assert sfo_table.value["Over-limit area (kV·ranked-index s)"].eq(0).all()
    assert tov_table.value["Over-limit area (kV·ranked-index s)"].gt(0).all()
    all_tab = next(tab for tab in at.tabs if tab.label == "All envelopes")
    tab_children = list(all_tab.children.values())
    table_position = next(index for index, child in enumerate(tab_children) if type(child).__name__ == "Dataframe")
    plot_positions = [index for index, child in enumerate(tab_children) if type(child).__name__ == "UnknownElement"]
    assert len(plot_positions) == 2 and max(plot_positions) < table_position
    assert {item.label for item in at.get("download_button")} == {
        "Download selected results (.xlsx)",
        "Download report charts (.zip)",
    }

    at.session_state[sfo_table.key] = {"selection": {"rows": [0], "columns": [], "cells": []}}
    at.run()
    selected_figure = json.loads(at.get("plotly_chart")[0].proto.spec)
    selected_curve = next(trace for trace in selected_figure["data"] if trace["name"] == "Case 1 · MM_A")
    assert selected_curve["line"]["width"] == 3.6

    at.session_state["primary_tabs"] = "Data & references"
    at.run()
    assert not at.exception
    button_keys = {item.key for item in at.get("button")}
    assert not {"selected_cases_all", "selected_cases_clear", "selected_mms_all", "selected_mms_clear"} & button_keys
    assert at.session_state["selected_cases"] == ["Case 1"]
    assert at.session_state["selected_mms"] == ["MM_A"]
    visible_text = " ".join(item.value for item in at.markdown)
    assert "synthetic example" not in visible_text.casefold()
    assert "local server folder" not in visible_text.casefold()


def test_envelope_channel_uses_wrapping_single_select_pills():
    at = _run_app_with_uploads([("project.zip", _project_zip(), "application/zip")])
    at.session_state["primary_tabs"] = "All envelopes"
    at.run()

    channel_pills = next(item for item in at.sidebar.get("pills") if item.label == "Envelope channel")
    assert channel_pills._is_single_select
    assert channel_pills.proto.wrap is True
    assert channel_pills.options == ["Max_all", "Max_A", "Max_B", "Max_C"]
    assert channel_pills.value == "Max_all"

    at.session_state["detail_channel"] = "Max_B"
    at.run()
    assert not at.exception
    assert at.session_state["detail_channel"] == "Max_B"


def test_sidebar_accepts_individual_csv_and_xlsx_uploads():
    files = _project_files()
    at = _run_app_with_uploads([
        ("LGp.csv", files["LGp.csv"], "text/csv"),
        ("LLp.csv", files["LLp.csv"], "text/csv"),
        ("Input_Data_PSCAD_Python_v11.xlsx", files["Input_Data_PSCAD_Python_v11.xlsx"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ])

    _assert_dashboard_controls(at)
    assert not any("No supported project inputs" in item.value for item in at.warning)


def test_voltage_and_ic_choices_use_sidebar_defaults():
    at = _run_app_with_uploads([("project.zip", _project_zip(), "application/zip")])

    assert at.session_state["voltage_level"] == 66.0
    assert at.session_state["ic_reference_choice"] == "Safety margin"
    voltage_pills = next(item for item in at.sidebar.get("pills") if item.label == "Voltage level")
    assert voltage_pills.options == ["66 kV"]
    assert voltage_pills.value == 66.0
    ic_control = next(item for item in at.get("segmented_control") if item.label == "IC reference")
    assert ic_control.options == ["Safety margin", "Withstand"]
    assert {item.label for item in at.sidebar.get("segmented_control")} == {"IC reference"}


def test_mapped_sa_limits_default_on_in_sidebar_and_summary():
    mm_id = "MM_230_ONS1"
    files = _project_files(mm_id, 230.0)
    sa_path = Path(__file__).resolve().parents[2] / "04_Test_data" / "SA.xlsx"
    files["SA.xlsx"] = sa_path.read_bytes()
    at = _run_app_with_uploads([("project.zip", _project_zip(files), "application/zip")])

    assert not at.exception
    assert len(at.get("pills")) == 1
    assert not at.main.get("pills")
    assert [item.label for item in at.sidebar.get("pills")] == ["Voltage level"]
    sa_key = _sa_selection_key(at)
    assert at.session_state[sa_key] == ["230 OnS SA"]
    buttons = {item.key: item.label for item in at.get("button")}
    assert buttons[f"{sa_key}_all"] == "All"
    assert buttons[f"{sa_key}_clear"] == "Clear"
    summary_figures = [json.loads(item.proto.spec) for item in at.get("plotly_chart")]
    assert {trace["name"] for trace in summary_figures[0]["data"] if trace.get("name", "").endswith(" SA")} == {
        "230 OnS SA"
    }
    assert not any(trace.get("name", "").endswith(" SA") for trace in summary_figures[1]["data"])


def test_sa_choices_are_filtered_by_voltage():
    files = _project_files("MM_66_OFT1", 66.0)
    sa_path = Path(__file__).resolve().parents[2] / "04_Test_data" / "SA.xlsx"
    files["SA.xlsx"] = sa_path.read_bytes()
    at = _run_app_with_uploads([("project.zip", _project_zip(files), "application/zip")])

    assert not at.exception
    assert not any(item.label == "SA limits" for item in at.get("toggle"))
    assert not any(item.label == "SA limits to apply" for item in at.sidebar.get("pills"))
    assert not any("could not be used" in item.value for item in at.sidebar.get("caption"))
    summary_figures = [json.loads(item.proto.spec) for item in at.get("plotly_chart")]
    assert not any(trace.get("name", "").endswith(" SA") for figure in summary_figures for trace in figure["data"])


def test_sa_choices_default_from_selected_mm_and_allow_same_voltage_alternatives():
    files = _project_files_for_mms(
        [("MM_230_ONS1", 230.0), ("MM_230_OSS1", 230.0), ("MM_66_OFT1", 66.0)]
    )
    sa_path = Path(__file__).resolve().parents[2] / "04_Test_data" / "SA.xlsx"
    files["SA.xlsx"] = sa_path.read_bytes()
    at = _run_app_with_uploads([("project.zip", _project_zip(files), "application/zip")])
    at.session_state["voltage_level"] = 230.0
    at.run()

    sa_key = _sa_selection_key(at)
    assert set(at.session_state[f"{sa_key}_options"]) == {"230 OnS SA", "230 OSS SA"}
    at.session_state["selected_mms"] = ["MM_230_ONS1"]
    at.run()
    assert at.session_state[sa_key] == ["230 OnS SA"]
    assert set(at.session_state[f"{sa_key}_options"]) == {"230 OnS SA", "230 OSS SA"}

    at.session_state[sa_key] = ["230 OnS SA", "230 OSS SA"]
    at.run()
    summary_figures = [json.loads(item.proto.spec) for item in at.get("plotly_chart")]
    assert {trace["name"] for trace in summary_figures[0]["data"] if trace.get("name", "").endswith(" SA")} == {
        "230 OnS SA",
        "230 OSS SA",
    }

    at.session_state["selected_mms"] = ["MM_230_OSS1"]
    at.run()
    assert at.session_state[sa_key] == ["230 OSS SA"]

    at.session_state["voltage_level"] = 66.0
    at.run()
    assert not any(item.label == "SA limits to apply" for item in at.sidebar.get("pills"))
    summary_figures = [json.loads(item.proto.spec) for item in at.get("plotly_chart")]
    assert not any(trace.get("name", "").endswith(" SA") for figure in summary_figures for trace in figure["data"])


def test_sa_violation_table_is_deferred_without_exposure_time():
    files = _project_files("MM_230_ONS1", 230.0)
    sa_path = Path(__file__).resolve().parents[2] / "04_Test_data" / "SA.xlsx"
    files["SA.xlsx"] = sa_path.read_bytes()
    at = _run_app_with_uploads([("project.zip", _project_zip(files), "application/zip")])
    at.session_state["primary_tabs"] = "All envelopes"
    at.run()

    assert not at.exception
    tables = [table for table in at.get("dataframe") if table.key and table.key.startswith("limit_exceedances_")]
    assert {table.key.split("_")[2] for table in tables} == {"sfo", "tov"}
    lg_figure = json.loads(at.get("plotly_chart")[0].proto.spec)
    assert any(trace.get("name", "").endswith(" SA") for trace in lg_figure["data"])


def test_case_selection_clear_and_all_buttons_update_inline_count():
    at = _run_app_with_uploads([("project.zip", _project_zip(), "application/zip")])

    at.button(key="selected_cases_clear").click().run()
    assert "Cases (0/1)" in " ".join(item.value for item in at.markdown)
    at.button(key="selected_cases_all").click().run()
    assert "Cases (1/1)" in " ".join(item.value for item in at.markdown)


def test_ctrl_click_case_or_mm_chip_selects_only_the_clicked_value():
    for options, clicked in ((["Case 1", "Case 2", "Case 3"], "Case 2"), (["MM_A", "MM_B"], "MM_B")):
        assert selection_after_click(options, options, clicked, exclusive=True) == [clicked]


def test_limit_visibility_toggles_apply_to_summary_and_all_envelopes():
    files = _project_files("MM_230_ONS1", 230.0)
    sa_path = Path(__file__).resolve().parents[2] / "04_Test_data" / "SA.xlsx"
    files["SA.xlsx"] = sa_path.read_bytes()
    at = _run_app_with_uploads([("project.zip", _project_zip(files), "application/zip")])

    assert not at.exception
    assert [(item.label, item.value) for item in at.get("toggle")] == [
        ("IC limits", True),
        ("SA limits", True),
    ]
    figures = [json.loads(item.proto.spec) for item in at.get("plotly_chart")]
    assert any(trace["name"].startswith("IC ") for trace in figures[0]["data"])
    assert any(trace["name"].endswith(" SA") for trace in figures[0]["data"])
    assert not any(trace["name"].endswith(" SA") for trace in figures[1]["data"])

    at.toggle(key="show_ic_limits").set_value(False).run()
    figures = [json.loads(item.proto.spec) for item in at.get("plotly_chart")]
    assert all(not any(trace["name"].startswith("IC ") for trace in figure["data"]) for figure in figures)
    assert any(trace["name"].endswith(" SA") for trace in figures[0]["data"])

    at.toggle(key="show_sa_limits").set_value(False).run()
    figures = [json.loads(item.proto.spec) for item in at.get("plotly_chart")]
    assert all(not any(trace["name"].endswith(" SA") for trace in figure["data"]) for figure in figures)

    at.session_state["show_ic_limits"] = True
    at.session_state["primary_tabs"] = "All envelopes"
    at.run()
    figures = [json.loads(item.proto.spec) for item in at.get("plotly_chart")]
    assert any(trace["name"].startswith("IC ") for trace in figures[0]["data"])
    assert not any(trace["name"].endswith(" SA") for trace in figures[0]["data"])


def test_05_sa_workbook_is_accepted_and_plotted_through_exact_mm_assignment():
    files = _project_files("MM_66_WTG01", 66.0)
    sa_path = Path(__file__).resolve().parents[2] / "05_Test_data" / "SA.xlsx"
    files["SA.xlsx"] = sa_path.read_bytes()
    at = _run_app_with_uploads([("project.zip", _project_zip(files), "application/zip")])

    assert not at.exception
    assert not any("could not be read" in item.value for item in at.caption)
    assert any(item.label == "SA limits" for item in at.get("toggle"))
    sa_key = _sa_selection_key(at)
    assert at.session_state[sa_key] == ["66 WTT SA"]
    assert at.session_state[f"{sa_key}_options"] == ["66 WTT SA"]
    sidebar_keys = {item.key for item in _descendants(at.sidebar) if getattr(item, "key", None)}
    main_keys = {item.key for item in _descendants(at.main) if getattr(item, "key", None)}
    assert f"{sa_key}_chips" in sidebar_keys
    assert f"{sa_key}_chips" not in main_keys
    summary_figures = [json.loads(item.proto.spec) for item in at.get("plotly_chart")]
    assert any(trace.get("name") == "66 WTT SA" for trace in summary_figures[0]["data"])
    assert not any(trace.get("name") == "66 WTT SA" for trace in summary_figures[1]["data"])

    at.session_state["primary_tabs"] = "Data & references"
    at.run()
    expander_labels = {item.label for item in at.get("expander")}
    assert "SA workbook template" in expander_labels
    assignment_expander = next(item for item in at.get("expander") if item.label == "MM assignments")
    assert assignment_expander.proto.expanded is False
    assignments = assignment_expander.get("dataframe")[0].value
    assert {"MM_ID", "SA_ID"} <= set(assignments.columns)
    assert ((assignments["MM_ID"] == "MM_66_WTG01") & (assignments["SA_ID"] == "66 WTT SA")).any()
    assert not any("legacy" in label.casefold() for label in expander_labels)
    assert any(item.label == "Download SA template" for item in at.get("download_button"))
