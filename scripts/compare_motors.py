"""Best-vs-best: A40-10L geared vs A40-12L kv410 direct.

Each motor gets its own Phase 4 one-string-per-bay search. The inner loop
re-picks the climb-legal prop with the lowest night bus power. Airframe
grid is the same as the current winner search.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solar_uav import config, environment, optimize

OUT = Path(__file__).resolve().parents[1] / "outputs"

MOTORS = (
    "A40-10L-V2-kv1100-6.7PG",
    "A40-12L-V4-kv410-direct",
)


def main():
    env = environment.design_day(config.SOLSTICE_DATE)
    cols = ["motor", "span_m", "chord_m", "tail_arm_m", "elevator_frac",
            "boom_spacing_m", "taper_ratio", "taper_start_frac", "string_plan",
            "n_cells", "prop", "mass_kg", "p_night_w", "climb_ms",
            "margin_wh", "closed"]
    winners = []
    for key in MOTORS:
        spec = config.MOTOR_CATALOG[key]
        print("=" * 70)
        print(f"SEARCH  {spec.name}")
        df = optimize.search(
            env, verbose=True, mixed_strings=True, one_string_per_bay=True,
            boom_grid=config.BOOM_SPACING_GRID_M,
            elevator_grid=(0.28, 0.34),
            motor_name=key)
        slug = "10L" if "10L" in key else "12L"
        path = OUT / f"phase4_motor_{slug}.csv"
        df.to_csv(path, index=False)
        print(f"  {len(df)} candidates → {path}")
        print(f"  closed: {int(df['closed'].sum())} / {len(df)}")
        if df.empty:
            continue
        print("  Top 5:")
        print(df[cols].head(5).to_string(index=False))
        w = optimize.winner(df)
        winners.append(w)
        print("  Winner:")
        print(w[cols].to_string())

    if len(winners) == 2:
        a, b = winners
        print("=" * 70)
        print("BEST vs BEST")
        print(f"  {a['motor']}: {a['prop']}  {a['span_m']}×{a['chord_m']} m  "
              f"Pnight={a['p_night_w']:.1f} W  margin={a['margin_wh']:.1f} Wh  "
              f"closed={bool(a['closed'])}")
        print(f"  {b['motor']}: {b['prop']}  {b['span_m']}×{b['chord_m']} m  "
              f"Pnight={b['p_night_w']:.1f} W  margin={b['margin_wh']:.1f} Wh  "
              f"closed={bool(b['closed'])}")
        print(f"  Δmargin (12L − 10L) = {b['margin_wh'] - a['margin_wh']:+.1f} Wh")
        print(f"  ΔPnight (12L − 10L) = {b['p_night_w'] - a['p_night_w']:+.1f} W")


if __name__ == "__main__":
    main()
