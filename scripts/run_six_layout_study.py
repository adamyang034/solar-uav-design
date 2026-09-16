"""Reproducible layout/battery morning-SOC study, including spawn workers."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from study_variants import RECTANGULAR_LAYOUT, apply_layout

ROOT = Path(__file__).resolve().parents[1]
LAYOUTS = {"pi_tail": ROOT, "split": ROOT / "split_empennage",
           "conventional": ROOT / "conventional",
           RECTANGULAR_LAYOUT: ROOT / "conventional"}
BATTERIES = {
    "gold_v1": {"PACK_ENERGY_WH": 483.0, "PACK_CAPACITY_AH": 23.68,
                "PACK_MASS_KG": 1.278, "PACK_CHARGE_MAX_A": 6.0},
    "6s_36ah": {"PACK_ENERGY_WH": 36 * 483.0 / 23.68,
                 "PACK_CAPACITY_AH": 36.0, "PACK_MASS_KG": 2.0,
                 "PACK_CHARGE_MAX_A": 6.0},
}

# Spawn imports this module before unpickling the optimizer initializer.
# Configure before importing optimize so every child sees the same battery.
COMBO = os.environ.get("SOLAR_UAV_STUDY_COMBO")
if COMBO:
    LAYOUT, BATTERY = COMBO.split("__")
    sys.path.insert(0, str(LAYOUTS[LAYOUT]))
    from solar_uav import config
    apply_layout(config, LAYOUT)
    for name, value in BATTERIES[BATTERY].items():
        setattr(config, name, value)


def seed_path(layout, battery, seed_dir):
    candidate = seed_dir / f"{layout}__{battery}.csv" if seed_dir else None
    if candidate is not None and candidate.exists():
        return candidate.resolve()
    if layout == RECTANGULAR_LAYOUT:
        return seed_path("conventional", battery, seed_dir)
    return (LAYOUTS[layout] / "outputs/phase4_candidates.csv"
            if battery == "gold_v1" else
            ROOT / "outputs/battery_36ah" / f"{layout}_phase4.csv")


def run_one(args):
    import pandas as pd
    from solar_uav import config, environment, optimize

    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    csv = out / f"{COMBO}.csv"
    source = seed_path(LAYOUT, BATTERY, args.seed_dir)
    start = None
    seed_rows = None
    if source.exists():
        seed_rows = pd.read_csv(source)
        prior = optimize.winner(seed_rows)
        if prior is not None:
            start = {k: float(prior[k]) for k in config.OPT_KEYS
                     if k in prior and pd.notna(prior[k])}
    manifest = {
        "combo": COMBO, "battery": BATTERIES[BATTERY],
        "pack_counts": list(config.PACK_GRID), "start": start,
        "maxiter": args.maxiter, "popsize": args.popsize,
        "method": args.method, "samples": args.samples, "rounds": args.rounds,
        "starts": args.starts, "diameter_radius": args.diameter_radius,
        "pitch_radius": args.pitch_radius,
        "workers": args.workers, "seed": args.seed,
        "objective": "maximize lower morning SOC, next >= current",
        "bounds": config.CONTINUOUS, "status": "running",
        "fixed_geometry": getattr(config, "FIXED_GEOMETRY", {}),
        "active_geometry": list(config.OPT_KEYS),
        "source_seed": str(source), "started": time.time(),
        "config": {k: v for k, v in vars(config).items()
                   if k.isupper() and isinstance(v, (str, int, float, bool, tuple))},
    }
    manifest_path = out / f"{COMBO}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"COMBO {COMBO}: {BATTERIES[BATTERY]}", flush=True)
    env = environment.design_day(config.SOLSTICE_DATE)
    if args.method == "surrogate":
        from surrogate_search import search_surrogate
        df, report = search_surrogate(
            env, seed_rows=seed_rows, workers=args.workers, seed=args.seed,
            samples=args.samples, rounds=args.rounds, starts=args.starts,
            diameter_radius=args.diameter_radius, pitch_radius=args.pitch_radius,
            dump_path=csv)
        manifest["surrogate_summary"] = {k: v for k, v in report.items() if k != "iterations"}
    else:
        df = optimize.search_continuous(
            env, workers=args.workers, maxiter=args.maxiter, popsize=args.popsize,
            seed=args.seed, start=start, dump_path=csv)
    df.to_csv(csv, index=False)
    manifest.update(status="complete", finished=time.time(),
                    candidates=len(df), passing=int(df.closed.sum()) if len(df) else 0)
    if len(df):
        winner = optimize.winner(df)
        manifest["winner"] = json.loads(winner.to_json())
        print(winner.to_string(), flush=True)
    manifest_path.write_text(json.dumps(manifest, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--maxiter", type=int, default=18)
    parser.add_argument("--popsize", type=int, default=6)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--method", choices=("surrogate", "de"), default="surrogate")
    parser.add_argument("--seed-dir", type=Path, default=ROOT / "outputs/morning_soc_rerun_2026-09-15")
    parser.add_argument("--samples", type=int, default=72)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--starts", type=int, default=3)
    parser.add_argument("--diameter-radius", type=float, default=2.5)
    parser.add_argument("--pitch-radius", type=float, default=2.0)
    parser.add_argument("--combo", choices=[f"{l}__{b}" for b in BATTERIES for l in LAYOUTS])
    args = parser.parse_args()
    if COMBO:
        try:
            run_one(args)
        except Exception as exc:
            manifest_path = args.output / f"{COMBO}.json"
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text())
                manifest.update(status="failed", finished=time.time(), error=str(exc))
                manifest_path.write_text(json.dumps(manifest, indent=2))
            raise
        return
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    for battery in BATTERIES:
        for layout, path in LAYOUTS.items():
            combo = f"{layout}__{battery}"
            if args.combo and combo != args.combo:
                continue
            existing = out / f"{combo}.json"
            if existing.exists():
                previous = json.loads(existing.read_text())
                fields = ("method", "seed", "samples", "rounds", "starts", "diameter_radius", "pitch_radius") if args.method == "surrogate" else ("method", "seed", "maxiter", "popsize")
                if any(previous.get(k, "de" if k == "method" else None) != getattr(args, k) for k in fields):
                    raise ValueError(f"Different run settings already exist in {out}; use a new output directory")
                if Path(previous["source_seed"]).resolve() != seed_path(layout, battery, args.seed_dir).resolve():
                    raise ValueError(f"Different seed source already exists in {out}; use a new output directory")
                if previous.get("status") == "complete":
                    print(f"Already complete: {combo}", flush=True)
                    continue
            for folder in ("apc", "mejzlik"):
                dest = path / "data" / folder
                if path != ROOT and not dest.exists():
                    dest.symlink_to(ROOT / "data" / folder, target_is_directory=True)
            env = dict(os.environ, SOLAR_UAV_STUDY_COMBO=combo)
            for key in ("OPENBLAS_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
                        "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
                env[key] = "1"
            command = [sys.executable, "-u", str(Path(__file__).resolve()),
                       "--output", str(out), "--workers", str(args.workers),
                       "--maxiter", str(args.maxiter), "--popsize", str(args.popsize),
                       "--seed", str(args.seed), "--method", args.method,
                       "--samples", str(args.samples), "--rounds", str(args.rounds),
                       "--starts", str(args.starts), "--diameter-radius", str(args.diameter_radius),
                       "--pitch-radius", str(args.pitch_radius)]
            if args.seed_dir:
                command.extend(["--seed-dir", str(args.seed_dir.resolve())])
            print(f"Starting {combo}; log {out / (combo + '.log')}", flush=True)
            with (out / f"{combo}.log").open("w") as log:
                subprocess.run(command, cwd=ROOT, env=env, stdout=log,
                               stderr=subprocess.STDOUT, check=True)
            print(f"Finished {combo}", flush=True)


if __name__ == "__main__":
    main()
