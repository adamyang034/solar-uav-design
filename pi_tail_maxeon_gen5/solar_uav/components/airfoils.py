"""Phase 2 — Airfoil aerodynamic models via NeuralFoil / AeroSandbox.

Candidates (user): S4110, S4310 (current baseline), AG35 for the main wing;
NACA 0010 for both tails. Re range of interest: 100k-200k.

Everything returns AeroSandbox-native objects (asb.Airfoil) and plain
DataFrames of polars, so the Phase 3/4 optimization can consume them
directly (asb.Airfoil carries NeuralFoil access internally).
"""

from __future__ import annotations

from pathlib import Path

import aerosandbox as asb
import numpy as np
import pandas as pd

WING_CANDIDATES = ["s4110", "s4310", "ag35"]
TAIL_AIRFOIL = "naca0010"
RE_GRID = [50e3, 100e3, 150e3, 200e3, 300e3]
ALPHA_GRID = np.arange(-6.0, 16.01, 0.25)
NEURALFOIL_MODEL = "xlarge"

POLAR_DIR = Path(__file__).resolve().parents[2] / "data" / "polars"


def get_airfoil(name: str) -> asb.Airfoil:
    """UIUC-database airfoil (or NACA) as an AeroSandbox object."""
    af = asb.Airfoil(name)
    if af.coordinates is None:
        raise ValueError(f"Airfoil {name!r} not found in AeroSandbox database")
    return af.repanel(n_points_per_side=100)


def polar(af: asb.Airfoil,
          alphas: np.ndarray = ALPHA_GRID,
          reynolds: list[float] = RE_GRID,
          model_size: str = NEURALFOIL_MODEL) -> pd.DataFrame:
    """NeuralFoil polar sweep. Includes NeuralFoil's own confidence metric
    ('analysis_confidence') — treat rows below ~0.8 with suspicion."""
    frames = []
    for re_ in reynolds:
        aero = af.get_aero_from_neuralfoil(
            alpha=alphas, Re=re_, mach=0.0, model_size=model_size)
        frames.append(pd.DataFrame({
            "airfoil": af.name,
            "re": re_,
            "alpha_deg": alphas,
            "cl": aero["CL"],
            "cd": aero["CD"],
            "cm": aero["CM"],
            "confidence": aero["analysis_confidence"],
        }))
    return pd.concat(frames, ignore_index=True)


def cruise_figures(df: pd.DataFrame) -> pd.DataFrame:
    """Per (airfoil, Re): max L/D and max CL^1.5/CD (min-power flight),
    the two numbers that matter for a solar loiterer."""
    rows = []
    for (name, re_), g in df.groupby(["airfoil", "re"]):
        ld = g["cl"] / g["cd"]
        pw = np.where(g["cl"] > 0, g["cl"] ** 1.5 / g["cd"], 0.0)
        rows.append({
            "airfoil": name,
            "re": re_,
            "ld_max": float(ld.max()),
            "alpha_ld_max": float(g["alpha_deg"].iloc[int(np.argmax(ld))]),
            "cl32_cd_max": float(pw.max()),
            "alpha_cl32_max": float(g["alpha_deg"].iloc[int(np.argmax(pw))]),
            "cl_max": float(g["cl"].max()),
        })
    return pd.DataFrame(rows)


def generate_all(save: bool = True) -> pd.DataFrame:
    """Polars for all candidate airfoils; cached to data/polars/*.csv."""
    POLAR_DIR.mkdir(parents=True, exist_ok=True)
    frames = []
    for name in WING_CANDIDATES + [TAIL_AIRFOIL]:
        cache = POLAR_DIR / f"{name}.csv"
        if cache.exists():
            frames.append(pd.read_csv(cache))
            continue
        df = polar(get_airfoil(name))
        if save:
            df.to_csv(cache, index=False)
        frames.append(df)
    return pd.concat(frames, ignore_index=True)
