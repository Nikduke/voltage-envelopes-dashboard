"""Streamlit entry point for the local voltage-envelope dashboard."""

from __future__ import annotations

from pathlib import Path
import time

import numpy as np
import pandas as pd
import streamlit as st

from analysis import (
    available_cases,
    available_mms,
    closest_reference_crossing,
    crossing_summary,
    curve_summary,
    mms_at_voltage,
    nominal_voltages,
    select_curves,
    summary_envelope,
)
from data_loader import ProjectData, SourceCandidate, discover_sources, load_project_data, source_signature
from exports import export_xlsx_bytes, figure_image_bytes, selected_csv_bytes
from limits import CHANGEOVER_S, SAFETY_FACTOR, ic_values
from plots import build_envelope_figure
from sa_data import convert_legacy_to_new, create_blank_template, create_synthetic_example
from validation import validation_frame


APP_ROOT = Path(__file__).resolve().parent
DEFAULT_SOURCE = APP_ROOT.parent / "02_Excel_Example"
st.set_page_config(page_title="Voltage Envelopes", page_icon="⚡", layout="wide", initial_sidebar_state="expanded")


@st.cache_data(max_entries=3, show_spinner=False)
def cached_project_load(_selected: dict[str, SourceCandidate | None], signature: str) -> ProjectData:
    return load_project_data(_selected)


def _discover_uploads(files) -> list[tuple[str, bytes]]:
    return [(file.name, file.getvalue()) for file in (files or [])]


def _selection(
    label: str,
    options: list[str],
    key: str,
    default_first: bool = False,
) -> list[str]:
    previous = st.session_state.get(key, [])
    if not isinstance(previous, list):
        previous = []
    valid = [value for value in previous if value in options]
    if key not in st.session_state:
        valid = options[:1] if default_first else []
        st.session_state[key] = valid
    elif valid != previous:
        st.session_state[key] = valid
    button_cols = st.columns([1, 1, 5])
    if button_cols[0].button("All", key=f"{key}_all", use_container_width=True):
        st.session_state[key] = list(options)
    if button_cols[1].button("Clear", key=f"{key}_clear", use_container_width=True):
        st.session_state[key] = []
    selection = st.multiselect(label, options, key=key, placeholder="Search and select…")
    button_cols[2].caption(f"{len(selection)} of {len(options)} selected")
    return selection


def _valid_selectbox(label: str, options: list, key: str, format_func=None):
    if not options:
        st.caption(f"{label}: no available values")
        return None
    current = st.session_state.get(key)
    if current not in options:
        st.session_state[key] = options[0]
    return st.selectbox(label, options, key=key, format_func=format_func)


def _index_range(frames: list[pd.DataFrame], key: str) -> tuple[float, float] | None:
    available = [frame["Time (s)"] for frame in frames if not frame.empty and "Time (s)" in frame]
    if not available:
        return None
    values = pd.concat(available, ignore_index=True).dropna()
    if values.empty:
        return None
    low, high = float(values.min()), float(values.max())
    if np.isclose(low, high):
        return low, high
    previous = st.session_state.get(key)
    if not isinstance(previous, tuple) or len(previous) != 2 or previous[0] < low or previous[1] > high:
        st.session_state[key] = (low, high)
    options = np.sort(values.unique()).astype(float).tolist()
    previous = st.session_state.get(key)
    if not isinstance(previous, tuple) or len(previous) != 2 or previous[0] not in options or previous[1] not in options:
        st.session_state[key] = (options[0], options[-1])
    return st.select_slider(
        "Representative-envelope index range (s)",
        options=options,
        key=key,
        format_func=lambda value: f"{value:.3f}",
    )


def _source_selector(role: str, label: str, candidates: list[SourceCandidate]) -> SourceCandidate | None:
    if not candidates:
        st.caption(f"{label}: not found")
        return None
    if len(candidates) == 1:
        st.caption(f"{label}: {candidates[0].label}")
        return candidates[0]
    labels = [candidate.label for candidate in candidates]
    options = ["Select a file…", *labels]
    key = f"source_{role}"
    if st.session_state.get(key) not in options:
        st.session_state[key] = options[0]
    choice = st.selectbox(f"{label} — choose source", options, key=key)
    return candidates[labels.index(choice)] if choice in labels else None


def _issue_summary(issues: list[dict[str, object]]) -> None:
    frame = validation_frame(issues)
    if frame.empty:
        st.success("No validation findings for the loaded sources.")
        return
    blocking = frame.loc[frame["Blocking"] == True]
    warnings = frame.loc[frame["Severity"].isin(["Warning", "Error"]) & (frame["Blocking"] != True)]
    notes = frame.loc[frame["Severity"].isin(["Note", "Info"])]
    st.markdown("#### Data validation")
    if not blocking.empty:
        st.error(f"{len(blocking)} blocking issue(s). Affected source curves are not plotted.")
        with st.expander("Blocking issues", expanded=True):
            st.dataframe(blocking, hide_index=True, width="stretch")
    else:
        st.success("No blocking result-file structure errors.")
    if not warnings.empty:
        with st.expander(f"Warnings and non-blocking errors ({len(warnings)})"):
            st.dataframe(warnings, hide_index=True, width="stretch")
    if not notes.empty:
        with st.expander(f"Coverage and interpretation notes ({len(notes)})"):
            st.dataframe(notes, hide_index=True, width="stretch")
    st.download_button(
        "Download validation details (CSV)",
        frame.to_csv(index=False).encode("utf-8-sig"),
        file_name="voltage_envelope_validation.csv",
        mime="text/csv",
        key="validation_download",
    )


def _source_panel() -> tuple[ProjectData, dict[str, SourceCandidate | None], str]:
    st.sidebar.header("Project sources")
    source_text = st.sidebar.text_input("Source folder", value=str(DEFAULT_SOURCE), key="source_folder")
    uploaded = st.sidebar.file_uploader(
        "Optional session-only files",
        type=["csv", "xlsx", "xlsm"],
        accept_multiple_files=True,
        help="Uploads stay in this Streamlit session and are never written to the source folder.",
    )
    scan_started = time.perf_counter()
    candidates = discover_sources(source_text, _discover_uploads(uploaded))
    scan_seconds = time.perf_counter() - scan_started
    labels = {"lg": "LG results CSV", "ll": "LL results CSV", "mm": "MM_blocks workbook", "sa": "SA workbook", "wl": "Legacy WL reference", "dashboard": "Excel dashboard reference"}
    selected = {role: _source_selector(role, labels[role], candidates[role]) for role in candidates}
    if st.sidebar.button("Reload selected files", type="primary", use_container_width=True):
        st.cache_data.clear()
        st.session_state["reload_at"] = time.time()
    signature = source_signature(selected, source_text) + f"|reload={st.session_state.get('reload_at', 0)}"
    try:
        with st.spinner("Loading and validating source files…"):
            project = cached_project_load(selected, signature)
    except Exception as exc:
        project = ProjectData(issues=[{"Severity": "Error", "Area": "Source loading", "Code": "load_error", "Message": str(exc), "Identifier": "", "Blocking": True}])
    st.sidebar.caption("Detected source candidates: " + ", ".join(f"{role.upper()} {len(values)}" for role, values in candidates.items()))
    st.session_state["source_scan_seconds"] = scan_seconds
    return project, selected, signature


def _y_axis_controls(data_frames: list[pd.DataFrame], key: str) -> tuple[float, float] | None:
    values = [frame["Voltage_kV_peak"] for frame in data_frames if not frame.empty and "Voltage_kV_peak" in frame]
    if not values:
        return None
    combined = pd.concat(values, ignore_index=True).dropna()
    if combined.empty:
        return None
    low_data, high_data = float(combined.min()), float(combined.max())
    enable = st.checkbox("Set manual voltage bounds", key=f"{key}_manual_toggle")
    if not enable:
        return None
    low, high = st.columns(2)
    low_bound = low.number_input("Y minimum (kV)", value=float(max(0, low_data * 0.9)), key=f"{key}_ymin")
    high_bound = high.number_input("Y maximum (kV)", value=float(high_data * 1.05), key=f"{key}_ymax")
    if low_bound >= high_bound:
        st.warning("Y-axis minimum must be below the maximum; automatic bounds are in use.")
        return None
    if low_bound > low_data or high_bound < high_data:
        st.warning(f"Manual bounds clip selected envelope data ({low_data:.2f}–{high_data:.2f} kV peak).")
    return float(low_bound), float(high_bound)


def _legacy_assignments(sa_data, mm_blocks: pd.DataFrame | None) -> tuple[dict[str, list[str]], dict[str, dict[str, str]]]:
    elements = sorted(sa_data.legacy["Element"].dropna().astype(str).unique()) if sa_data and sa_data.kind == "legacy" else []
    mm_ids = mm_blocks["Group"].dropna().astype(str).tolist() if mm_blocks is not None and "Group" in mm_blocks else []
    overlay: dict[str, list[str]] = {}
    mapping: dict[str, dict[str, str]] = {}
    for index, element in enumerate(elements):
        mm_key = f"legacy_mm_{index}"
        status_key = f"legacy_status_{index}"
        if mm_key not in st.session_state:
            st.session_state[mm_key] = "Unassigned"
        if status_key not in st.session_state:
            st.session_state[status_key] = "Unknown"
        mm_id = st.session_state.get(mm_key)
        status = st.session_state.get(status_key, "Unknown")
        if mm_id in mm_ids:
            sa_id = sa_data.types.loc[sa_data.types["Model"].astype(str).eq(element), "SA_ID"].iloc[0]
            overlay.setdefault(str(mm_id), []).append(str(sa_id))
            mapping[element] = {"MM_ID": str(mm_id), "Installation_Status": str(status)}
    return overlay, mapping


def _sa_for_new(sa_data, selected_mms: list[str]) -> tuple[dict[str, list[str]], bool]:
    by_mm: dict[str, list[str]] = {}
    if sa_data is None or sa_data.kind != "new":
        return by_mm, False
    type_lookup = sa_data.types.drop_duplicates("SA_ID").set_index("SA_ID", drop=False)
    installed = sa_data.assignments.loc[
        sa_data.assignments["MM_ID"].astype(str).isin(set(selected_mms))
        & sa_data.assignments["Installation_Status"].astype(str).eq("Installed")
    ]
    for _, assignment in installed.iterrows():
        sa_id = str(assignment["SA_ID"])
        if sa_id in type_lookup.index:
            row = type_lookup.loc[sa_id]
            if str(row.get("Curve_Type", "")) == "TOV_withstand" and str(row.get("Voltage_Basis", "")).casefold() == "kv_peak":
                by_mm.setdefault(str(assignment["MM_ID"]), []).append(sa_id)
    return by_mm, bool(by_mm)


def _sa_controls(project: ProjectData, selected_mms: list[str], key: str) -> tuple[dict[str, list[str]], bool]:
    sa = project.sa
    if sa is None or sa.kind not in {"new", "legacy"}:
        return {}, False
    if sa.kind == "new":
        by_mm, has_default = _sa_for_new(sa, selected_mms)
        possible = sorted(sa.types.loc[sa.types["Curve_Type"].astype(str).eq("TOV_withstand"), "SA_ID"].astype(str).unique())
        alternatives = _selection("Alternative SA types (comparison only)", possible, f"{key}_sa_alternatives") if possible else []
        for mm_id in selected_mms:
            for sa_id in alternatives:
                if sa_id not in by_mm.setdefault(mm_id, []):
                    by_mm[mm_id].append(sa_id)
    else:
        by_mm, _ = _legacy_assignments(sa, project.mm_blocks)
        has_default = bool(by_mm)
    include_unknown = st.checkbox(
        "Include SA comparisons with unknown voltage basis (raw values; no conversion)",
        value=False,
        key=f"{key}_unknown_sa",
        help="Such lines remain comparison-only and cannot be interpreted as kV peak unless their source basis is verified.",
    )
    show = st.checkbox("Show assigned/selected SA comparisons on LG", value=has_default, key=f"{key}_show_sa")
    return (by_mm if show else {}), include_unknown


def _downloads(
    figures: dict[str, object],
    plotted: pd.DataFrame,
    summary: pd.DataFrame,
    references: pd.DataFrame,
    issues: list[dict[str, object]],
    metadata: dict[str, object],
    prefix: str,
) -> None:
    st.markdown("#### Exports")
    st.session_state[f"{prefix}_payload_bytes"] = sum(len(figure.to_json().encode("utf-8")) for figure in figures.values() if figure is not None)
    csv_data = selected_csv_bytes(plotted, metadata)
    xlsx_data = export_xlsx_bytes(plotted, summary, references, validation_frame(issues), metadata)
    cols = st.columns([1, 1, 1, 1, 1])
    cols[0].download_button("Selected data CSV", csv_data, f"{prefix}_selected_data.csv", "text/csv", key=f"{prefix}_csv")
    cols[1].download_button("Workbook XLSX", xlsx_data, f"{prefix}_export.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"{prefix}_xlsx")
    for index, measurement in enumerate(("LG", "LL"), start=2):
        figure = figures.get(measurement)
        if figure is None:
            continue
        cols[index].download_button(
            f"{measurement} PNG",
            lambda chart=figure: figure_image_bytes(chart, "png"),
            f"{prefix}_{measurement.lower()}.png",
            "image/png",
            key=f"{prefix}_{measurement.lower()}_png",
        )
    with st.expander("Vector chart exports (SVG)"):
        for measurement, figure in figures.items():
            if figure is not None:
                st.download_button(
                    f"{measurement} SVG",
                    lambda chart=figure: figure_image_bytes(chart, "svg"),
                    f"{prefix}_{measurement.lower()}.svg",
                    "image/svg+xml",
                    key=f"{prefix}_{measurement.lower()}_svg",
                )


def _view_controls(project: ProjectData, prefix: str, data_frames: list[pd.DataFrame]) -> tuple[list[str], list[str], float, tuple[float, float] | None, str]:
    cases_available = sorted(set().union(*(set(frame["Case"].dropna().astype(str)) for frame in data_frames if not frame.empty))) if any(not frame.empty for frame in data_frames) else []
    mms_available = sorted(set().union(*(set(frame["MM_name_all"].dropna().astype(str)) for frame in data_frames if not frame.empty))) if any(not frame.empty for frame in data_frames) else []
    voltages = nominal_voltages(project.mm_blocks, mms_available)
    voltage = _valid_selectbox("Nominal voltage (kV)", voltages, f"{prefix}_voltage", format_func=lambda value: f"{value:g} kV")
    mms_at_v = mms_at_voltage(project.mm_blocks, mms_available, voltage)
    cases = _selection("Cases", cases_available, f"{prefix}_cases", default_first=True)
    mms = _selection("MM points / busbars", mms_at_v, f"{prefix}_mms", default_first=True)
    index = _index_range(data_frames, f"{prefix}_index_grid")
    channel = st.segmented_control("Envelope channel", ["Max_all", "Max_A", "Max_B", "Max_C"], default="Max_all", key=f"{prefix}_channel")
    return cases, mms, float(voltage) if voltage is not None else float("nan"), index, channel or "Max_all"


def _render_detailed(project: ProjectData, signature: str) -> None:
    st.subheader("Detailed comparison")
    source_frames = [frame for frame in (project.lg, project.ll) if frame is not None and not frame.empty]
    cases, mms, voltage, index, channel = _view_controls(project, "detail", source_frames)
    reference = st.selectbox("IC reference", ["Withstand", "Safety margin"], key="detail_reference")
    show_ic = st.checkbox("Show IC reference", value=True, key="detail_show_ic")
    sa_by_mm, unknown_sa = _sa_controls(project, mms, "detail")
    manual_y = _y_axis_controls(
        [select_curves(frame, cases, mms, index, channel) for frame in (project.lg, project.ll)], "detail"
    )
    chosen = {
        "LG": select_curves(project.lg, cases, mms, index, channel),
        "LL": select_curves(project.ll, cases, mms, index, channel),
    }
    figures = {}
    plotted = []
    for measurement in ("LG", "LL"):
        selected = chosen[measurement]
        if not selected.empty:
            selected = selected.assign(Measurement=measurement)
            plotted.append(selected)
        figure = build_envelope_figure(
            chosen[measurement], measurement, channel, "detailed", project.mm_blocks,
            reference, show_ic, project.sa, sa_by_mm if measurement == "LG" else {},
            unknown_sa if measurement == "LG" else False, manual_y,
            f"{signature}|detail|{measurement}|{','.join(cases)}|{','.join(mms)}|{channel}",
            reference_mms=mms,
            envelope_source=project.source_names.get(measurement.casefold(), ""),
            mm_source=project.source_names.get("mm", ""),
            sa_source=project.source_names.get("sa", ""),
        )
        figures[measurement] = figure
        st.plotly_chart(figure, width="stretch", config={"displaylogo": False}, alt=f"{measurement} representative voltage envelope and selected reference comparisons")
        summary = curve_summary(chosen[measurement], channel)
        with st.expander(f"{measurement} selected curves ({len(summary)})"):
            st.dataframe(summary, hide_index=True, width="stretch")
    reference_rows = pd.concat(
        [crossing_summary(chosen[m], project.mm_blocks, m, reference, channel) for m in ("LG", "LL")],
        ignore_index=True,
    )
    if not reference_rows.empty:
        st.caption("Reference comparison counts are numerical ranked-index samples above a selected reference. They do not establish a physical-duration violation or compliance result.")
        with st.expander("Selected-curve reference comparison"):
            st.dataframe(reference_rows, hide_index=True, width="stretch")
    plot_data = pd.concat(plotted, ignore_index=True) if plotted else pd.DataFrame()
    metadata = {
        "View": "Detailed",
        "Cases": cases,
        "MM points": mms,
        "Nominal voltage (kV)": voltage,
        "Channel": channel,
        "Index range (ranked index s)": index,
        "IC reference": reference if show_ic else "Hidden",
        "IC changeover (s)": CHANGEOVER_S,
        "Safety factor": SAFETY_FACTOR,
        "LG source": project.source_names.get("lg", ""),
        "LL source": project.source_names.get("ll", ""),
        "MM workbook": project.source_names.get("mm", ""),
        "SA workbook": project.source_names.get("sa", ""),
        "Assessment status": "Ranked-index comparison only; not chronological TOV/compliance assessment",
    }
    _downloads(figures, plot_data, pd.concat([curve_summary(chosen[m], channel).assign(Measurement=m) for m in ("LG", "LL")], ignore_index=True), reference_rows, project.issues, metadata, "voltage_detailed")


def _render_summary(project: ProjectData, signature: str) -> None:
    st.subheader("Overall summary")
    source_frames = [frame for frame in (project.lg, project.ll) if frame is not None and not frame.empty]
    cases, mms, voltage, index, channel = _view_controls(project, "summary", source_frames)
    reference = st.selectbox("IC reference", ["Withstand", "Safety margin"], key="summary_reference")
    show_ic = st.checkbox("Show IC reference", value=True, key="summary_show_ic")
    sa_by_mm, unknown_sa = _sa_controls(project, mms, "summary")
    chosen = {
        measurement: select_curves(frame, cases, mms, index, channel)
        for measurement, frame in (("LG", project.lg), ("LL", project.ll))
    }
    maxima = {measurement: summary_envelope(frame, channel) for measurement, frame in chosen.items()}
    manual_y = _y_axis_controls(list(maxima.values()), "summary")
    figures = {}
    plotted = []
    for measurement in ("LG", "LL"):
        data = maxima[measurement]
        if not data.empty:
            data = data.assign(Measurement=measurement)
            plotted.append(data)
        figure = build_envelope_figure(
            maxima[measurement], measurement, channel, "summary", project.mm_blocks,
            reference, show_ic, project.sa, sa_by_mm if measurement == "LG" else {},
            unknown_sa if measurement == "LG" else False, manual_y,
            f"{signature}|summary|{measurement}|{','.join(cases)}|{','.join(mms)}|{channel}",
            reference_mms=mms,
            envelope_source=project.source_names.get(measurement.casefold(), ""),
            mm_source=project.source_names.get("mm", ""),
            sa_source=project.source_names.get("sa", ""),
        )
        figures[measurement] = figure
        st.plotly_chart(figure, width="stretch", config={"displaylogo": False}, alt=f"Maximum selected {measurement} representative envelope with governing source provenance")
    st.markdown("#### Peak by case and MM point")
    peak_rows = []
    for measurement, selected in chosen.items():
        for (case, mm_id), group in selected.groupby(["Case", "MM_ID"], sort=True):
            peak = group.loc[group["Voltage_kV_peak"].idxmax()]
            row = {"Measurement": measurement, "Case": case, "MM_ID": mm_id, "Peak (kV peak)": float(peak["Voltage_kV_peak"]), "Peak index (s)": float(peak["Index_s"])}
            if channel == "Max_all":
                row.update({column: peak[column] for column in ("Run", "Fault_type") if column in peak and pd.notna(peak[column])})
            peak_rows.append(row)
    peaks = pd.DataFrame(peak_rows)
    st.dataframe(peaks, hide_index=True, width="stretch")
    comparison = pd.concat(
        [crossing_summary(chosen[m], project.mm_blocks, m, reference, channel) for m in ("LG", "LL")],
        ignore_index=True,
    )
    envelope_crossings = []
    for measurement in ("LG", "LL"):
        crossing = closest_reference_crossing(maxima[measurement], project.mm_blocks, measurement, reference)
        if crossing:
            envelope_crossings.append({"Measurement": measurement, **crossing})
        else:
            envelope_crossings.append({"Measurement": measurement, "Crossing": "No sampled reference crossing in the selected range", "Assessment": "Numerical ranked-index comparison only; not a duration violation"})
    crossing_frame = pd.DataFrame(envelope_crossings)
    st.markdown("#### Closest reference crossing")
    st.dataframe(crossing_frame, hide_index=True, width="stretch")
    st.caption("The plotted maximum is calculated independently at each representative index. Its governing Case/MM (and Run/Fault_type for Max_all) can change from point to point. Crossings are ranked-index comparisons, not duration violations.")
    references = comparison
    plot_data = pd.concat(plotted, ignore_index=True) if plotted else pd.DataFrame()
    metadata = {
        "View": "Overall summary",
        "Cases": cases,
        "MM points": mms,
        "Nominal voltage (kV)": voltage,
        "Channel": channel,
        "Index range (ranked index s)": index,
        "IC reference": reference if show_ic else "Hidden",
        "IC changeover (s)": CHANGEOVER_S,
        "Safety factor": SAFETY_FACTOR,
        "LG source": project.source_names.get("lg", ""),
        "LL source": project.source_names.get("ll", ""),
        "MM workbook": project.source_names.get("mm", ""),
        "SA workbook": project.source_names.get("sa", ""),
        "Assessment status": "Ranked-index comparison only; not chronological TOV/compliance assessment",
    }
    _downloads(figures, plot_data, peaks, pd.concat([references, crossing_frame], ignore_index=True, sort=False), project.issues, metadata, "voltage_summary")


def _render_limits(project: ProjectData) -> None:
    st.subheader("Limits and assignments")
    st.markdown("**IC project reference convention:** SIWL is kV peak for index < 0.020 s; SDPF is assumed kV RMS and converted by √2 for index ≥ 0.020 s. Safety-margin references divide either by 1.15. The changeover is project-specific, not a universal IEC declaration.")
    st.warning("The CSV index is a ranked representative-envelope index, not elapsed exposure time. A curve/reference intersection does not establish physical TOV withstand or compliance.")
    if project.mm_blocks is None:
        st.info("Load a workbook containing MM_blocks to inspect insulation-coordination data.")
    else:
        st.markdown("#### MM_blocks source catalogue")
        st.dataframe(project.mm_blocks, hide_index=True, width="stretch")
        st.caption(f"Source: {project.source_names.get('mm', 'MM workbook')}. SDPF units are not stated in the workbook; kV RMS is a documented project assumption.")
        derived_rows = []
        for _, source_row in project.mm_blocks.iterrows():
            for measurement in ("LG", "LL"):
                try:
                    values = ic_values(source_row, measurement)
                except (KeyError, TypeError, ValueError):
                    continue
                derived_rows.append(
                    {
                        "MM_ID": source_row["Group"],
                        "Un (kV)": source_row.get("Un"),
                        "Measurement": measurement,
                        "SIWL input (kV peak)": values["SIWL_peak"],
                        "SIWL / 1.15 (kV peak)": values["SIWL_margin_peak"],
                        "SDPF input (assumed kV RMS)": values["SDPF_input"],
                        "SDPF × √2 (kV peak)": values["SDPF_peak"],
                        "SDPF × √2 / 1.15 (kV peak)": values["SDPF_margin_peak"],
                        "Changeover (s)": CHANGEOVER_S,
                        "Safety factor": SAFETY_FACTOR,
                        "Input workbook": project.source_names.get("mm", ""),
                    }
                )
        st.markdown("#### Derived IC references by MM and measurement")
        st.dataframe(pd.DataFrame(derived_rows), hide_index=True, width="stretch")
        candidates = project.mm_blocks.loc[project.mm_blocks["Un"].eq(230)] if "Un" in project.mm_blocks else pd.DataFrame()
        if not candidates.empty:
            row = candidates.iloc[0]
            vals = ic_values(row, "LG")
            st.caption(f"230 kV spot check ({row['Group']}, LG): SIWL margin {vals['SIWL_margin_peak']:.2f} kV peak; SDPF raw {vals['SDPF_peak']:.2f} kV peak; SDPF margin {vals['SDPF_margin_peak']:.2f} kV peak.")
    st.markdown("#### Surge-arrester types and source status")
    if project.sa is None:
        st.info("No SA workbook selected. Envelope and IC views remain available.")
    elif project.sa.kind == "legacy":
        st.warning("Legacy SA data has unknown manufacturer verification, duty basis, voltage basis and MM assignment. No mapping is inferred. The curves are preserved as numeric comparison data only.")
        st.dataframe(project.sa.legacy, hide_index=True, width="stretch")
        elements = sorted(project.sa.legacy["Element"].dropna().astype(str).unique())
        mm_ids = project.mm_blocks["Group"].dropna().astype(str).tolist() if project.mm_blocks is not None and "Group" in project.mm_blocks else []
        st.markdown("#### Explicit legacy mapping (session only)")
        for index, element in enumerate(elements):
            left, middle, right = st.columns([2, 2, 2])
            left.write(element)
            mm_options = ["Unassigned", *mm_ids]
            key = f"legacy_mm_{index}"
            if st.session_state.get(key) not in mm_options:
                st.session_state[key] = "Unassigned"
            middle.selectbox("MM point", mm_options, key=key, label_visibility="collapsed")
            right.selectbox("Installation status", ["Unknown", "Installed", "Not installed"], key=f"legacy_status_{index}", label_visibility="collapsed")
        _, mapping = _legacy_assignments(project.sa, project.mm_blocks)
        if mapping and len({item["MM_ID"] for item in mapping.values()}) == len(mapping) and len(mapping) == len(elements):
            try:
                converted = convert_legacy_to_new(project.sa, project.mm_blocks, mapping)
                st.download_button("Export mapped SA workbook (XLSX)", converted, "SA_characteristics_mapped_legacy.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="legacy_conversion_download")
            except (KeyError, ValueError) as exc:
                st.error(f"Legacy conversion unavailable: {exc}")
        else:
            st.caption("Map every legacy element to a unique MM point to enable conversion export.")
    else:
        st.markdown("**SA_Types**")
        st.dataframe(project.sa.types, hide_index=True, width="stretch")
        st.markdown("**MM_Assignment**")
        st.dataframe(project.sa.assignments, hide_index=True, width="stretch")
        st.markdown("**SA_Curves**")
        st.dataframe(project.sa.curves, hide_index=True, width="stretch")
        if project.mm_blocks is not None:
            from sa_data import validate_sa_compatibility
            compatibility = validation_frame(validate_sa_compatibility(project.sa, project.mm_blocks))
            if not compatibility.empty:
                st.dataframe(compatibility, hide_index=True, width="stretch")
    st.download_button("Blank SA characteristics template (XLSX)", create_blank_template(), "SA_characteristics_template.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="sa_template_download")
    st.download_button("Synthetic SA workbook example (XLSX)", create_synthetic_example(), "SA_characteristics_synthetic_example.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="sa_example_download")
    st.markdown("**Deferred:** SA V–I/energy calculation, manufacturer-datasheet digitisation, extrapolated sub-0.1 s thermal withstand, and chronological SA duty/compliance assessment. No SA pass/fail result is calculated from representative CSVs.")


def main() -> None:
    st.title("Voltage Envelopes")
    st.caption("PSCAD representative-envelope and insulation-coordination reference viewer")
    project, _selected, signature = _source_panel()
    source_status = pd.DataFrame(
        [
            {"Source": name, "Selected file": project.source_names.get(role, "Not selected"), "Origin": project.source_origins.get(role, "—"), "Status": ("Selected; reference only, not loaded at runtime" if role == "dashboard" and project.source_names.get(role) else "Loaded" if project.source_names.get(role) else "Optional / unavailable")}
            for role, name in (("lg", "LG results"), ("ll", "LL results"), ("mm", "MM_blocks"), ("sa", "SA characteristics"), ("wl", "Legacy IC limits"), ("dashboard", "Excel dashboard reference"))
        ]
    )
    with st.expander("Source files and status", expanded=False):
        st.dataframe(source_status, hide_index=True, width="stretch")
        if project.loaded_at:
            st.caption(f"Last load: {project.loaded_at.strftime('%Y-%m-%d %H:%M:%S %Z')} · parse and validation: {project.load_seconds:.2f} s · current source scan: {st.session_state.get('source_scan_seconds', 0):.3f} s · cache signature: {signature[:12]}")
    if project.lg is not None and project.ll is not None:
        cases = available_cases(project.lg, project.ll)
        mms = available_mms(project.lg, project.ll)
        voltages = nominal_voltages(project.mm_blocks, mms)
        metrics = st.columns(4)
        metrics[0].metric("Cases", len(cases))
        metrics[1].metric("Result MM points", len(mms))
        metrics[2].metric("Configured MM points", project.mm_blocks["Group"].nunique() if project.mm_blocks is not None and "Group" in project.mm_blocks else "—")
        metrics[3].metric("Nominal voltage levels", len(voltages))
    _issue_summary(project.issues)
    blocking_result = any(bool(issue.get("Blocking")) and issue.get("Area") in {"LG CSV", "LL CSV"} for issue in project.issues)
    if blocking_result:
        st.error("Resolve the blocking LG/LL input errors before plotting result curves. Validation and source details remain available below.")
    st.info("**Interpretation:** the CSV time column is a representative-envelope ranking/index. It is not a continuous waveform or elapsed equipment exposure time. Intersections with IC or SA curves are reference comparisons only; this app does not calculate chronological TOV compliance.")
    views = ["Detailed comparison", "Overall summary", "Limits & assignments"]
    view = st.segmented_control("Dashboard view", views, default=views[0], key="active_view")
    started = time.perf_counter()
    if view == "Detailed comparison" and not blocking_result:
        _render_detailed(project, signature)
    elif view == "Overall summary" and not blocking_result:
        _render_summary(project, signature)
    elif view == "Limits & assignments":
        _render_limits(project)
    elif blocking_result:
        st.info("Load valid LG and LL result CSV files to display dashboard charts.")
    st.sidebar.markdown("---")
    st.sidebar.caption(f"View computation/render preparation: {time.perf_counter() - started:.3f} s (server-side; excludes browser rendering).")
    view_prefix = "voltage_detailed" if view == "Detailed comparison" else "voltage_summary"
    st.sidebar.caption(f"Rendered figure JSON payload: {st.session_state.get(f'{view_prefix}_payload_bytes', 0):,} bytes across visible charts.")


if __name__ == "__main__":
    main()
