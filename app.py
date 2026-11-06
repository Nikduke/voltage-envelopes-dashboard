"""Streamlit entry point for the local voltage-envelope dashboard."""

from __future__ import annotations

from functools import partial
from hashlib import sha256
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analysis import (
    available_cases,
    available_mms,
    crossing_summary,
    crossing_summaries,
    mms_at_voltage,
    nominal_voltages,
    select_curves,
    summary_envelope,
)
from chart_exports import export_report_charts_zip
from data_loader import ProjectData, SourceCandidate, discover_sources, load_project_data, source_signature
from exports import export_xlsx_bytes
from limits import CHANGEOVER_S, SAFETY_FACTOR, ic_values
from plots import build_envelope_figure
from sa_data import create_blank_template
from selection_state import selection_after_click
from validation import validation_frame


APP_ROOT = Path(__file__).resolve().parent
APP_LOGO_PATH = APP_ROOT / "assets" / "mpe_app_wordmark.png"
APP_ICON_PATH = APP_ROOT / "assets" / "mpe_app_icon.png"
st.set_page_config(page_title="Voltage Envelopes", page_icon=str(APP_ICON_PATH), layout="wide", initial_sidebar_state="expanded")
st.html(
    """
<style>
.st-key-detail_channel [role="radio"] {
    padding-inline: 0.4rem !important;
}
</style>
""",
)
PLOT_WIDTH_KEY = "voltage_envelopes_plot_width"
_PLOT_WIDTH_SENSOR = st.components.v2.component(
    "voltage_envelopes_plot_width_sensor",
    html='<div id="plot-width-sensor" aria-hidden="true"></div>',
    css="#plot-width-sensor { width: 100%; height: 0; overflow: hidden; }",
    js="""
const sensors = new WeakMap()

export default function (component) {
  const { data, parentElement, setStateValue } = component
  const host = parentElement.host
  const previous = sensors.get(parentElement)
  if (previous) {
    clearTimeout(previous.timer)
    previous.observer.disconnect()
  }

  const sensor = { observer: null, timer: null }
  let lastWidth = Number(data?.width ?? 0)
  const reportWidth = () => {
    const width = Math.round(host.getBoundingClientRect().width / 8) * 8
    if (width > 0 && width !== lastWidth) {
      lastWidth = width
      setStateValue("width", width)
    }
  }
  const observer = new ResizeObserver(() => {
    clearTimeout(sensor.timer)
    sensor.timer = setTimeout(reportWidth, 120)
  })
  sensor.observer = observer
  sensors.set(parentElement, sensor)
  observer.observe(host)
  reportWidth()

  return () => {
    clearTimeout(sensor.timer)
    observer.disconnect()
    if (sensors.get(parentElement) === sensor) sensors.delete(parentElement)
  }
}
""",
)
_SELECTION_CHIP_GROUP = st.components.v2.component(
    "voltage_envelopes_selection_chip_group",
    html='<div id="selection-chip-group" role="group"></div>',
    css="""
#selection-chip-group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px 6px;
}
#selection-chip-group button {
  border: 1px solid var(--st-border-color, #C8D0D8);
  border-radius: 999px;
  background: var(--st-background-color, #FFFFFF);
  color: var(--st-text-color, #1F2937);
  cursor: pointer;
  font: inherit;
  line-height: 1.25;
  padding: 0.34rem 0.72rem;
  white-space: nowrap;
}
#selection-chip-group button[aria-pressed="true"] {
  border-color: var(--st-primary-color, #0B7A75);
  background: color-mix(in srgb, var(--st-primary-color, #0B7A75) 11%, #FFFFFF);
  color: var(--st-primary-color, #0B7A75);
}
#selection-chip-group button:focus-visible {
  outline: 2px solid var(--st-primary-color, #0B7A75);
  outline-offset: 2px;
}
""",
    js="""
export default function (component) {
  const { data, parentElement, setTriggerValue } = component
  const root = parentElement.querySelector("#selection-chip-group")
  if (!root) return

  const options = Array.isArray(data?.options) ? data.options.map(String) : []
  const optionsSignature = JSON.stringify(options)
  if (root.dataset.options !== optionsSignature) {
    root.replaceChildren()
    options.forEach((option, index) => {
      const button = document.createElement("button")
      button.type = "button"
      button.textContent = option
      button.dataset.index = String(index)
      button.setAttribute("aria-label", option)
      button.setAttribute("aria-pressed", "false")
      button.onclick = (event) => {
        setTriggerValue("clicked", {
          option,
          exclusive: Boolean(event.ctrlKey || event.metaKey),
        })
      }
      root.append(button)
    })
    root.dataset.options = optionsSignature
  }

  root.setAttribute("aria-label", String(data?.label ?? "Selectable items"))
  const selected = new Set(Array.isArray(data?.selected) ? data.selected.map(String) : [])
  for (const button of root.querySelectorAll("button")) {
    const option = options[Number(button.dataset.index)]
    button.setAttribute("aria-pressed", selected.has(option) ? "true" : "false")
  }
}
""",
)


def _measure_plot_container_width() -> int | None:
    width_state = st.session_state.get(PLOT_WIDTH_KEY, {})
    width_state = width_state if isinstance(width_state, dict) else {}
    _PLOT_WIDTH_SENSOR(
        key=PLOT_WIDTH_KEY,
        data={"width": width_state.get("width", 0)},
        default={"width": 0},
        on_width_change=lambda: None,
        width="stretch",
        height="content",
    )
    width_state = st.session_state.get(PLOT_WIDTH_KEY, {})
    width_state = width_state if isinstance(width_state, dict) else {}
    width = int(width_state.get("width", 0) or 0)
    return width or None


def _set_selection(key: str, values: list[str]) -> None:
    st.session_state[key] = list(values)


def _apply_chip_click(key: str, component_key: str, options: list[str]) -> None:
    component_state = st.session_state.get(component_key, {})
    if isinstance(component_state, dict):
        click = component_state.get("clicked")
        if isinstance(click, dict):
            st.session_state[key] = selection_after_click(
                options,
                list(st.session_state.get(key, [])),
                str(click.get("option", "")),
                bool(click.get("exclusive", False)),
            )


@st.cache_data(max_entries=3, show_spinner=False)
def cached_project_load(_selected: dict[str, SourceCandidate | None], signature: str) -> ProjectData:
    return load_project_data(_selected)


@st.cache_data(max_entries=3, show_spinner=False)
def cached_selection_catalogs(
    _lg: pd.DataFrame | None,
    _ll: pd.DataFrame | None,
    signature: str,
) -> tuple[list[str], list[str]]:
    """Reuse Case/MM options for an unchanged source set."""
    return available_cases(_lg, _ll), available_mms(_lg, _ll)


@st.cache_data(max_entries=3, show_spinner=False)
def cached_reference_display_data(
    _project: ProjectData,
    signature: str,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Reuse source-derived Data & references tables for an unchanged source set."""
    project = _project
    source_rows = pd.DataFrame(
        [
            {
                "Input": label,
                "File": project.source_names.get(role, "Not selected"),
                "Origin": project.source_origins.get(role, "—"),
                "Status": "Loaded" if project.source_names.get(role) else ("Optional" if role == "sa" else "Required"),
            }
            for role, label in (("lg", "LG results"), ("ll", "LL results"), ("mm", "MM_blocks workbook"), ("sa", "SA reference"))
        ]
    )
    derived_rows: list[dict[str, object]] = []
    if project.mm_blocks is not None:
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
                        "SIWL (kV peak)": values["SIWL_peak"],
                        "SIWL / 1.15": values["SIWL_margin_peak"],
                        "SDPF input (assumed kV RMS)": values["SDPF_input"],
                        "SDPF × √2 (kV peak)": values["SDPF_peak"],
                        "SDPF × √2 / 1.15": values["SDPF_margin_peak"],
                        "LIWL (metadata)": source_row.get("LIWL"),
                    }
                )
    derived_frame = pd.DataFrame(derived_rows)
    if project.sa is None or project.sa.curves.empty:
        sa_point_counts = pd.DataFrame(columns=["SA_ID", "Source_points", "Supplied_values"])
    else:
        sa_point_counts = (
            project.sa.curves.groupby("SA_ID", dropna=False)["Voltage_kV_peak"]
            .agg(Source_points="size", Supplied_values="count")
            .reset_index()
        )
    issues = validation_frame(project.issues)
    return source_rows, derived_frame, sa_point_counts, issues


@st.cache_data(max_entries=3, show_spinner=False)
def cached_source_discovery(uploads: tuple[tuple[str, bytes], ...]) -> dict[str, list[SourceCandidate]]:
    return discover_sources(list(uploads))


def _selection_pills(
    label: str,
    options: list[str],
    key: str,
    default_all: bool = True,
    default: list[str] | None = None,
    container=st.sidebar,
    controls_below: bool = False,
) -> list[str]:
    options = list(dict.fromkeys(map(str, options)))
    options_key = f"{key}_options"
    previous_options = st.session_state.get(options_key)
    previous = st.session_state.get(key)
    if previous is None:
        selected = list(default if default is not None else (options if default_all else []))
    elif previous_options != options:
        overlap = [option for option in previous if option in options]
        selected = overlap if overlap or not previous else list(default if default is not None else options)
    else:
        selected = [option for option in previous if option in options]
    st.session_state[key] = selected
    st.session_state[options_key] = options
    component_key = f"{key}_chips"

    if controls_below:
        container.markdown(f"**{label} ({len(selected)}/{len(options)})**")
        all_col, clear_col = container.columns(2, vertical_alignment="center")
    else:
        title, all_col, clear_col = container.columns([2, 1, 1], vertical_alignment="center")
        title.markdown(f"**{label} ({len(selected)}/{len(options)})**")
    all_col.button(
        "All",
        key=f"{key}_all",
        disabled=not options,
        width="stretch",
        on_click=_set_selection,
        args=(key, options),
    )
    clear_col.button(
        "Clear",
        key=f"{key}_clear",
        disabled=not options,
        width="stretch",
        on_click=_set_selection,
        args=(key, []),
    )
    if not options:
        container.caption(f"No {label.casefold()} available.")
        return []
    with container:
        _SELECTION_CHIP_GROUP(
            key=component_key,
            data={"label": label, "options": options, "selected": selected},
            on_clicked_change=partial(_apply_chip_click, key, component_key, options),
            width="stretch",
            height="content",
        )
    return list(st.session_state.get(key, selected))


def _valid_segmented_control(
    label: str,
    options: list,
    key: str,
    format_func=None,
    container=st,
):
    if not options:
        container.caption(f"{label}: no available values")
        return None
    if key in st.session_state and st.session_state[key] not in options:
        st.session_state[key] = options[0]
    arguments = {"key": key, "format_func": format_func, "width": "stretch"}
    if key not in st.session_state:
        arguments["default"] = options[0]
    return container.segmented_control(label, options, **arguments)


def _valid_single_pill(label: str, options: list, key: str, format_func=None, container=st):
    if not options:
        container.caption(f"{label}: no available values")
        return None
    if key in st.session_state and st.session_state[key] not in options:
        st.session_state[key] = options[0]
    arguments = {
        "selection_mode": "single",
        "key": key,
        "format_func": format_func,
        "label_visibility": "visible",
        "width": "content",
        "wrap": True,
    }
    if key not in st.session_state:
        arguments["default"] = options[0]
    return container.pills(label, options, **arguments)


def _remember_violation_selection(
    table_key: str,
    scope: str,
    row_targets: list[tuple[str, str, str]],
) -> None:
    state = st.session_state.get(table_key)
    selection = state.get("selection", {}) if isinstance(state, dict) else getattr(state, "selection", None)
    rows = selection.get("rows", []) if isinstance(selection, dict) else getattr(selection, "rows", [])
    target = row_targets[int(rows[0])] if rows and 0 <= int(rows[0]) < len(row_targets) else None
    st.session_state["selected_violation_curve"] = {"scope": scope, "target": target}


def _index_range(frames: list[pd.DataFrame], key: str, container=st) -> tuple[float, float] | None:
    available = [frame["Time (s)"] for frame in frames if not frame.empty and "Time (s)" in frame]
    if not available:
        return None
    values = pd.concat(available, ignore_index=True).dropna()
    if values.empty:
        return None
    low, high = float(values.min()), float(values.max())
    if np.isclose(low, high):
        return low, high
    options = np.sort(values.unique()).astype(float).tolist()
    return container.select_slider(
        "Index range (s)",
        options=options,
        value=(options[0], options[-1]),
        key=key,
        format_func=lambda value: f"{value:.3f}",
        persist_state="session",
    )


def _source_selector(role: str, label: str, candidates: list[SourceCandidate]) -> SourceCandidate | None:
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    labels = [candidate.label for candidate in candidates]
    options = ["Select a file…", *labels]
    key = f"source_{role}"
    if st.session_state.get(key) not in options:
        st.session_state[key] = options[0]
    choice = st.sidebar.selectbox(f"{label} — choose source", options, key=key)
    return candidates[labels.index(choice)] if choice in labels else None


def _issue_summary(frame: pd.DataFrame) -> None:
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
def _source_panel() -> tuple[ProjectData, str]:
    st.sidebar.image(str(APP_LOGO_PATH), width=210)
    st.sidebar.header("Project files")
    uploaded = st.sidebar.file_uploader(
        "Project files",
        type=["zip", "csv", "xlsx", "xlsm"],
        accept_multiple_files=True,
        key="project_files",
        help="Upload one project ZIP or the individual LGp/LLp CSVs and PSCAD workbook. SA.xlsx is optional.",
    )
    upload_payload = tuple((item.name, item.getvalue()) for item in (uploaded or []))
    try:
        candidates = cached_source_discovery(upload_payload) if upload_payload else {role: [] for role in ("lg", "ll", "mm", "sa")}
    except ValueError as exc:
        st.sidebar.error(str(exc))
        candidates = {role: [] for role in ("lg", "ll", "mm", "sa")}
    labels = {"lg": "LG results CSV", "ll": "LL results CSV", "mm": "MM_blocks workbook", "sa": "SA workbook"}
    selected = {role: _source_selector(role, labels[role], candidates[role]) for role in candidates}
    if upload_payload and not any(candidates.values()):
        st.sidebar.warning("No supported project inputs were found in the uploaded files.")
    elif upload_payload and any(selected[role] is None for role in ("lg", "ll", "mm")):
        st.sidebar.warning("Upload or select LGp.csv, LLp.csv and the PSCAD input workbook.")
    signature = source_signature(selected)
    try:
        with st.spinner("Loading and validating source files…"):
            project = cached_project_load(selected, signature)
    except Exception as exc:
        project = ProjectData(issues=[{"Severity": "Error", "Area": "Source loading", "Code": "load_error", "Message": str(exc), "Identifier": "", "Blocking": True}])
    return project, signature


def _view_controls(project: ProjectData, signature: str) -> tuple[float, str, list[str], list[str]]:
    st.sidebar.markdown("#### View")
    cases_available, mms_available = cached_selection_catalogs(project.lg, project.ll, signature)
    voltages = nominal_voltages(project.mm_blocks, mms_available)
    voltage = _valid_single_pill(
        "Voltage level",
        voltages,
        "voltage_level",
        format_func=lambda value: f"{value:g} kV",
        container=st.sidebar,
    )
    reference = _valid_segmented_control(
        "IC reference",
        ["Safety margin", "Withstand"],
        "ic_reference_choice",
        container=st.sidebar,
    ) or "Safety margin"
    selected_voltage = float(voltage) if voltage is not None else float("nan")
    return selected_voltage, reference, cases_available, mms_available


def _main_selection_controls(
    project: ProjectData,
    voltage: float,
    cases_available: list[str],
    mms_available: list[str],
) -> tuple[list[str], list[str]]:
    mms_at_v = mms_at_voltage(project.mm_blocks, mms_available, voltage)
    cases: list[str] = []
    selected_mms: list[str] = []
    if cases_available or mms_available:
        case_column, mm_column = st.columns(2, gap="medium")
        with case_column:
            case_container = st.container(border=True)
            cases = _selection_pills("Cases", cases_available, "selected_cases", container=case_container)
        with mm_column:
            mm_container = st.container(border=True)
            selected_mms = _selection_pills("MM points", mms_at_v, "selected_mms", container=mm_container)
    return cases, selected_mms


def _sidebar_controls(
    project: ProjectData,
    signature: str,
    active_analysis_view: bool,
    active_all_envelopes: bool,
    voltage: float,
    cases: list[str],
    selected_mms: list[str],
) -> dict[str, object]:
    source_frames = [frame for frame in (project.lg, project.ll) if frame is not None and not frame.empty]
    if "show_ic_limits" not in st.session_state:
        st.session_state["show_ic_limits"] = True
    show_ic = st.sidebar.toggle("IC limits", key="show_ic_limits")

    sa_assignments, sa_options = _sa_catalog(project, voltage)
    if sa_options:
        if "show_sa_limits" not in st.session_state:
            st.session_state["show_sa_limits"] = True
        show_sa = st.sidebar.toggle("SA limits", key="show_sa_limits")
    else:
        show_sa = False
        if project.source_names.get("sa") and (project.sa is None or project.sa.kind != "new"):
            st.sidebar.caption(
                f"{project.source_names['sa']} could not be used as a dashboard reference; see Data & references → Validation."
            )
    sa_by_mm = _sa_controls(sa_assignments, sa_options, selected_mms, voltage, signature)

    index = None
    channel = "Max_all"
    selected_curves: dict[str, pd.DataFrame] = {}
    if active_analysis_view:
        with st.sidebar.expander("Envelope controls", expanded=False) as envelope_controls:
            index = _index_range(source_frames, "detail_index_grid", envelope_controls)
            if active_all_envelopes:
                channel = _valid_single_pill(
                    "Envelope channel",
                    ["Max_all", "Max_A", "Max_B", "Max_C"],
                    "detail_channel",
                    container=envelope_controls,
                ) or "Max_all"
        if active_all_envelopes:
            selected_curves = {
                "LG": select_curves(project.lg, cases, selected_mms, index, channel),
                "LL": select_curves(project.ll, cases, selected_mms, index, channel),
            }

    return {
        "index": index,
        "channel": channel,
        "show_ic": show_ic,
        "show_sa": show_sa,
        "sa_by_mm": sa_by_mm,
        "selected_curves": selected_curves,
    }


def _sa_catalog(project: ProjectData, voltage: float) -> tuple[pd.DataFrame, list[str]]:
    sa = project.sa
    mm_blocks = project.mm_blocks
    if sa is None or sa.kind != "new" or mm_blocks is None or not {"Group", "Un"}.issubset(mm_blocks.columns):
        return pd.DataFrame(), []
    has_values = set(sa.curves.loc[sa.curves["Voltage_kV_peak"].notna(), "SA_ID"].astype(str))
    mm_voltages = pd.to_numeric(mm_blocks["Un"], errors="coerce")
    at_voltage = np.isclose(
        mm_voltages.to_numpy(dtype=float, na_value=np.nan),
        voltage,
        rtol=0.0,
        atol=1e-6,
    )
    voltage_mms = set(mm_blocks.loc[at_voltage, "Group"].dropna().astype(str))
    assignments = sa.assignments.loc[
        sa.assignments["MM_ID"].astype(str).isin(voltage_mms)
        & sa.assignments["SA_ID"].astype(str).ne("")
    ]
    options = sorted(set(assignments["SA_ID"].astype(str)) & has_values)
    return assignments, options


def _sa_controls(
    assignments: pd.DataFrame,
    options: list[str],
    selected_mms: list[str],
    voltage: float,
    signature: str,
) -> dict[str, list[str]]:
    if not options:
        return {}

    selected_mm_set = set(map(str, selected_mms))
    mapped_defaults = sorted(
        set(assignments.loc[assignments["MM_ID"].astype(str).isin(selected_mm_set), "SA_ID"].astype(str))
        & set(options)
    )
    selection_key = sha256("|".join([signature, str(voltage)]).encode("utf-8")).hexdigest()[:12]
    widget_key = f"sa_limits_{selection_key}"
    mm_signature_key = f"sa_defaults_mm_signature_{selection_key}"
    mm_signature = sha256("|".join(sorted(selected_mm_set)).encode("utf-8")).hexdigest()[:12]
    if st.session_state.get(mm_signature_key) != mm_signature:
        st.session_state[widget_key] = mapped_defaults
        st.session_state[mm_signature_key] = mm_signature
    selected = _selection_pills(
        "SA limits to apply",
        options,
        widget_key,
        default_all=False,
        default=mapped_defaults,
        container=st.sidebar,
        controls_below=True,
    )
    st.sidebar.caption(f"Mapped to {voltage:g} kV MM points; selected MM assignments are checked.")
    return {mm_id: list(selected) for mm_id in selected_mm_set}


def _downloads(
    plotted: pd.DataFrame,
    summary: pd.DataFrame,
    references: pd.DataFrame,
    issues: list[dict[str, object]],
    metadata: dict[str, object],
    prefix: str,
    report_figures: dict[str, go.Figure],
) -> None:
    sa_data = metadata.get("_sa_data")
    export_metadata = {key: value for key, value in metadata.items() if not key.startswith("_")}

    def make_xlsx() -> bytes:
        return export_xlsx_bytes(
            plotted,
            summary,
            references,
            validation_frame(issues),
            export_metadata,
            sa_curves=sa_data.curves if sa_data is not None and sa_data.kind == "new" else None,
            sa_assignments=sa_data.assignments if sa_data is not None and sa_data.kind == "new" else None,
        )

    def make_report_charts() -> bytes:
        is_summary = metadata["View"] == "Summary"
        return export_report_charts_zip(
            report_figures,
            include_curve_legend=is_summary,
            filename_prefix="summary" if is_summary else "all_envelopes",
        )

    xlsx_column, charts_column = st.columns(2, gap="small")
    xlsx_column.download_button(
        "Download selected results (.xlsx)",
        make_xlsx,
        f"{prefix}_results.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"{prefix}_xlsx",
        type="primary",
        width="stretch",
    )
    charts_column.download_button(
        "Download report charts (.zip)",
        make_report_charts,
        f"{prefix}_report_charts.zip",
        "application/zip",
        key=f"{prefix}_report_charts",
        help="Contains separate LG and LL PNG charts at fixed A4 report size. Summary keeps the curve legend; All envelopes keeps only the IC and SA limit legend.",
        width="stretch",
    )
def _blocking_result(project: ProjectData) -> bool:
    return any(
        bool(issue.get("Blocking")) and issue.get("Area") in {"LG CSV", "LL CSV"}
        for issue in project.issues
    )


def _blocking_result_message(project: ProjectData, destination: str) -> str:
    if any(
        issue.get("Code") == "source_not_selected" and issue.get("Area") in {"LG CSV", "LL CSV"}
        for issue in project.issues
    ):
        return f"Upload project inputs in the sidebar to view {destination}."
    return f"Resolve the blocking LG/LL data issues listed in Data & references to view {destination}."


def _render_detailed_view(
    project: ProjectData,
    signature: str,
    voltage: float,
    reference: str,
    cases: list[str],
    mms: list[str],
    index: tuple[float, float] | None,
    channel: str,
    show_ic: bool,
    show_sa: bool,
    sa_by_mm: dict[str, list[str]],
    chosen: dict[str, pd.DataFrame],
    plot_container_width: int | None,
) -> None:
    st.subheader("All envelopes")
    st.caption("Individual LG and LL envelopes. Select a row in either IC table below the plots to highlight its curve.")
    if not cases or not mms:
        st.info("Select at least one case and one MM point to display the envelopes.")
        return
    plotted: list[pd.DataFrame] = []
    curve_summaries = {
        measurement: crossing_summaries(chosen[measurement], project.mm_blocks, measurement, reference, channel)
        for measurement in ("LG", "LL")
    }
    reference_rows = pd.concat(
        [curve_summaries[m]["all"] for m in ("LG", "LL")],
        ignore_index=True,
    )
    exceedances = reference_rows.loc[reference_rows["Ranked samples above reference"].gt(0)].copy()
    exceedances = exceedances.sort_values(
        ["Over-limit area (kV·ranked-index s)", "Peak excess (kV)", "Measurement", "Case", "MM_ID"],
        ascending=[False, False, True, True, True],
        kind="stable",
    ).reset_index(drop=True)
    selection_key = "|".join(
        [signature, reference, str(voltage), channel, str(index), *cases, *mms]
    )
    part_exceedances = {
        part: pd.concat(
            [curve_summaries[m][part] for m in ("LG", "LL")],
            ignore_index=True,
        )
        for part in ("SFO", "TOV")
    }
    for part, frame in part_exceedances.items():
        part_exceedances[part] = frame.loc[frame["Ranked samples above reference"].gt(0)].sort_values(
            ["Over-limit area (kV·ranked-index s)", "Peak excess (kV)", "Measurement", "Case", "MM_ID"],
            ascending=[False, False, True, True, True],
            kind="stable",
        ).reset_index(drop=True)
    selected_state = st.session_state.get("selected_violation_curve")
    selected_violation = (
        selected_state.get("target")
        if isinstance(selected_state, dict) and selected_state.get("scope") == selection_key
        else None
    )
    if selected_state is None:
        for part in ("SFO", "TOV"):
            table_key = f"limit_exceedances_{part.casefold()}_" + sha256(selection_key.encode("utf-8")).hexdigest()[:16]
            table_state = st.session_state.get(table_key)
            table_selection = table_state.get("selection", {}) if isinstance(table_state, dict) else getattr(table_state, "selection", None)
            rows = table_selection.get("rows", []) if isinstance(table_selection, dict) else getattr(table_selection, "rows", [])
            if rows and 0 <= int(rows[0]) < len(part_exceedances[part]):
                row = part_exceedances[part].iloc[int(rows[0])]
                selected_violation = (str(row["Measurement"]), str(row["Case"]), str(row["MM_ID"]))
                break
    report_figures: dict[str, go.Figure] = {}
    for measurement in ("LG", "LL"):
        selected = chosen[measurement]
        if not selected.empty:
            plotted.append(selected.assign(Measurement=measurement))
        figure = build_envelope_figure(
            selected,
            measurement,
            channel,
            "detailed",
            project.mm_blocks,
            reference,
            show_ic,
            project.sa,
            sa_by_mm if measurement == "LG" else {},
            f"{signature}|detail|{measurement}|{','.join(cases)}|{','.join(mms)}|{channel}",
            reference_mms=mms,
            envelope_source=project.source_names.get(measurement.casefold(), ""),
            mm_source=project.source_names.get("mm", ""),
            highlight_curve=(selected_violation[1], selected_violation[2])
            if selected_violation is not None and selected_violation[0] == measurement
            else None,
            plot_container_width=plot_container_width,
            show_sa=show_sa,
            x_range=index,
        )
        report_figures[measurement] = figure
        st.plotly_chart(
            figure,
            width="stretch",
            config={"displaylogo": False, "modeBarButtonsToRemove": ["toImage"]},
            alt=f"{measurement} representative voltage envelopes by case and MM point",
        )
    st.caption("The tables use the selected IC reference. Select a row to highlight its curve.")
    for part, label in (("SFO", "SFO part"), ("TOV", "TOV part")):
        table = part_exceedances[part]
        st.markdown(f"#### {label} violations — {reference}")
        if table.empty:
            st.info(f"No selected LG or LL envelopes exceed the {reference.lower()} reference in this part.")
            continue
        table_columns = ["Measurement", "Case", "MM_ID"]
        if channel == "Max_all":
            table_columns.append("Runs with exceedance")
        table_columns.extend(["Peak excess (kV)", "Over-limit area (kV·ranked-index s)"])
        table_key = f"limit_exceedances_{part.casefold()}_" + sha256(selection_key.encode("utf-8")).hexdigest()[:16]
        row_targets = [
            (str(row.Measurement), str(row.Case), str(row.MM_ID))
            for row in table[["Measurement", "Case", "MM_ID"]].itertuples(index=False)
        ]
        st.dataframe(
            table[table_columns],
            hide_index=True,
            width="stretch",
            height=min(42 + 36 * min(len(table), 8), 330),
            on_select=partial(_remember_violation_selection, table_key, selection_key, row_targets),
            selection_mode="single-row",
            key=table_key,
            alt=f"{label} IC-reference violations grouped by measurement, case and MM point.",
            column_config={
                "Over-limit area (kV·ranked-index s)": st.column_config.NumberColumn(format="%.4f"),
                "Peak excess (kV)": st.column_config.NumberColumn(format="%.2f"),
            },
        )
    plotted_data = pd.concat(plotted, ignore_index=True) if plotted else pd.DataFrame()
    metadata = {
        "View": "All envelopes",
        "Cases": cases,
        "MM points": mms,
        "Nominal voltage (kV)": voltage,
        "Channel": channel,
        "Index range (ranked index s)": index,
        "IC reference": reference,
        "IC changeover (s)": CHANGEOVER_S,
        "Safety factor": SAFETY_FACTOR,
        "LG source": project.source_names.get("lg", ""),
        "LL source": project.source_names.get("ll", ""),
        "MM workbook": project.source_names.get("mm", ""),
        "SA workbook": project.source_names.get("sa", ""),
        "_sa_data": project.sa,
    }
    _downloads(
        plotted_data,
        exceedances,
        reference_rows,
        project.issues,
        metadata,
        "voltage_detailed",
        report_figures,
    )


def _render_summary_view(
    project: ProjectData,
    signature: str,
    voltage: float,
    reference: str,
    cases: list[str],
    mms: list[str],
    index: tuple[float, float] | None,
    show_ic: bool,
    show_sa: bool,
    sa_by_mm: dict[str, list[str]],
    plot_container_width: int | None,
) -> None:
    st.subheader("Summary")
    st.caption("Highest LG and LL envelopes across the selected cases and MM points.")
    if not cases or not mms:
        st.info("Select at least one case and one MM point to display the summary.")
        return
    selected = {
        "LG": select_curves(project.lg, cases, mms, index, "Max_all"),
        "LL": select_curves(project.ll, cases, mms, index, "Max_all"),
    }
    maxima = {measurement: summary_envelope(frame, "Max_all") for measurement, frame in selected.items()}
    plotted: list[pd.DataFrame] = []
    report_figures: dict[str, go.Figure] = {}
    for measurement in ("LG", "LL"):
        envelope = maxima[measurement]
        if not envelope.empty:
            plotted.append(envelope.assign(Measurement=measurement))
        figure = build_envelope_figure(
            envelope,
            measurement,
            "Max_all",
            "summary",
            project.mm_blocks,
            reference,
            show_ic,
            project.sa,
            sa_by_mm if measurement == "LG" else {},
            f"{signature}|summary|{measurement}|{','.join(cases)}|{','.join(mms)}",
            reference_mms=mms,
            envelope_source=project.source_names.get(measurement.casefold(), ""),
            mm_source=project.source_names.get("mm", ""),
            plot_container_width=plot_container_width,
            show_sa=show_sa,
            x_range=index,
        )
        report_figures[measurement] = figure
        st.plotly_chart(
            figure,
            width="stretch",
            config={"displaylogo": False, "modeBarButtonsToRemove": ["toImage"]},
            alt=f"Maximum selected {measurement} representative envelope",
        )
    plotted_data = pd.concat(plotted, ignore_index=True) if plotted else pd.DataFrame()
    references = pd.concat(
        [crossing_summary(selected[m], project.mm_blocks, m, reference, "Max_all") for m in ("LG", "LL")],
        ignore_index=True,
    )
    summary_comparisons = pd.concat(
        [crossing_summary(maxima[m], project.mm_blocks, m, reference, "Max_all") for m in ("LG", "LL")],
        ignore_index=True,
    )
    summary_exceedances = summary_comparisons.loc[summary_comparisons["Ranked samples above reference"].gt(0)].copy()
    metadata = {
        "View": "Summary",
        "Cases": cases,
        "MM points": mms,
        "Nominal voltage (kV)": voltage,
        "Envelope channel": "Max_all",
        "Index range (ranked index s)": index,
        "IC reference": reference,
        "IC changeover (s)": CHANGEOVER_S,
        "Safety factor": SAFETY_FACTOR,
        "LG source": project.source_names.get("lg", ""),
        "LL source": project.source_names.get("ll", ""),
        "MM workbook": project.source_names.get("mm", ""),
        "SA workbook": project.source_names.get("sa", ""),
        "_sa_data": project.sa,
    }
    _downloads(
        plotted_data,
        summary_exceedances,
        references,
        project.issues,
        metadata,
        "voltage_summary",
        report_figures,
    )


def _render_data_references(project: ProjectData, signature: str) -> None:
    st.subheader("Data & references")
    st.caption("Source files, project conventions, SA references and validation are collected here.")
    source_rows, derived_rows, sa_point_counts, issues = cached_reference_display_data(project, signature)
    st.dataframe(source_rows, hide_index=True, width="stretch")
    st.caption("IC references use the MM_blocks sheet. WLs.xlsx is not used.")
    if project.mm_blocks is None:
        st.warning("No workbook with an MM_blocks sheet is loaded.")
    else:
        st.markdown("#### IC convention from MM_blocks")
        st.caption("For LG and LL independently: index < 0.020 s uses SIWL (kV peak); index ≥ 0.020 s uses SDPF assumed kV RMS × √2. Safety-margin reference = withstand peak / 1.15. This is a project plotting convention, not a universal standard or compliance result.")
        with st.expander(f"MM_blocks catalogue ({len(project.mm_blocks)} configured MM points)", expanded=False):
            st.dataframe(project.mm_blocks, hide_index=True, width="stretch")
        with st.expander("Derived LG and LL IC reference values", expanded=False):
            st.dataframe(derived_rows, hide_index=True, width="stretch")

    st.markdown("#### Surge-arrester references")
    if project.sa is None:
        st.caption("No SA.xlsx or SA_*.xlsx was supplied. IC references remain available.")
    else:
        if project.sa.kind == "new":
            st.caption("SA curve values are plotted in kV peak. Only the exact MM mapping and supplied curve points are used.")
        else:
            st.warning("The selected SA workbook needs a valid SA_Curves sheet and exact MM_Assignment mapping. Check validation below.")
        if not project.sa.assignments.empty:
            with st.expander("MM assignments", expanded=False):
                st.dataframe(project.sa.assignments, hide_index=True, width="stretch")
        if project.sa.kind == "new":
            st.dataframe(sa_point_counts, hide_index=True, width="stretch")
        elif not project.sa.curves.empty:
            with st.expander("Parsed SA source values", expanded=False):
                st.dataframe(project.sa.curves, hide_index=True, width="stretch", height=360)
    with st.expander("SA workbook template", expanded=False):
        st.download_button("Download SA template", create_blank_template, "SA_template.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="sa_template_download")
    st.markdown("#### Validation")
    _issue_summary(issues)


def main() -> None:
    st.title("Voltage Envelopes")
    project, signature = _source_panel()
    tabs = st.tabs(
        ["Summary", "All envelopes", "Data & references"],
        default="Summary",
        key="primary_tabs",
        on_change="rerun",
    )
    active_tab_index = next((index for index, tab in enumerate(tabs) if tab.open), 0)
    has_dashboard_data = all(
        frame is not None and not frame.empty
        for frame in (project.lg, project.ll, project.mm_blocks)
    )
    if has_dashboard_data:
        plot_container_width = _measure_plot_container_width() if active_tab_index < 2 else None
        voltage, reference, cases_available, mms_available = _view_controls(project, signature)
    else:
        plot_container_width = None
        voltage, reference = float("nan"), "Safety margin"
        cases, mms = [], []
        controls = {
            "index": None,
            "channel": "Max_all",
            "show_ic": False,
            "show_sa": False,
            "sa_by_mm": {},
            "selected_curves": {},
        }
    blocking_result = _blocking_result(project)
    if has_dashboard_data:
        if active_tab_index < 2:
            with tabs[active_tab_index]:
                cases, mms = _main_selection_controls(project, voltage, cases_available, mms_available)
        else:
            previous_cases = st.session_state.get("selected_cases", cases_available)
            cases = [case for case in previous_cases if case in cases_available]
            voltage_mms = mms_at_voltage(project.mm_blocks, mms_available, voltage)
            previous_mms = st.session_state.get("selected_mms", voltage_mms)
            mms = [mm for mm in previous_mms if mm in voltage_mms]
        controls = _sidebar_controls(
            project,
            signature,
            active_tab_index < 2,
            active_tab_index == 1,
            voltage,
            cases,
            mms,
        )

    with tabs[active_tab_index]:
        if active_tab_index == 0:
            if blocking_result:
                st.info(_blocking_result_message(project, "the summary"))
            else:
                _render_summary_view(
                    project,
                    signature,
                    voltage,
                    reference,
                    cases,
                    mms,
                    controls["index"],
                    controls["show_ic"],
                    controls["show_sa"],
                    controls["sa_by_mm"],
                    plot_container_width,
                )
        elif active_tab_index == 1:
            if blocking_result:
                st.info(_blocking_result_message(project, "individual envelopes"))
            else:
                _render_detailed_view(
                    project,
                    signature,
                    voltage,
                    reference,
                    cases,
                    mms,
                    controls["index"],
                    controls["channel"],
                    controls["show_ic"],
                    controls["show_sa"],
                    controls["sa_by_mm"],
                    controls["selected_curves"],
                    plot_container_width,
                )
        else:
            _render_data_references(project, signature)


if __name__ == "__main__":
    main()
