"""AeroSandbox response-surface search; only exact catalog evaluations can win.

Shared by the three layout packages through the six-case runner. Imports of
solar_uav intentionally resolve to the layout selected by that runner.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
import json
from pathlib import Path
import time

import aerosandbox as asb
import aerosandbox.numpy as anp
import numpy as np
import pandas as pd
from scipy.spatial import ConvexHull
from scipy.stats import qmc


@dataclass
class SmoothFit:
    """Ridge-regularized Gaussian RBF plus affine trend, in normalized inputs."""
    centers: np.ndarray
    coefficients: np.ndarray
    offset: float
    scale: float
    length: float = 0.65
    ridge: float = .1

    @staticmethod
    def basis(x):
        distance = np.sum((x[:, None, :] - x[None, :, :]) ** 2, axis=2)
        return np.column_stack([np.ones(len(x)), x, np.exp(-distance / (2 * .65**2))])

    @classmethod
    def choose_ridge(cls, x, y):
        """Analytic leave-one-out error tunes smoothing without held-out labels."""
        x, y = np.asarray(x, float), np.asarray(y, float)
        phi = cls.basis(x)
        gram = phi.T @ phi
        target = (y - np.mean(y)) / max(float(np.std(y)), 1e-6)
        trials = []
        for strength in (.001, .01, .1, 1., 10.):
            penalty = np.full(phi.shape[1], strength)
            penalty[0] = 1e-8
            inverse_action = np.linalg.solve(gram + np.diag(penalty), phi.T)
            prediction = phi @ (inverse_action @ target)
            leverage = np.sum(phi * inverse_action.T, axis=1)
            error = np.mean(((target - prediction) / np.maximum(1 - leverage, 1e-6))**2)
            trials.append((float(error), strength))
        return min(trials)[1]

    @classmethod
    def fit(cls, x, y, ridge=.1):
        x, y = np.asarray(x, float), np.asarray(y, float)
        offset = float(np.mean(y))
        scale = max(float(np.std(y)), 1e-6)
        phi = cls.basis(x)
        penalty = np.full(phi.shape[1], ridge)
        penalty[0] = 1e-8
        coefficients = np.linalg.solve(
            phi.T @ phi + np.diag(penalty), phi.T @ ((y - offset) / scale))
        return cls(x, coefficients, offset, scale, ridge=ridge)

    def __call__(self, x):
        radial = [anp.exp(-anp.sum((x - center)**2) / (2 * self.length**2))
                  for center in self.centers]
        features = anp.concatenate([anp.array([1.0]), x, anp.array(radial)])
        return self.offset + self.scale * anp.dot(self.coefficients, features)


def nearby_props(catalog, diameter, pitch, *, diameter_radius=2.5,
                 pitch_radius=2.0, minimum=5):
    """Actual SKUs only; retain all variants within the rectangular window.

    Fill sparse windows with nearest available SKUs, never synthetic sizes.
    Distance scaling gives diameter and pitch the requested neighborhood sizes.
    """
    if diameter_radius <= 0 or pitch_radius <= 0 or minimum < 1:
        raise ValueError('Neighborhood radii and minimum count must be positive')
    d = (catalog.diameter_in.to_numpy(float) - diameter) / diameter_radius
    p = (catalog.pitch_in.to_numpy(float) - pitch) / pitch_radius
    distances = d*d + p*p
    selected = set(np.flatnonzero((np.abs(d) <= 1) & (np.abs(p) <= 1)))
    selected.update(np.argsort(distances)[:min(minimum, len(catalog))])
    return catalog.iloc[sorted(selected, key=lambda i: (distances[i], str(catalog.iloc[i]['name'])))].copy()


def nearby_packs(value, allowed):
    """Nearest allowed values on both sides, not arbitrary rounded integers."""
    allowed = sorted(set(int(v) for v in allowed))
    lower = [v for v in allowed if v <= value]
    upper = [v for v in allowed if v >= value]
    chosen = set(([lower[-1]] if lower else []) + ([upper[0]] if upper else []))
    chosen.update(sorted(allowed, key=lambda n: (abs(n - value), n))[:2])
    return sorted(chosen)


def bounded_solution(z):
    """Remove solver-scale bound drift without relaxing aircraft requirements."""
    z = np.asarray(z, float).ravel()
    if not np.all(np.isfinite(z)) or np.any(z < -1e-6) or np.any(z > 1 + 1e-6):
        raise RuntimeError('Solver returned a point outside the normalized design bounds')
    return np.clip(z, 0., 1.)


_WORKER = {}


def _init_worker(env, settings, props=None):
    from solar_uav import config
    from solar_uav.components.propulsion import register_props
    for key, value in settings.items():
        setattr(config, key, value)
    _WORKER['env'] = env
    if props:
        register_props(props)


def _exact(task):
    from solar_uav import config, optimize, asb_physics
    from solar_uav.components.propulsion import load_prop, PropulsionSystem
    from solar_uav.components.motor import drive_for
    x, packs, name = task
    # Rounded global aero caches must not make a candidate depend on evaluation order.
    for key, cache in vars(asb_physics).items():
        if key.endswith('_CACHE') and isinstance(cache, dict):
            cache.clear()
    d = optimize.design_from_x(x, n_packs=packs)
    prop = load_prop(name)
    d.prop_name, d.prop_diameter_in = name, prop.diameter_in
    drive = drive_for(config.MOTOR_DEFAULT)
    system = PropulsionSystem(prop=prop, motor=drive)
    started = time.perf_counter()
    row = optimize.evaluate_design(d, _WORKER['env'], [name], {name: prop}, drive, {name: system})
    return dict(x=list(x), packs=int(packs), prop=name, row=row,
                elapsed_s=time.perf_counter() - started)


def _feature(observation, lookup, lo, scale):
    prop = lookup.loc[observation['prop']]
    return (np.r_[observation['x'], observation['packs'], prop.diameter_in, prop.pitch_in] - lo) / scale


def _models(observations, lookup, lo, scale, seed):
    """Separate manufacturer fits; report holdout error without treating it as certification."""
    models, diagnostics = {}, {}
    targets = ('objective_soc', 'soc_min', 'morning_soc_change', 'climb_ms', 'unmet_wh')
    for family in sorted(lookup.manufacturer.unique()):
        obs = [o for o in observations if lookup.loc[o['prop'], 'manufacturer'] == family]
        valid = [o for o in obs if o['row'] is not None and
                 all(np.isfinite(o['row'][key]) for key in targets)]
        if len(valid) < 8:
            diagnostics[family] = dict(status='insufficient_samples', valid=len(valid), total=len(obs))
            continue
        x = np.array([_feature(o, lookup, lo, scale) for o in valid])
        soc_values = np.array([o['row']['objective_soc'] for o in valid])
        strength = SmoothFit.choose_ridge(x, soc_values)
        fits = {key: SmoothFit.fit(x, [o['row'][key] for o in valid], ridge=strength) for key in targets}
        valid_ids = {id(o) for o in valid}
        fits['valid'] = SmoothFit.fit(
            np.array([_feature(o, lookup, lo, scale) for o in obs]),
            [float(id(o) in valid_ids) for o in obs], ridge=strength)
        models[family] = fits
        # Group identical relaxed coordinates so catalog variants cannot leak between splits.
        groups = {}
        for i, xx in enumerate(x):
            groups.setdefault(tuple(np.round(xx, 8)), []).append(i)
        keys = list(groups)
        rng = np.random.default_rng(seed)
        rng.shuffle(keys)
        test = [i for k in keys[:max(1, len(keys)//5)] for i in groups[k]]
        train = [i for k in keys[max(1, len(keys)//5):] for i in groups[k]]
        error = None
        if len(train) >= 6:
            yy = soc_values
            holdout = SmoothFit.fit(x[train], yy[train], ridge=SmoothFit.choose_ridge(x[train], yy[train]))
            error = float(np.sqrt(np.mean([(float(holdout(x[i])) - yy[i])**2 for i in test])))
        diagnostics[family] = dict(status='fit', valid=len(valid), total=len(obs),
                                   ridge=strength,
                                   held_out_soc_rmse_pp=None if error is None else 100*error)
    return models, diagnostics


def _propose(fits, catalog, anchors, lo, scale, n_geometry, trust_radius):
    """IPOPT optimizes a continuous pack count, diameter/pitch, and geometry.

    Relaxed constraint tolerances below are proposal-only. Exact acceptance
    still uses the original morning SOC tolerance and all original gates.
    """
    from solar_uav import config
    proposals, failures = [], []
    dp = (catalog[['diameter_in', 'pitch_in']].to_numpy(float) - lo[-2:]) / scale[-2:]
    hull = ConvexHull(np.unique(dp, axis=0))
    for anchor in anchors:
        opti = asb.Opti()
        low, high = np.zeros(len(lo)), np.ones(len(lo))
        low[:n_geometry] = np.maximum(0, anchor[:n_geometry] - trust_radius)
        high[:n_geometry] = np.minimum(1, anchor[:n_geometry] + trust_radius)
        z = opti.variable(init_guess=anchor, n_vars=len(lo), lower_bound=low, upper_bound=high)
        opti.subject_to(anp.sum((z[:n_geometry] - anchor[:n_geometry])**2) <= trust_radius**2)
        opti.subject_to(anp.sum((z[-2:] - anchor[-2:])**2) <= .25**2)
        for a, b, c in hull.equations:
            opti.subject_to(a*z[-2] + b*z[-1] + c <= 0)
        score = fits['objective_soc'](z)
        opti.subject_to([
            fits['valid'](z) >= .5,
            fits['soc_min'](z) >= config.SOC_MIN,
            fits['morning_soc_change'](z) >= -.002,
            fits['climb_ms'](z) >= config.CLIMB_RATE_REQ_MS,
            fits['unmet_wh'](z) <= .1,
            score <= 1,
        ])
        opti.minimize(-score + .002 * anp.sum((z - anchor)**2))
        try:
            solution = opti.solve(verbose=False, max_iter=250, max_runtime=20)
            zz = bounded_solution(solution(z))
            proposals.append(dict(z=zz, predicted_soc=float(fits['objective_soc'](zz)),
                                  solver_status=solution.stats()['return_status']))
        except RuntimeError as exc:
            failures.append(str(exc).splitlines()[-1])
    return sorted(proposals, key=lambda p: p['predicted_soc'], reverse=True), failures


def search_surrogate(env, *, seed_rows=None, workers=6, seed=7, samples=72,
                     rounds=3, starts=3, dump_path=None, diameter_radius=2.5,
                     pitch_radius=2.0, verbose=True):
    """Return exact ranked rows and diagnostics, never a fractional aircraft.

    Initial catalog sweeps happen once at the incumbent, not at every geometry.
    Later evaluations are neighborhoods of continuous IPOPT proposals and
    small geometry perturbations that cross cell-packing thresholds.
    """
    from solar_uav import config, optimize
    from solar_uav.components.propulsion import shortlist_props, load_prop
    from solar_uav.mission import candidate_score
    if samples < 0 or rounds < 1 or starts < 1 or workers < 1:
        raise ValueError('samples >= 0; rounds, starts, and workers must be positive')
    if diameter_radius <= 0 or pitch_radius <= 0:
        raise ValueError('Propeller neighborhood radii must be positive')
    catalog = shortlist_props().reset_index(drop=True)
    if catalog.empty:
        raise ValueError('No catalog props in the configured window')
    props = {name: load_prop(name) for name in catalog.name}
    lookup = catalog.set_index('name')
    keys = list(config.OPT_KEYS)
    geometry_bounds = np.array([config.CONTINUOUS[k][:2] for k in keys], float)
    packs = sorted(set(config.PACK_GRID))
    if len(packs) < 2:
        raise ValueError('Pack relaxation requires at least two allowed pack counts')
    lo = np.r_[geometry_bounds[:, 0], min(packs), catalog.diameter_in.min(), catalog.pitch_in.min()]
    hi = np.r_[geometry_bounds[:, 1], max(packs), catalog.diameter_in.max(), catalog.pitch_in.max()]
    scale = hi - lo
    if np.any(scale <= 0):
        raise ValueError('Relaxed search coordinates need nonzero ranges')
    seeds = []
    if seed_rows is not None and not seed_rows.empty:
        for _, row in optimize.rank_candidates(seed_rows).head(12).iterrows():
            if row.get('prop') not in lookup.index or int(row.n_packs) not in packs:
                continue
            x = optimize.x_from_start({k: float(row[k]) for k in keys})
            if np.all(x >= geometry_bounds[:, 0] - 1e-9) and np.all(x <= geometry_bounds[:, 1] + 1e-9):
                seeds.append((np.clip(x, geometry_bounds[:, 0], geometry_bounds[:, 1]), int(row.n_packs), str(row.prop)))
    incumbent = seeds[0][0] if seeds else optimize.x_from_start()
    tasks = list(seeds)
    tasks.extend((incumbent.copy(), int(n), str(name)) for n in packs for name in catalog.name)
    rng = np.random.default_rng(seed)
    latin = qmc.LatinHypercube(len(keys), seed=seed).random(samples)
    normalized = (incumbent - geometry_bounds[:, 0]) / scale[:len(keys)]
    for i, xx in enumerate(latin):
        # Half global, half local: discover alternatives and resolve the incumbent region.
        if i % 2:
            xx = np.clip(normalized + (xx - .5) * .4, 0, 1)
        x = geometry_bounds[:, 0] + xx * scale[:len(keys)]
        tasks.append((x, int(packs[i % len(packs)]), str(catalog.iloc[rng.integers(len(catalog))]['name'])))
    observations, seen, diagnostics = [], set(), []
    trust = {family: .20 for family in catalog.manufacturer.unique()}
    settings = {k: getattr(config, k) for k in
                ('PACK_ENERGY_WH', 'PACK_CAPACITY_AH', 'PACK_MASS_KG', 'PACK_CHARGE_MAX_A')}
    started = time.perf_counter()
    pool = ProcessPoolExecutor(max_workers=workers, initializer=_init_worker, initargs=(env, settings, props)) if workers > 1 else None
    if pool is None:
        _init_worker(env, settings, props)

    def evaluate(batch, label):
        unique = []
        for x, n, name in batch:
            key = (int(n), str(name), *np.round(x, 9))
            if key not in seen:
                seen.add(key)
                unique.append((list(x), int(n), str(name)))
        observations.extend(list(pool.map(_exact, unique)) if pool else [_exact(t) for t in unique])
        frame = optimize._rows_to_frame([o['row'] for o in observations if o['row'] is not None])
        if dump_path is not None and not frame.empty:
            frame.to_csv(dump_path, index=False)
        if verbose:
            best = f"{100*frame.iloc[0].objective_soc:.2f}%" if not frame.empty else 'none'
            print(f"  {label}: {len(observations)} exact single-prop evaluations; best morning SOC {best}", flush=True)
        return frame

    try:
        frame = evaluate(tasks, 'initial sampling')
        for iteration in range(rounds):
            fits, fit_report = _models(observations, lookup, lo, scale, seed)
            batch, proposal_report = [], []
            before_count = len(observations)
            for family, family_fits in fits.items():
                family_catalog = catalog[catalog.manufacturer == family]
                eligible = sorted([o for o in observations if o['row'] is not None and
                                   lookup.loc[o['prop'], 'manufacturer'] == family],
                                  key=lambda o: candidate_score(o['row']))
                # Include both pack counts among multistart anchors.
                anchor_obs = [next((o for o in eligible if o['packs'] == n), None) for n in packs]
                anchors = [_feature(o, lookup, lo, scale) for o in anchor_obs if o is not None][:starts]
                for o in eligible:
                    if len(anchors) >= starts:
                        break
                    z = _feature(o, lookup, lo, scale)
                    if not anchors or min(np.linalg.norm(z - a) for a in anchors) > .15:
                        anchors.append(z)
                    if len(anchors) >= starts:
                        break
                rmse = fit_report[family].get('held_out_soc_rmse_pp')
                if rmse is not None and rmse > 5:
                    trust[family] = min(trust[family], .10)
                proposals, failures = _propose(family_fits, family_catalog, anchors, lo, scale, len(keys), trust[family])
                selected = proposals[:1]
                # Failed solves do not produce an alleged optimum; sample exact neighbors instead.
                if not selected and anchors:
                    selected = [dict(z=anchors[0], predicted_soc=None, solver_status='fallback_anchor')]
                for proposal in selected:
                    raw = lo + scale * proposal['z']
                    neighborhood = nearby_props(family_catalog, raw[-2], raw[-1],
                                                diameter_radius=diameter_radius, pitch_radius=pitch_radius)
                    pack_choices = nearby_packs(raw[len(keys)], packs)
                    for n in pack_choices:
                        batch.extend((raw[:len(keys)], n, name) for name in neighborhood.name)
                    # Exact packing on either side of small geometric changes, using nearest SKU.
                    for key in ('chord_m', 'boom_spacing_m'):
                        j = keys.index(key)
                        for direction in (-1, 1):
                            x = raw[:len(keys)].copy()
                            x[j] = np.clip(x[j] + direction*.005, geometry_bounds[j, 0], geometry_bounds[j, 1])
                            batch.extend((x, n, neighborhood.iloc[0]['name']) for n in pack_choices)
                    proposal_report.append(dict(family=family, relaxed=dict(zip(keys + ['n_packs', 'diameter_in', 'pitch_in'], raw)),
                                                predicted_soc=proposal['predicted_soc'], status=proposal['solver_status'],
                                                props=list(neighborhood.name), packs=pack_choices, failures=failures,
                                                trust_radius=trust[family],
                                                incumbent_soc=max((o['row']['objective_soc'] for o in eligible if o['row']['closed']), default=None)))
            frame = evaluate(batch, f'IPOPT refinement {iteration + 1}')
            for p in proposal_report:
                accepted = [o['row']['objective_soc'] for o in observations[before_count:]
                            if o['row'] is not None and o['row']['closed'] and
                            lookup.loc[o['prop'], 'manufacturer'] == p['family']]
                p['verified_neighborhood_soc'] = max(accepted, default=None)
                baseline, actual, prediction = p['incumbent_soc'], p['verified_neighborhood_soc'], p['predicted_soc']
                if actual is None or (prediction is not None and prediction - actual > .03) or (baseline is not None and actual <= baseline):
                    trust[p['family']] = max(.025, trust[p['family']] * .5)
                if verbose:
                    print(f"    {p['family']}: {p['status']}; relaxed D={p['relaxed']['diameter_in']:.2f} in, P={p['relaxed']['pitch_in']:.2f} in; exact passing neighborhood SOC={actual}", flush=True)
            diagnostics.append(dict(iteration=iteration + 1, fits=fit_report, proposals=proposal_report))
    finally:
        if pool:
            pool.shutdown(wait=True)
    report = dict(method='aerosandbox_surrogate', exact_evaluations=len(observations),
                  catalog_props=len(catalog), elapsed_s=time.perf_counter()-started,
                  candidates=len(frame), iterations=diagnostics,
                  warnings=['Response-surface proposals are not exact physics or guaranteed global optima.',
                            'Final results contain only original-model evaluations of actual catalog SKUs.'])
    if dump_path is not None:
        path = Path(dump_path)
        path.with_suffix('.surrogate.json').write_text(json.dumps(report, indent=2, default=lambda x: x.item() if isinstance(x, np.generic) else x))
        path.with_suffix('.samples.json').write_text(json.dumps(observations, default=lambda x: x.item() if isinstance(x, np.generic) else x))
    return frame, report
