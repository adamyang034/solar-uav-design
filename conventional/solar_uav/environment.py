"""Phase 1 — Mission-site solar resource and thermal environment model.

Produces minute-resolution 24 h profiles of:
  * clear-sky plane-of-array irradiance on a horizontal wing (GHI-based),
    with incidence-angle (reflection) losses applied to the beam component
    — this is the "sun is never exactly overhead" factor,
  * ambient temperature (sinusoidal design-day model),
  * cell temperature (NOCT-style, calibrated so the solstice-noon static
    cell temperature hits config.CELL_T_MAX_C).

Irradiance uncertainty is exposed as a simple multiplicative scale so the
Monte Carlo layer (Phase 5) can sample it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pvlib

from . import config


def _location() -> pvlib.location.Location:
    return pvlib.location.Location(
        latitude=config.LATITUDE_DEG,
        longitude=config.LONGITUDE_DEG,
        altitude=config.ALTITUDE_M,  # field elevation; 400 ft AGL is aero-only
        tz=config.TIMEZONE,
    )


def day_times(date: str, freq: str = "1min") -> pd.DatetimeIndex:
    """Minute-resolution local-time index covering one civil day."""
    start = pd.Timestamp(date, tz=config.TIMEZONE)
    return pd.date_range(start, start + pd.Timedelta(days=1), freq=freq,
                         inclusive="left")


def solar_geometry(times: pd.DatetimeIndex) -> pd.DataFrame:
    """Sun elevation/azimuth/zenith (degrees) for the mission site."""
    return _location().get_solarposition(times)


def clearsky_irradiance(times: pd.DatetimeIndex) -> pd.DataFrame:
    """Clear-sky GHI/DNI/DHI (W/m^2) via the Ineichen model with the
    bundled Linke turbidity climatology."""
    return _location().get_clearsky(times, model="ineichen")


def poa_effective(times: pd.DatetimeIndex,
                  irradiance_scale: float = 1.0) -> pd.DataFrame:
    """Effective irradiance absorbed by a horizontal, fiberglass-encapsulated
    array (W/m^2), before cell efficiency.

    Components:
      * beam on horizontal = DNI * cos(zenith)  (the geometric sun-angle loss)
      * additional reflection loss at high incidence via a physical IAM model
        (air/glass interface; FLAGGED as representative of thin fiberglass)
      * diffuse with the standard ~0.95 effective IAM
      * encapsulation bulk transmission from config.

    `irradiance_scale` is the uncertainty knob (1.0 nominal).
    """
    solpos = solar_geometry(times)
    cs = clearsky_irradiance(times)

    zenith = solpos["apparent_zenith"].to_numpy()
    aoi = np.clip(zenith, 0.0, 90.0)  # horizontal panel: AOI == zenith
    iam_beam = pvlib.iam.physical(aoi)
    iam_diffuse = 0.95  # FLAGGED: standard sky-diffuse IAM approximation

    beam_h = cs["dni"].to_numpy() * np.cos(np.radians(np.clip(zenith, 0, 90)))
    beam_h = np.clip(beam_h, 0.0, None)
    poa = beam_h * iam_beam + cs["dhi"].to_numpy() * iam_diffuse
    poa_eff = poa * config.ENCAPSULATION_TRANSMISSION * irradiance_scale

    out = pd.DataFrame(index=times)
    out["ghi"] = cs["ghi"]
    out["poa_raw"] = beam_h + cs["dhi"].to_numpy()
    out["poa_eff"] = np.clip(poa_eff, 0.0, None)
    out["sun_elevation_deg"] = solpos["apparent_elevation"]
    return out


def ambient_temperature(times: pd.DatetimeIndex,
                        t_min_c: float = config.T_AMB_MIN_C,
                        t_max_c: float = config.T_AMB_MAX_C) -> np.ndarray:
    """Sinusoidal design-day air temperature: min at 05:00, max at 15:30.

    FLAGGED: replace with hourly TMY data if closure is tight.
    """
    hours = times.hour + times.minute / 60.0
    # Peak at 15.5 h, trough 10.5 h earlier.
    phase = 2 * np.pi * (hours - 15.5) / 24.0
    mean = 0.5 * (t_min_c + t_max_c)
    amp = 0.5 * (t_max_c - t_min_c)
    return mean + amp * np.cos(phase)


def noct_coefficient(date: str = config.SOLSTICE_DATE) -> float:
    """Calibrate k in T_cell = T_amb + k * POA so the solstice-noon static
    cell temperature equals config.CELL_T_MAX_C (75 C per the user)."""
    times = day_times(date)
    env = poa_effective(times)
    t_amb = ambient_temperature(times)
    i_noon = int(np.argmax(env["poa_eff"].to_numpy()))
    poa_noon = env["poa_eff"].iloc[i_noon]
    return (config.CELL_T_MAX_C - t_amb[i_noon]) / poa_noon


def cell_temperature(poa_eff: np.ndarray, t_amb_c: np.ndarray,
                     k: float | None = None) -> np.ndarray:
    """NOCT-style cell temperature (C). k defaults to the 75 C calibration.

    FLAGGED: static (no flight-airflow cooling) => conservative for energy.
    """
    if k is None:
        k = noct_coefficient()
    return t_amb_c + k * poa_eff


def design_day(date: str = config.SOLSTICE_DATE,
               irradiance_scale: float = 1.0) -> pd.DataFrame:
    """One-stop 24 h minute-resolution environment profile."""
    times = day_times(date)
    env = poa_effective(times, irradiance_scale=irradiance_scale)
    env["t_amb_c"] = ambient_temperature(times)
    env["t_cell_c"] = cell_temperature(env["poa_eff"].to_numpy(),
                                       env["t_amb_c"].to_numpy())
    return env


def window_scan(start: str = config.MISSION_WINDOW[0],
                end: str = config.MISSION_WINDOW[1],
                freq_days: int = 5) -> pd.DataFrame:
    """Scan the mission window: daily plane-of-array energy and dark hours.

    'dark' here = sun below 5 deg elevation, a proxy for array-useless time;
    the true battery-night is computed by the Phase 4 energy balance.
    """
    dates = pd.date_range(start, end, freq=f"{freq_days}D")
    rows = []
    for d in dates:
        prof = design_day(d.strftime("%Y-%m-%d"))
        dt_h = 1.0 / 60.0
        energy = prof["poa_eff"].sum() * dt_h / 1000.0        # kWh/m^2/day
        dark_h = float((prof["sun_elevation_deg"] < 5.0).sum()) * dt_h
        rows.append({"date": d, "poa_kwh_m2": energy, "dark_hours": dark_h})
    return pd.DataFrame(rows).set_index("date")
