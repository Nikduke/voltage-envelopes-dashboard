"""Read-only discovery and normalisation for voltage-envelope source files."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import time
from typing import Any

import pandas as pd

from sa_data import SAData, load_sa_workbook, validate_sa_compatibility
from validation import make_issue, validate_cross_sources, validate_envelope, validate_mm_blocks


SOURCE_ROLES = ("lg", "ll", "mm", "sa", "wl", "dashboard")
SKIP_DIRS = {".git", ".venv", "__pycache__", "graphify-out", "templates", "tests", "docs", "exports", "uploads", "output"}


@dataclass(frozen=True)
class SourceCandidate:
    role: str
    filename: str
    origin: str
    path: Path | None = None
    data: bytes | None = None

    @property
    def label(self) -> str:
        return f"{self.filename} · {self.origin}"

    @property
    def identity(self) -> str:
        if self.path is not None:
            return f"{self.role}|{self.origin}|{self.path.resolve()}"
        content_hash = sha256(self.data or b"").hexdigest()
        return f"{self.role}|{self.origin}|{self.filename}|{content_hash}"

    def source(self) -> Path | BytesIO:
        if self.path is not None:
            return self.path
        return BytesIO(self.data or b"")


@dataclass
class ProjectData:
    lg: pd.DataFrame | None = None
    ll: pd.DataFrame | None = None
    mm_blocks: pd.DataFrame | None = None
    input_meta: dict[str, object] = field(default_factory=dict)
    sa: SAData | None = None
    legacy_wl: pd.DataFrame | None = None
    source_names: dict[str, str] = field(default_factory=dict)
    source_origins: dict[str, str] = field(default_factory=dict)
    issues: list[dict[str, object]] = field(default_factory=list)
    loaded_at: datetime | None = None
    load_seconds: float = 0.0


def classify_filename(filename: str) -> str | None:
    name = Path(filename).name.casefold()
    stem = Path(name).stem
    suffix = Path(name).suffix.casefold()
    if suffix == ".csv":
        if "lgp" in stem:
            return "lg"
        if "llp" in stem:
            return "ll"
    if suffix in {".xlsx", ".xlsm"}:
        if stem.startswith("input_data_pscad_python_v11") or "mm_blocks" in stem:
            return "mm"
        if stem.startswith("sa_characteristics") or stem.startswith("sas"):
            return "sa"
        if stem.startswith("wls"):
            return "wl"
        if stem.startswith("voltage_envelope_dashboard"):
            return "dashboard"
    return None


def discover_sources(
    folder: str | Path, uploads: list[tuple[str, bytes]] | None = None
) -> dict[str, list[SourceCandidate]]:
    """Find plausible sources. Multiple candidates stay visible for selection."""
    candidates: dict[str, list[SourceCandidate]] = {role: [] for role in SOURCE_ROLES}
    root = Path(folder).expanduser() if str(folder).strip() else None
    if root is not None and root.is_dir():
        for path in sorted(root.rglob("*"), key=lambda item: str(item).casefold()):
            if not path.is_file() or any(part.casefold() in SKIP_DIRS or part.startswith(".") for part in path.relative_to(root).parts[:-1]):
                continue
            if path.name.startswith("~$"):
                continue
            role = classify_filename(path.name)
            if role:
                candidates[role].append(SourceCandidate(role, path.name, "Folder", path=path))
    for filename, data in uploads or []:
        role = classify_filename(filename)
        if role:
            candidates[role].append(SourceCandidate(role, filename, "Session upload", data=bytes(data)))
    for role in candidates:
        candidates[role].sort(key=lambda candidate: (candidate.filename.casefold(), candidate.origin))
    return candidates


def source_signature(selected: dict[str, SourceCandidate | None], folder: str | Path) -> str:
    """Key cached data to selected source content or path/size/mtime."""
    parts = [str(Path(folder).expanduser().resolve())]
    for role in SOURCE_ROLES:
        candidate = selected.get(role)
        if candidate is None:
            parts.append(f"{role}=missing")
        elif candidate.path is not None:
            try:
                stat = candidate.path.stat()
                parts.append(f"{candidate.identity}|{stat.st_size}|{stat.st_mtime_ns}")
            except OSError as exc:
                parts.append(f"{candidate.identity}|{exc}")
        else:
            parts.append(candidate.identity)
    return sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _read_csv(candidate: SourceCandidate) -> pd.DataFrame:
    if candidate.path is not None:
        return pd.read_csv(candidate.path)
    return pd.read_csv(BytesIO(candidate.data or b""))


def _excel_file(candidate: SourceCandidate) -> pd.ExcelFile:
    return pd.ExcelFile(candidate.source(), engine="openpyxl")


def _read_mm_workbook(candidate: SourceCandidate) -> tuple[pd.DataFrame, dict[str, object]]:
    with _excel_file(candidate) as workbook:
        if "MM_blocks" not in workbook.sheet_names:
            raise ValueError("The input workbook has no MM_blocks worksheet.")
        mm = pd.read_excel(workbook, sheet_name="MM_blocks")
        input_meta: dict[str, object] = {}
        if "Input_Data" in workbook.sheet_names:
            raw = pd.read_excel(workbook, sheet_name="Input_Data", header=None)
            for _, row in raw.iloc[:, :2].iterrows():
                if len(row) < 2 or pd.isna(row.iloc[0]) or pd.isna(row.iloc[1]):
                    continue
                key = str(row.iloc[0]).strip().casefold()
                if key and key not in {"parameter", "study type", "input parameters pre snapshot", "input parameters post snapshot"}:
                    input_meta[key] = row.iloc[1]
    mm.columns = [str(column).strip() for column in mm.columns]
    for column in mm.columns:
        if column != "Group":
            mm[column] = pd.to_numeric(mm[column], errors="coerce")
    return mm, input_meta


def _read_legacy_wl(candidate: SourceCandidate) -> pd.DataFrame:
    with _excel_file(candidate) as workbook:
        frame = pd.read_excel(workbook, sheet_name=0)
    frame.columns = [str(column).strip() for column in frame.columns]
    return frame


def load_project_data(selected: dict[str, SourceCandidate | None]) -> ProjectData:
    """Read selected inputs, validate them and return a detached snapshot."""
    started = time.perf_counter()
    data = ProjectData()
    data.loaded_at = datetime.now().astimezone()
    for role, candidate in selected.items():
        if candidate is not None:
            data.source_names[role] = candidate.filename
            data.source_origins[role] = candidate.origin

    for role, label in (("lg", "LG CSV"), ("ll", "LL CSV")):
        candidate = selected.get(role)
        if candidate is None:
            data.issues.append(make_issue("Error", label, "source_not_selected", f"Select a {label} file.", blocking=True))
            continue
        try:
            frame = _read_csv(candidate)
            for column in ("Time (s)", "Max_A", "Max_B", "Max_C", "Max_all", "Run"):
                if column in frame.columns:
                    frame[column] = pd.to_numeric(frame[column], errors="coerce")
            setattr(data, role, frame)
            data.issues.extend(validate_envelope(frame, label))
        except Exception as exc:
            data.issues.append(make_issue("Error", label, "read_error", f"Could not read {candidate.filename}: {exc}", blocking=True))

    mm_candidate = selected.get("mm")
    if mm_candidate is None:
        data.issues.extend(validate_mm_blocks(None))
    else:
        try:
            data.mm_blocks, data.input_meta = _read_mm_workbook(mm_candidate)
            data.issues.extend(validate_mm_blocks(data.mm_blocks))
        except Exception as exc:
            data.issues.append(make_issue("Error", "MM workbook", "read_error", f"Could not read {mm_candidate.filename}: {exc}"))

    sa_candidate = selected.get("sa")
    if sa_candidate is not None:
        data.sa = load_sa_workbook(sa_candidate.source() if sa_candidate.path is not None else sa_candidate.data or b"", sa_candidate.filename)
        data.issues.extend(data.sa.issues)
        data.issues.extend(validate_sa_compatibility(data.sa, data.mm_blocks))

    wl_candidate = selected.get("wl")
    if wl_candidate is not None:
        try:
            data.legacy_wl = _read_legacy_wl(wl_candidate)
            required = {"Time (s)", "System", "IC limit"}
            missing = required - set(data.legacy_wl.columns)
            if missing:
                data.issues.append(make_issue("Warning", "Legacy WLs", "missing_legacy_wl_columns", f"Legacy WLs is missing {', '.join(sorted(missing))}; it will not be plotted."))
            else:
                data.legacy_wl["Time (s)"] = pd.to_numeric(data.legacy_wl["Time (s)"], errors="coerce")
                data.legacy_wl["IC limit"] = pd.to_numeric(data.legacy_wl["IC limit"], errors="coerce")
        except Exception as exc:
            data.issues.append(make_issue("Warning", "Legacy WLs", "read_error", f"Could not read optional legacy WLs: {exc}"))

    data.issues.extend(validate_cross_sources(data.lg, data.ll, data.mm_blocks, data.input_meta))
    data.load_seconds = time.perf_counter() - started
    return data
