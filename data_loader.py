"""Read-only discovery and normalisation for voltage-envelope source files."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import time
from zipfile import BadZipFile, ZipFile

import pandas as pd

from sa_data import SAData, load_sa_workbook, validate_sa_compatibility
from validation import make_issue, validate_cross_sources, validate_envelope, validate_mm_blocks


SOURCE_ROLES = ("lg", "ll", "mm", "sa")
SKIP_ARCHIVE_DIRS = {".git", ".venv", "__pycache__", "__macosx", "graphify-out", "templates", "tests", "docs", "exports", "uploads", "output"}


@dataclass(frozen=True)
class SourceCandidate:
    role: str
    filename: str
    origin: str
    path: Path | None = None
    data: bytes | None = None
    content_digest: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        digest = sha256(self.data or b"").hexdigest() if self.path is None else ""
        object.__setattr__(self, "content_digest", digest)

    @property
    def label(self) -> str:
        return f"{self.filename} · {self.origin}"

    @property
    def identity(self) -> str:
        if self.path is not None:
            return f"{self.role}|{self.origin}|{self.path.resolve()}"
        return f"{self.role}|{self.origin}|{self.filename}|{self.content_digest}"

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
        if stem.startswith(("input_data_pscad_python_v11", "input_data_pscad_python_0.11")) or "mm_blocks" in stem:
            return "mm"
        if suffix == ".xlsx" and (stem == "sa" or stem.startswith("sa_")):
            return "sa"
    return None


def discover_sources(
    uploads: list[tuple[str, bytes]] | None = None,
) -> dict[str, list[SourceCandidate]]:
    """Find supported inputs from one ZIP or a set of separately uploaded files."""
    candidates: dict[str, list[SourceCandidate]] = {role: [] for role in SOURCE_ROLES}
    uploaded_files = list(uploads or [])
    zip_files = [(filename, data) for filename, data in uploaded_files if Path(filename).suffix.casefold() == ".zip"]
    if len(zip_files) > 1 or (zip_files and len(uploaded_files) > 1):
        raise ValueError("Upload either one project ZIP or the individual CSV/XLSX files, not both.")

    for filename, data in uploaded_files:
        if Path(filename).suffix.casefold() == ".zip":
            try:
                with ZipFile(BytesIO(data)) as archive:
                    for member in archive.infolist():
                        parts = Path(member.filename.replace("\\", "/")).parts
                        if (
                            member.is_dir()
                            or member.filename.startswith("~$")
                            or any(part.casefold() in SKIP_ARCHIVE_DIRS or part.startswith(".") for part in parts[:-1])
                        ):
                            continue
                        member_name = Path(member.filename).name
                        role = classify_filename(member_name)
                        if role:
                            candidates[role].append(
                                SourceCandidate(role, member_name, "Project ZIP", data=archive.read(member))
                            )
            except BadZipFile as exc:
                raise ValueError(f"{filename} is not a valid ZIP archive.") from exc
            continue
        role = classify_filename(filename)
        if role:
            candidates[role].append(SourceCandidate(role, Path(filename).name, "Uploaded", data=bytes(data)))
    for role in candidates:
        candidates[role].sort(key=lambda candidate: (candidate.filename.casefold(), candidate.origin))
    return candidates


def source_signature(selected: dict[str, SourceCandidate | None]) -> str:
    """Key cached data to the selected source content or path/size/mtime."""
    parts: list[str] = []
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
            duplicate_rows = int(frame.duplicated().sum())
            if duplicate_rows:
                frame = frame.drop_duplicates(keep="first").reset_index(drop=True)
                data.issues.append(
                    make_issue(
                        "Warning",
                        label,
                        "exact_duplicate_rows_removed",
                        f"{duplicate_rows:,} exact duplicate rows were removed; the retained measurements are unchanged.",
                    )
                )
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

    data.issues.extend(validate_cross_sources(data.lg, data.ll, data.mm_blocks, data.input_meta))
    data.load_seconds = time.perf_counter() - started
    return data
