"""Configuration restrictions shared by the study runner and viewer builder."""

RECTANGULAR_LAYOUT = "conventional_rectangular"
RECTANGULAR_GEOMETRY = {
    "taper_ratio": 1.0,
    "taper_start_frac": 1.0,
    "washout_tip_deg": 0.0,
    "washout_start_frac": 0.0,
}


def apply_layout(config, layout):
    """Call before importing optimize, including in spawned workers."""
    if layout != RECTANGULAR_LAYOUT:
        return
    config.FIXED_GEOMETRY = dict(RECTANGULAR_GEOMETRY)
    config.CONTINUOUS = dict(config.CONTINUOUS)
    for key, value in RECTANGULAR_GEOMETRY.items():
        config.CONTINUOUS[key] = (value, value, value)
    # Remove constant coordinates, rather than fitting zero-width dimensions.
    config.OPT_KEYS = tuple(k for k in config.OPT_KEYS if k not in RECTANGULAR_GEOMETRY)
    config.OPT_START = {k: config.CONTINUOUS[k][2] for k in config.OPT_KEYS}
    config.TAPER_RATIO_BOUNDS = (1.0, 1.0)
    config.TAPER_START_BOUNDS = (1.0, 1.0)
    config.WASHOUT_TIP_BOUNDS_DEG = (0.0, 0.0)
    config.WASHOUT_START_BOUNDS = (0.0, 0.0)


def validate_layout(design, layout):
    if layout == RECTANGULAR_LAYOUT:
        for key, value in RECTANGULAR_GEOMETRY.items():
            if getattr(design, key) != value:
                raise ValueError(f"{layout} requires {key}={value}")
