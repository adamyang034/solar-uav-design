"""Unswept Fourier lifting-line for a twisted, tapered wing.

Prandtl / Anderson collocation on the half-span (odd sine modes). Used
only when geometric washout is nonzero. Induced-drag efficiency is
reported relative to the same planform with zero twist so washout cannot
beat the handbook Oswald factor unless the lift distribution actually
improves.

FLAGGED: inviscid section slope from the NeuralFoil polar (capped at 2π);
no fuselage, no viscous wake, no sweep.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

N_MODE = 11  # odd Fourier modes on the half-span


def _theta_nodes(n: int = N_MODE) -> np.ndarray:
    """Collocation θ in (0, π/2]; y = (b/2) cos θ, so θ→0 is the tip."""
    return (np.arange(1, n + 1, dtype=float) * np.pi) / (2.0 * n)


def _modes(n: int = N_MODE) -> np.ndarray:
    return 2 * np.arange(n, dtype=float) + 1.0


@lru_cache(maxsize=256)
def _influence_inv(chords: tuple[float, ...], span_m: float,
                   a0: float) -> np.ndarray:
    """Inverse of the linear lifting-line matrix for a frozen planform."""
    c = np.asarray(chords, dtype=float)
    n = c.size
    theta = _theta_nodes(n)
    ns = _modes(n)
    sin_th = np.sin(theta)
    m = np.empty((n, n))
    for j in range(n):
        row = np.sin(np.outer(ns, theta[j]).ravel())
        m[j, :] = row * (2.0 * span_m / (max(a0, 0.5) * max(c[j], 1e-4))
                         + ns / max(sin_th[j], 1e-6))
    return np.linalg.inv(m)


def solve_coefficients(alpha_geom_rad: np.ndarray, alpha_l0_rad: float,
                       chords: np.ndarray, span_m: float, a0: float,
                       ) -> np.ndarray:
    """Fourier coefficients A_n from geometric alpha at the collocation y's."""
    rhs = np.asarray(alpha_geom_rad, dtype=float) - float(alpha_l0_rad)
    inv = _influence_inv(tuple(np.round(chords, 6)), float(span_m),
                         float(round(a0, 5)))
    return inv @ rhs


def cl_distribution(A: np.ndarray, chords: np.ndarray, span_m: float,
                    ) -> np.ndarray:
    """Section CL at the collocation stations (half-span)."""
    theta = _theta_nodes(A.size)
    ns = _modes(A.size)
    gamma_over_bV = 2.0 * (A[:, None] * np.sin(ns[:, None] * theta[None, :])).sum(axis=0)
    # Γ = 2 b V Σ A_n sin(nθ)  →  cl = 2 Γ / (V c) = 4 (b/c) Σ A sin
    return 2.0 * span_m * gamma_over_bV / np.maximum(chords, 1e-4)


def cl_wing(A: np.ndarray, aspect_ratio: float) -> float:
    """Wing CL from the first Fourier coefficient."""
    return float(np.pi * aspect_ratio * A[0])


def oswald_from_A(A: np.ndarray) -> float:
    """e = A1² / Σ n A_n² from the Trefftz plane."""
    ns = _modes(A.size)
    denom = float(np.sum(ns * A * A))
    if denom <= 1e-16:
        return 1.0
    return float(A[0] ** 2 / denom)
