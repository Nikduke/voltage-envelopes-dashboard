"""Exports for currently selected envelope data and Plotly figures."""

from __future__ import annotations

from io import BytesIO
from typing import Any

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill


ASSESSMENT_NOTE = "Reference comparison on envelope index"


def export_xlsx_bytes(
    selected: pd.DataFrame,
    summary: pd.DataFrame,
    references: pd.DataFrame,
    validation: pd.DataFrame,
    metadata: dict[str, Any],
    sa_curves: pd.DataFrame | None = None,
    sa_assignments: pd.DataFrame | None = None,
) -> bytes:
    """Build selected results with provenance and supplied SA source values."""
    metadata_frame = pd.DataFrame(
        [{"Field": str(key), "Value": ", ".join(map(str, value)) if isinstance(value, (list, tuple, set)) else str(value)} for key, value in metadata.items()]
        + [{"Field": "Assessment status", "Value": ASSESSMENT_NOTE}]
    )
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        selected.to_excel(writer, sheet_name="Selected data", index=False)
        summary.to_excel(writer, sheet_name="Limit exceedances", index=False)
        references.to_excel(writer, sheet_name="Reference comparison", index=False)
        validation.to_excel(writer, sheet_name="Validation", index=False)
        metadata_frame.to_excel(writer, sheet_name="Metadata", index=False)
        if sa_curves is not None and sa_assignments is not None:
            sa_curves.to_excel(writer, sheet_name="SA source points", index=False)
            sa_assignments.to_excel(writer, sheet_name="SA assignments", index=False)
        for worksheet in writer.sheets.values():
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
    return buffer.getvalue()
