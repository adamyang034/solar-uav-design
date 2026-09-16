"""Read-only engineering review metadata, using the model's actual gates."""
from datetime import datetime, timezone
import hashlib
import json
import math


def numeric_check(key, label, actual, limit, unit, direction, tolerance=0, strict=False, note=""):
    finite = actual is not None and math.isfinite(float(actual))
    slack = ((actual - limit) if direction == "min" else (limit - actual)) if finite else None
    passed = finite and (slack > -tolerance if strict else slack >= -tolerance)
    return dict(id=key, label=label, actual=actual, limit=limit, unit=unit,
                direction=direction, headroom=slack, tolerance=tolerance,
                strict=strict, status="pass" if passed else "fail", note=note)


def snapshot(data, design, config, csv, package_root):
    e, s = data["energy"], data["study"]
    from solar_uav.mission import MORNING_SOC_TOL
    checks = [
        numeric_check("recovery", "Morning-to-morning recovery", 100*e["morning_soc_change"], 0, "pp", "min",
                      100*MORNING_SOC_TOL, note="Next morning SOC minus current morning SOC at onset of net charging. Numerical tolerance only."),
        numeric_check("reserve", "Minimum scored SOC", 100*e["soc_min"], 100*config.SOC_MIN, "%", "min", .0001,
                      note="Scored mission interval, not the separate 89-hour display trace. Headroom is percentage points."),
        numeric_check("mass", "Maximum takeoff mass", design.mass_kg, config.MTOW_MAX_KG, "kg", "max"),
        numeric_check("span", "Wingspan", design.span_m, config.WINGSPAN_MAX_M, "m", "max", 1e-9),
        numeric_check("climb", "Climb rate", e["climb_ms"], config.CLIMB_RATE_REQ_MS, "m/s", "min",
                      note="Provisional model requirement; propeller/motor predictions require validation."),
        numeric_check("unmet", "Unserved energy", e["unmet_wh"], .5, "Wh", "max", strict=True,
                      note="Existing mission gate is strictly less than 0.5 Wh."),
        numeric_check("static", "Static margin", 100*design.static_margin(), 100*config.STATIC_MARGIN_MIN, "% MAC", "min",
                      note="Aerodynamic model assumes CG at quarter-chord; illustrative CAD mass-lump CG is not coupled to this check."),
        numeric_check("roll", "Roll rate", design.roll_rate_deg_s(), config.ROLL_RATE_MIN_DEG_S, "deg/s", "min", 1e-6),
    ]
    for key, label, result, note in [
        ("yaw", "Rudder authority" if config.N_MOTORS == 1 else "Differential-thrust authority", s["yaw_pass"], "Existing yaw-authority check at the evaluated control speed."),
        ("solar", "Solar packing & electrical limits", design.solar_feasible(), "Packing and configured controller limits; new buck/boost hardware remains provisional."),
        ("controls", "Stability & control gates", design.stability_ok(), design.stability_fail_reason() or "Includes elevator, pitch and roll authority."),
        ("hard", "All geometry & design gates", s["hard_failure"] is None, s["hard_failure"] or "Original optimizer hard-constraint function."),
    ]:
        checks.append(dict(id=key, label=label, status="pass" if result else "fail", actual=bool(result),
                           limit=None, headroom=None, unit="", direction="boolean", note=note))
    checks.append(dict(id="structure", label="Strength, buckling & aeroelasticity", status="not_evaluated",
                       actual=None, limit=None, headroom=None, unit="", direction="none",
                       note="Separate structural analysis. No structural approval is implied by model feasibility."))
    manifest_path = csv.with_suffix(".json")
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    digest = hashlib.sha256()
    for path in sorted((package_root / "solar_uav").rglob("*.py")):
        digest.update(str(path.relative_to(package_root)).encode())
        digest.update(path.read_bytes())
    warnings = [
        "Model-feasible is not flight-qualified; structural sizing, buckling, flutter and control reversal are outside this study.",
        "Clear-sky summer-solstice conditions at El Mirage; no cloud or off-design weather guarantee.",
        "Proposed 108 g buck/boost MPPT uses provisional efficiency and electrical limits.",
        "Aerodynamic stability uses an assumed quarter-chord CG. CAD component positions and inertia are illustrative, not an as-built mass survey.",
        "Best evaluated catalog candidate, not a certified global optimum. Hardware and aerodynamic assumptions require test data.",
    ]
    if not config.REQUIRE_YAW_STABILITY:
        warnings.append("Passive directional-stability thresholds are disabled; yaw-authority checks remain active.")
    if e.get("reason") and e["reason"] != "ok":
        warnings.append(e["reason"])
    return dict(
        checks=checks, warnings=warnings,
        provenance=dict(
            source_csv=str(csv.resolve()), source_name=csv.name,
            source_sha256=hashlib.sha256(csv.read_bytes()).hexdigest() if csv.exists() else None,
            manifest_path=str(manifest_path.resolve()) if manifest_path.exists() else None,
            model_sha256=digest.hexdigest(),
            run_completed_utc=datetime.fromtimestamp(manifest["finished"], timezone.utc).isoformat() if manifest.get("finished") else None,
            method=manifest.get("method", "unrecorded"), seed=manifest.get("seed"),
            candidates=manifest.get("candidates"), passing=manifest.get("passing"),
            exact_evaluations=manifest.get("surrogate_summary", {}).get("exact_evaluations"),
            fixed_geometry=manifest.get("fixed_geometry", {}),
            bounds=manifest.get("bounds", {}),
            active_geometry=manifest.get("active_geometry", list(config.OPT_KEYS)),
            search_soc=s["search_morning_soc"], recomputed_soc=e["objective_soc"],
            difference_pp=s["morning_soc_difference_pp"],
        ),
        inputs={k: getattr(config, k) for k in (
            "SOLSTICE_DATE", "LATITUDE_DEG", "LONGITUDE_DEG", "SITE_ALTITUDE_M", "CRUISE_ALT_AGL_M",
            "MTOW_MAX_KG", "WINGSPAN_MAX_M", "SOC_MIN", "CLIMB_RATE_REQ_MS", "STATIC_MARGIN_MIN",
            "ROLL_RATE_MIN_DEG_S", "YAW_RATE_MIN_DEG_S", "REQUIRE_YAW_STABILITY", "PACK_ENERGY_WH",
            "PACK_CAPACITY_AH", "PACK_MASS_KG", "PACK_CHARGE_MAX_A", "PACK_R_INTERNAL_OHM",
            "MPPT_MASS_KG", "MPPT_EFFICIENCY", "MPPT_MAX_INPUT_A", "MPPT_MAX_PV_VOC_V",
            "MPPT_MAX_PV_ABS_V", "MPPT_MAX_PANEL_W", "PROP_THRUST_DERATE", "PROP_POWER_INFLATE",
            "ESC_EFFICIENCY", "GEARBOX_EFFICIENCY", "CELL_BIN_DEFAULT", "CELL_MASS_KG",
            "ENCAPSULATION_TRANSMISSION", "WIRING_MISMATCH_SOILING_EFF") if hasattr(config, k)},
        objective="Maximize min(current morning SOC, next morning SOC), with next >= current.",
        display_basis="89 h display starts at 08:00 with 100% SOC; repeating design-day conditions. Separate from the scored morning cycle.",
    )
