"""Exports for currently selected envelope data and Plotly figures."""

from __future__ import annotations

from io import BytesIO
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill


ASSESSMENT_NOTE = "Ranked-index reference comparison only; not a chronological TOV/compliance assessment."


def selected_csv_bytes(data: pd.DataFrame, metadata: dict[str, Any]) -> bytes:
    frame = data.copy()
    for key, value in metadata.items():
        if isinstance(value, (list, tuple, set)):
            value = ", ".join(map(str, value))
        frame[f"_Metadata_{key}"] = value
    if "Assessment_Status" not in frame:
        frame["Assessment_Status"] = ASSESSMENT_NOTE
    return frame.to_csv(index=False).encode("utf-8-sig")


def export_xlsx_bytes(
    selected: pd.DataFrame,
    summary: pd.DataFrame,
    references: pd.DataFrame,
    validation: pd.DataFrame,
    metadata: dict[str, Any],
) -> bytes:
    """Build a multi-sheet export with a compact provenance sheet."""
    metadata_frame = pd.DataFrame(
        [{"Field": str(key), "Value": ", ".join(map(str, value)) if isinstance(value, (list, tuple, set)) else str(value)} for key, value in metadata.items()]
        + [{"Field": "Assessment status", "Value": ASSESSMENT_NOTE}]
    )
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        selected.to_excel(writer, sheet_name="Selected data", index=False)
        summary.to_excel(writer, sheet_name="Envelope summary", index=False)
        references.to_excel(writer, sheet_name="Reference comparison", index=False)
        validation.to_excel(writer, sheet_name="Validation", index=False)
        metadata_frame.to_excel(writer, sheet_name="Metadata", index=False)
    buffer.seek(0)
    workbook = load_workbook(buffer)
    for worksheet in workbook.worksheets:
        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = worksheet.dimensions
        worksheet.sheet_view.showGridLines = False
        for cell in worksheet[1]:
            cell.font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="1F4E78")
            cell.alignment = Alignment(vertical="center", wrap_text=True)
        worksheet.row_dimensions[1].height = 28
        for column_cells in worksheet.columns:
            letter = column_cells[0].column_letter
            width = max((len(str(cell.value)) for cell in column_cells if cell.value is not None), default=10)
            worksheet.column_dimensions[letter].width = min(max(width + 2, 12), 48)
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def figure_image_bytes(figure: go.Figure, image_format: str = "png") -> bytes:
    if image_format not in {"png", "svg"}:
        raise ValueError("image_format must be png or svg")
    return figure.to_image(format=image_format, width=figure.layout.width or 1400, height=figure.layout.height or 500, scale=1)
