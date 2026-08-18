"""Find the most efficient APC-prop × free-Kv pairing for the current airframe.

Usage:  .venv/bin/python scripts/run_kv_prop.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solar_uav.aircraft import Design
from solar_uav import config, optimize_kv

OUT = Path(__file__).resolve().parents[1] / "outputs"
OUT.mkdir(exist_ok=True)


def sample_airframe() -> Design:
    """Phase 4 best-so-far geometry (6 m × 0.36 m, 84 cells, 2 packs)."""
    d = Design(span_m=6.0, chord_m=0.36, tail_arm_m=1.3,
               n_packs=2, cells_per_string=12, n_strings=7,
               elevator_frac=0.28)
    d.n_strings = max(1, d.max_strings())
    return d


def main():
    d = sample_airframe()
    print("=" * 70)
    print("KV × PROP MATCHER  (APC discrete, Kv free, A40-12L stator)")
    print(f"  Airframe: {d.span_m} m × {d.chord_m} m, {d.n_cells} cells, "
          f"{d.n_packs} packs, {d.mass_kg:.2f} kg")

    df = optimize_kv.search(d, verbose=True)
    if df.empty:
        print("  No feasible combos.")
        return
    path = OUT / "kv_prop_candidates.csv"
    df.to_csv(path, index=False)
    print(f"  {len(df)} feasible (Kv, prop) pairs -> {path}")

    w = optimize_kv.winner(df)
    print("  Best (climb-feasible, min cruise bus power):")
    print(w[["prop", "kv", "prop_rpm", "voltage_v", "p_bus_w", "idle_w",
             "efficiency", "climb_ms", "duty", "i0_a", "r_ohm"]].to_string())

    ok = df[df["climb_ok"]]
    practical = ok[ok["duty"] >= config.ESC_DUTY_MIN]
    print(f"  Climb-feasible: {len(ok)} / {len(df)}")
    print(f"  Climb + ESC duty ≥ {config.ESC_DUTY_MIN:.0%}: {len(practical)}")
    print("  Top 8 practical (climb + duty):")
    cols = ["prop", "kv", "p_bus_w", "idle_w", "efficiency", "prop_rpm",
            "voltage_v", "duty", "climb_ms"]
    pool = practical if len(practical) else ok
    print(pool[cols].head(8).round(3).to_string(index=False))

    refs = optimize_kv.catalog_references(d)
    if not refs.empty:
        print("  Catalog Hacker units (best prop each):")
        for name, g in refs.groupby("catalog"):
            gok = g[g["climb_ok"]].nsmallest(1, "p_bus_w")
            if gok.empty:
                gok = g.nsmallest(1, "p_bus_w")
            r = gok.iloc[0]
            print(f"    {name}: {r['prop']}  {r['p_bus_w']:.0f} W  "
                  f"Kv_eff={r['kv_effective']:.0f}  climb={r['climb_ms']:.2f}")

    # Heatmap: bus power vs Kv (x) and prop (y), practical set
    plot_df = practical if len(practical) else ok
    pivot = plot_df.pivot_table(index="prop", columns="kv", values="p_bus_w",
                                aggfunc="min")
    fig, ax = plt.subplots(figsize=(12, 8))
    im = ax.imshow(pivot.to_numpy(), aspect="auto", origin="upper",
                   cmap="viridis_r")
    ax.set_xticks(range(0, len(pivot.columns), 4))
    ax.set_xticklabels([int(c) for c in pivot.columns[::4]])
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(list(pivot.index), fontsize=8)
    ax.set_xlabel("Motor Kv (direct drive, rpm/V)")
    ax.set_ylabel("APC propeller")
    fig.colorbar(im, ax=ax, label="Cruise bus power [W] (2 motors)")
    # mark winner
    if w["prop"] in pivot.index and w["kv"] in pivot.columns:
        yi = list(pivot.index).index(w["prop"])
        xi = list(pivot.columns).index(w["kv"])
        ax.plot(xi, yi, "r*", ms=14, label="optimum")
        ax.legend(loc="upper right")
    ax.set_title("Cruise bus power — APC prop × free Kv (climb-feasible only)")
    fig.tight_layout()
    fig.savefig(OUT / "kv_prop_heatmap.png", dpi=150)

    # Slice: best prop at each Kv, and best Kv at a few props
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    best_by_kv = plot_df.loc[plot_df.groupby("kv")["p_bus_w"].idxmin()]
    axes[0].plot(best_by_kv["kv"], best_by_kv["p_bus_w"], lw=1.8)
    axes[0].set_xlabel("Kv")
    axes[0].set_ylabel("Best-prop cruise bus power [W]")
    axes[0].set_title("Envelope: min power vs Kv")
    axes[0].axvline(w["kv"], color="r", ls="--")

    for pname in [w["prop"], "16x10E", "18x10E", "20x13E"]:
        g = plot_df[plot_df["prop"] == pname]
        if g.empty:
            continue
        axes[1].plot(g["kv"], g["p_bus_w"], lw=1.5, label=pname)
    axes[1].set_xlabel("Kv")
    axes[1].set_ylabel("Cruise bus power [W]")
    axes[1].legend(fontsize=8)
    axes[1].set_title("Selected props vs Kv")
    fig.tight_layout()
    fig.savefig(OUT / "kv_prop_slices.png", dpi=150)

    print(f"  Plots: {OUT / 'kv_prop_heatmap.png'}, {OUT / 'kv_prop_slices.png'}")


if __name__ == "__main__":
    main()
