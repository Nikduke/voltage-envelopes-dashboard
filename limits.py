"""Project-specific insulation-coordination references."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


CHANGEOVER_S = 0.020
SAFETY_FACTOR = 1.15


def ic_values(mm_row: pd.Series | dict[str, object], measurement: str) -> dict[str, float]:
    """Return the source and derived LG or LL withstand values in kV peak."""
    if measurement not in {"LG", "LL"}:
        raise ValueError("measurement must be 'LG' or 'LL'")
    siwl = float(mm_row[f"SIWL_{measurement}"])
    sdpf_rms = float(mm_row[f"SDPF_{measurement}"])
    sdpf_peak = sdpf_rms * math.sqrt(2.0)
    return {
        "SIWL_peak": siwl,
        "SIWL_margin_peak": siwl / SAFETY_FACTOR,
        "SDPF_input": sdpf_rms,
        "SDPF_peak": sdpf_peak,
        "SDPF_margin_peak": sdpf_peak / SAFETY_FACTOR,
    }


def ic_curve(
    mm_row: pd.Series | dict[str, object], measurement: str, index_s: np.ndarray, reference: str
) -> np.ndarray:
    """Build the 20 ms project reference at supplied ranked indices.

    `reference` is `Withstand` or `Safety margin`. The x values are the CSV's
    representative-envelope index; they are not asserted to be exposure time.
    """
    values = ic_values(mm_row, measurement)
    use_siwl = np.asarray(index_s, dtype=float) < CHANGEOVER_S
    raw = np.where(use_siwl, values["SIWL_peak"], values["SDPF_peak"])
    if reference == "Withstand":
        return raw
    if reference == "Safety margin":
        return raw / SAFETY_FACTOR
    raise ValueError("reference must be 'Withstand' or 'Safety margin'")


def reference_label(reference: str) -> str:
    if reference == "Withstand":
        return "Withstand reference crossing"
    if reference == "Safety margin":
        return "Safety-margin reference crossing"
    return "Reference comparison"
