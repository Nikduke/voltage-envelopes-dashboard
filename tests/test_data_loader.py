from io import BytesIO
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from analysis import available_mms, nominal_voltages
from data_loader import SourceCandidate, classify_filename, discover_sources, load_project_data, source_signature


def _zip(files: dict[str, bytes]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


def test_zip_discovery_keeps_multiple_candidates_and_skips_export_directories():
    archive = _zip(
        {
            "Project/LGp.csv": b"case,data",
            "Project/LGp_revised.csv": b"case,data2",
            "Project/LLp.csv": b"case,data",
            "Project/Input_Data_PSCAD_Python_v11.xlsx": b"workbook",
            "Project/SA.xlsx": b"sa",
            "exports/LGp_export.csv": b"export",
        }
    )
    candidates = discover_sources([("project.zip", archive)])
    assert [candidate.filename for candidate in candidates["lg"]] == ["LGp.csv", "LGp_revised.csv"]
    assert [candidate.filename for candidate in candidates["ll"]] == ["LLp.csv"]
    assert candidates["mm"][0].filename == "Input_Data_PSCAD_Python_v11.xlsx"
    assert candidates["sa"][0].filename == "SA.xlsx"


def test_discovery_accepts_individual_uploaded_csv_and_excel_files():
    files = [
        ("LGp.csv", b"Time (s),Max_all\n0,10\n"),
        ("LLp.csv", b"Time (s),Max_all\n0,11\n"),
        ("Input_Data_PSCAD_Python_v11.xlsx", b"workbook"),
        ("SA.xlsx", b"SA workbook"),
    ]

    candidates = discover_sources(files)

    assert candidates["lg"][0].origin == "Uploaded"
    assert candidates["lg"][0].data == files[0][1]
    assert candidates["ll"][0].filename == "LLp.csv"
    assert candidates["mm"][0].filename == "Input_Data_PSCAD_Python_v11.xlsx"
    assert candidates["sa"][0].filename == "SA.xlsx"


def test_mm_workbook_filename_accepts_both_011_and_v11_versions():
    assert classify_filename("Input_Data_PSCAD_Python_0.11.xlsx") == "mm"
    assert classify_filename("Input_Data_PSCAD_Python_v11.xlsx") == "mm"


def test_discovery_rejects_zip_mixed_with_individual_uploads():
    with pytest.raises(ValueError, match="either one project ZIP or the individual"):
        discover_sources([("project.zip", _zip({})), ("LGp.csv", b"case,data")])


def test_zip_discovery_requires_production_sa_filename_and_ignores_legacy_wl():
    archive = _zip(
        {
            "Project/SAs(1).xlsx": b"old name",
            "Project/SAs.xlsx": b"legacy",
            "Project/WLs.xlsx": b"legacy",
            "Project/SA_final.xlsx": b"new SA",
        }
    )
    candidates = discover_sources([("project.zip", archive)])
    assert [candidate.filename for candidate in candidates["sa"]] == ["SA_final.xlsx"]
    assert classify_filename("SAs(1).xlsx") is None
    assert classify_filename("SAs.xlsx") is None
    assert classify_filename("WLs.xlsx") is None


def test_invalid_zip_reports_a_clear_input_error():
    with pytest.raises(ValueError, match="not a valid ZIP archive"):
        discover_sources([("project.zip", b"not a zip")])


def test_load_removes_only_exact_duplicate_rows_and_blocks_conflicting_curve_indexes():
    header = "Time (s),Max_A,Max_B,Max_C,MM_name_A,MM_name_B,MM_name_C,Max_all,Case,Run,Fault_type,MM_name_all"
    source_row = "0,100,90,80,MM_A,MM_A,MM_A,100,Case 1,1,AG,MM_A"
    exact = (header + "\n" + source_row + "\n" + source_row + "\n").encode("utf-8")
    inputs = {
        role: SourceCandidate(role, f"{role.upper()}p.csv", "Uploaded", data=exact)
        for role in ("lg", "ll")
    }

    loaded = load_project_data(inputs)

    assert len(loaded.lg) == len(loaded.ll) == 1
    cleaned = [issue for issue in loaded.issues if issue["Code"] == "exact_duplicate_rows_removed"]
    assert len(cleaned) == 2
    assert all(not issue["Blocking"] for issue in cleaned)
    assert not any(issue["Code"] == "duplicate_curve_index" for issue in loaded.issues)

    conflicting = (header + "\n" + source_row + "\n" + source_row.replace(",100,Case 1", ",101,Case 1") + "\n").encode("utf-8")
    invalid = load_project_data({
        role: SourceCandidate(role, f"{role.upper()}p.csv", "Uploaded", data=conflicting)
        for role in ("lg", "ll")
    })
    assert sum(issue["Code"] == "duplicate_curve_index" and issue["Blocking"] for issue in invalid.issues) == 2


def test_05_project_zip_loads_the_011_workbook_and_current_sa_source():
    root = Path(__file__).resolve().parents[2] / "05_Test_data"
    rewritten = BytesIO()
    with ZipFile(rewritten, "w", ZIP_DEFLATED) as project:
        for path in root.iterdir():
            if not path.is_file() or path.suffix.casefold() not in {".csv", ".xlsx"}:
                continue
            name = path.name.replace(
                "Input_Data_PSCAD_Python_v11.xlsx",
                "Input_Data_PSCAD_Python_0.11.xlsx",
            )
            project.writestr(f"Project/{name}", path.read_bytes())

    candidates = discover_sources([("project.zip", rewritten.getvalue())])
    assert [candidate.filename for candidate in candidates["mm"]] == ["Input_Data_PSCAD_Python_0.11.xlsx"]
    project_data = load_project_data({
        role: files[0] if len(files) == 1 else None
        for role, files in candidates.items()
    })

    assert project_data.lg is not None and len(project_data.lg) == 133_000
    assert project_data.ll is not None and len(project_data.ll) == 133_000
    assert project_data.lg["Case"].nunique() == project_data.ll["Case"].nunique() == 8
    assert project_data.lg["MM_name_all"].nunique() == project_data.ll["MM_name_all"].nunique() == 67
    assert project_data.mm_blocks is not None
    assert len(project_data.mm_blocks) == 68
    assert project_data.sa is not None and project_data.sa.kind == "new"
    assert set(project_data.sa.curves["SA_ID"]) == {"66 WTT SA"}
    assert nominal_voltages(project_data.mm_blocks, available_mms(project_data.lg, project_data.ll)) == [33.0, 66.0, 230.0, 380.0]
    assert not any(issue["Blocking"] and issue["Area"] in {"LG CSV", "LL CSV"} for issue in project_data.issues)
    duplicate_notices = [issue for issue in project_data.issues if issue["Code"] == "exact_duplicate_rows_removed"]
    assert not duplicate_notices


def test_source_signature_changes_for_file_replacement_and_upload_content():
    root = Path(__file__).resolve().parents[1] / ".test-temp"
    root.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=root) as work:
        folder = Path(work)
        path = folder / "LGp.csv"
        path.write_text("first", encoding="utf-8")
        candidate = SourceCandidate("lg", path.name, "Test", path=path)
        first = source_signature({"lg": candidate})
        path.write_text("other", encoding="utf-8")
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000_000))
        second = source_signature({"lg": candidate})
        assert first != second
        upload_a = SourceCandidate("lg", "LGp.csv", "Uploaded", data=b"csv-A")
        upload_b = SourceCandidate("lg", "LGp.csv", "Uploaded", data=b"csv-B")
        assert source_signature({"lg": upload_a}) != source_signature({"lg": upload_b})


def test_mm_workbook_can_be_replaced_after_loading():
    root = Path(__file__).resolve().parents[1] / ".test-temp"
    root.mkdir(exist_ok=True)
    source = Path(__file__).resolve().parents[2] / "04_Test_data" / "Input_Data_PSCAD_Python_v11.xlsx"
    assert source.exists()
    with TemporaryDirectory(dir=root) as work:
        folder = Path(work)
        path = folder / source.name
        path.write_bytes(source.read_bytes())
        candidate = SourceCandidate("mm", path.name, "Test", path=path)
        loaded = load_project_data({"mm": candidate})
        assert loaded.mm_blocks is not None and len(loaded.mm_blocks) == 31
        moved = folder / "replaced.xlsx"
        path.replace(moved)
        assert moved.exists() and not path.exists()
