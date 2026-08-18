"""Phase 5 Monte Carlo + Phase 6 validation pipeline + CAD export.

Usage:  .venv/bin/python scripts/run_phase56.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solar_uav import cad, config, environment, mission, monte_carlo, validation
from solar_uav.aircraft import reference_design
from solar_uav.components.propulsion import PropulsionSystem, load_prop

OUT = Path(__file__).resolve().parents[1] / "outputs"
OUT.mkdir(exist_ok=True)
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = ""):
    if cond:
        print(f"  PASS  {name}")
    else:
        FAILURES.append(f"{name}: {detail}")
        print(f"  FAIL  {name}  {detail}")


def phase5(design, env, prop_sys):
    print("=" * 70)
    print("PHASE 5 — Monte Carlo uncertainty (reference airframe)")
    df = monte_carlo.run(design, prop_name=config.REF_PROP, env=env, verbose=True)
    df.to_csv(OUT / "phase5_samples.csv", index=False)
    summary = monte_carlo.summarize(df)
    (OUT / "phase5_summary.json").write_text(json.dumps(summary, indent=2))
    drivers = monte_carlo.spearman_drivers(df)
    drivers.to_csv(OUT / "phase5_spearman.csv", index=False)
    torn, base = monte_carlo.tornado(design, env, prop_sys)
    torn.to_csv(OUT / "phase5_tornado.csv", index=False)

    print(f"  n={summary['n']}  P(closed)={summary['p_closed']:.3f}  "
          f"P(closed & ≤12 kg)={summary['p_closed_legal']:.3f}")
    print(f"  margin P10/P50/P90 = {summary['margin_p10_wh']:.0f} / "
          f"{summary['margin_p50_wh']:.0f} / {summary['margin_p90_wh']:.0f} Wh")
    print(f"  SOC min P10/P50 = {summary['soc_min_p10']:.3f} / "
          f"{summary['soc_min_p50']:.3f}")
    print("  Spearman |margin| drivers:")
    print(drivers.head(5).to_string(index=False))

    check("sample count", summary["n"] == config.MC_N_SAMPLES,
          f"{summary['n']}")
    check("every sample has a margin", df["margin_wh"].notna().all())
    check("nominal tornado baseline is finite", np.isfinite(base.margin_wh),
          str(base.margin_wh))

    # Histogram
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    m = df.loc[df["margin_wh"] > -1e8, "margin_wh"]
    axes[0].hist(m, bins=24, color="tab:blue", edgecolor="white")
    axes[0].axvline(0, color="r", ls="--", label="closure")
    axes[0].axvline(summary["margin_p10_wh"], color="k", ls=":", label="P10")
    axes[0].axvline(summary["margin_p50_wh"], color="k", ls="-", label="P50")
    axes[0].set_xlabel("Energy margin [Wh]")
    axes[0].set_ylabel("Samples")
    axes[0].set_title("Phase 5 — 24 h energy margin")
    axes[0].legend(fontsize=8)
    axes[1].hist(df["soc_min"] * 100, bins=24, color="tab:orange", edgecolor="white")
    axes[1].axvline(config.SOC_MIN * 100, color="r", ls="--", label="20% floor")
    axes[1].set_xlabel("Minimum SOC [%]")
    axes[1].set_title("Phase 5 — night SOC floor")
    axes[1].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "phase5_margin_hist.png", dpi=150)
    plt.close(fig)

    # Tornado
    params = torn["param"].unique()
    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    y = np.arange(len(params))
    for i, p in enumerate(params):
        g = torn[torn["param"] == p]
        lo = float(g.loc[g["side"] == "lo", "delta_wh"].iloc[0])
        hi = float(g.loc[g["side"] == "hi", "delta_wh"].iloc[0])
        ax.barh(i, hi, color="tab:blue", height=0.35)
        ax.barh(i, lo, color="tab:orange", height=0.35)
    ax.axvline(0, color="k", lw=0.6)
    ax.set_yticks(y)
    ax.set_yticklabels(params)
    ax.set_xlabel("Δ energy margin vs nominal [Wh]")
    ax.set_title("Phase 5 tornado (±1σ, one-at-a-time)")
    fig.tight_layout()
    fig.savefig(OUT / "phase5_tornado.png", dpi=150)
    plt.close(fig)

    # Overlay a few SOC traces at P10 / P50 / P90 of margin
    ranked = df.sort_values("margin_wh")
    picks = {
        "P10": ranked.iloc[max(0, int(0.10 * len(ranked)))],
        "P50": ranked.iloc[int(0.50 * len(ranked))],
        "P90": ranked.iloc[min(len(ranked) - 1, int(0.90 * len(ranked)))],
    }
    fig, ax = plt.subplots(figsize=(10, 4.2))
    for label, row in picks.items():
        sc = monte_carlo._scales_from_row(row.to_dict())
        res = mission.simulate(design, env, prop_sys, dt_min=10, scales=sc)
        if res.soc_trace.size:
            ax.plot(res.hours, res.soc_trace * 100, label=f"{label} ({res.margin_wh:.0f} Wh)")
    ax.axhline(config.SOC_MIN * 100, color="r", ls="--", label="20% floor")
    ax.set_xlabel("Hours from afternoon-full")
    ax.set_ylabel("SOC [%]")
    ax.set_title("Phase 5 — SOC traces at margin percentiles")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT / "phase5_soc_percentiles.png", dpi=150)
    plt.close(fig)
    return df, summary, torn, base


def phase6(design):
    print("=" * 70)
    print("PHASE 6 — validation protocols")
    comps = validation.evaluate_all(design, prop_name=config.REF_PROP)
    rec_path = validation.write_recommendations(comps, OUT / "phase6_factor_recommendations.json")
    awaiting = sum(1 for c in comps if c.awaiting_data)
    print(f"  {awaiting}/{len(comps)} protocols awaiting measured CSVs")
    for c in comps:
        status = "AWAIT" if c.awaiting_data else "DATA"
        print(f"  {status:5s}  {c.protocol:16s}  {c.notes}")
    print(f"  recommendations → {rec_path}")

    selftest = validation.run_self_test()
    print("  Synthetic fitter self-test:")
    for k, v in selftest.items():
        print(f"    {k}: {v}")
    check("panel fitter recovers planted scale", selftest.get("panel_ok", False),
          f"got {selftest.get('panel_recovered')}")
    check("thrust fitter recovers planted scale", selftest.get("thrust_ok", False),
          f"got {selftest.get('thrust_recovered')}")
    check("glide fitter recovers planted scale", selftest.get("glide_ok", False),
          f"got {selftest.get('glide_recovered')}")
    (OUT / "phase6_selftest.json").write_text(json.dumps(selftest, indent=2, default=str))
    return comps, selftest


def phase_cad(design):
    print("=" * 70)
    print("CAD / visualizer")
    paths = cad.export_all(design, OUT)
    for k, p in paths.items():
        print(f"  {k:16s} {p}")
    check("STL written", Path(paths["stl"]).stat().st_size > 1000)
    check("HTML viewer written", Path(paths["html"]).stat().st_size > 1000)
    check("three-view written", Path(paths["three_view"]).stat().st_size > 1000)
    return paths


def main():
    design = reference_design()
    print(f"Reference: {design.span_m}×{design.chord_m} m, "
          f"{design.n_cells} cells, {design.n_packs} packs, "
          f"{config.REF_PROP}, {design.mass_kg:.2f} kg")
    env = environment.design_day(config.SOLSTICE_DATE)
    prop_sys = PropulsionSystem(prop=load_prop(config.REF_PROP))
    design.prop_diameter_in = prop_sys.prop.diameter_in or 16.0

    phase5(design, env, prop_sys)
    phase6(design)
    phase_cad(design)

    print("=" * 70)
    if FAILURES:
        print(f"{len(FAILURES)} CHECK(S) FAILED:")
        for f in FAILURES:
            print("  -", f)
        sys.exit(1)
    print(f"All Phase 5/6 checks passed. Artifacts in {OUT}")


if __name__ == "__main__":
    main()
