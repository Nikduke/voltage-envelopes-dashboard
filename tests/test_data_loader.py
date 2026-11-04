from pathlib import Path
import os
from tempfile import TemporaryDirectory

from data_loader import SourceCandidate, discover_sources, source_signature


def test_discovery_keeps_multiple_candidates_explicit_and_skips_output_dirs():
    root = Path(__file__).resolve().parents[1] / ".test-temp"
    root.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=root) as work:
        folder = Path(work)
        (folder / "LGp.csv").write_text("one", encoding="utf-8")
        (folder / "LGp_revised.csv").write_text("two", encoding="utf-8")
        (folder / "exports").mkdir()
        (folder / "exports" / "LGp_export.csv").write_text("skip", encoding="utf-8")
        candidates = discover_sources(folder)
        assert [candidate.filename for candidate in candidates["lg"]] == ["LGp.csv", "LGp_revised.csv"]
        assert candidates["ll"] == []


def test_source_signature_changes_for_file_replacement_and_upload_content():
    root = Path(__file__).resolve().parents[1] / ".test-temp"
    root.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=root) as work:
        folder = Path(work)
        path = folder / "LGp.csv"
        path.write_text("first", encoding="utf-8")
        candidate = SourceCandidate("lg", path.name, "Folder", path=path)
        first = source_signature({"lg": candidate}, folder)
        path.write_text("other", encoding="utf-8")
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000_000))
        second = source_signature({"lg": candidate}, folder)
        assert first != second
        upload_a = SourceCandidate("lg", "LGp.csv", "Session upload", data=b"csv-A")
        upload_b = SourceCandidate("lg", "LGp.csv", "Session upload", data=b"csv-B")
        assert source_signature({"lg": upload_a}, folder) != source_signature({"lg": upload_b}, folder)


def test_mm_workbook_can_be_replaced_after_loading():
    root = Path(__file__).resolve().parents[1] / ".test-temp"
    root.mkdir(exist_ok=True)
    source_root = Path(__file__).resolve().parents[2] / "02_Excel_Example"
    source = discover_sources(source_root)["mm"][0].path
    assert source is not None
    with TemporaryDirectory(dir=root) as work:
        folder = Path(work)
        path = folder / source.name
        path.write_bytes(source.read_bytes())
        candidate = SourceCandidate("mm", path.name, "Folder", path=path)
        from data_loader import load_project_data

        loaded = load_project_data({"mm": candidate})
        assert loaded.mm_blocks is not None and len(loaded.mm_blocks) == 31
        moved = folder / "replaced.xlsx"
        path.replace(moved)
        assert moved.exists() and not path.exists()
