# Split-empennage optimizer (fork)

Clone of the π-tail toolchain so that folder's results stay untouched.

**Layout:** two identical fuselages, each with its own T-tail. No bridging
H-stab, no H-stab solar. Tails are **not** sized from `V_H`/`V_V`. The
H-stab is inverted from `SM_MIN = 0.08`. Fins are structural T-tail posts
(boom fitting); weathercock, yaw damping, and differential-thrust yaw
are not constraints. No T-tail downwash credit.

**Construction:** tail surfaces and H-stab/V-stab interfaces are 0.75× the
π-tail areal build (user, FLAGGED until weigh-in). Carbon booms start at
the wing trailing edge, not at c/4.

```bash
.venv/bin/python split_empennage/scripts/run_phase34.py
.venv/bin/python split_empennage/scripts/visualize.py
```

Viewer: `split_empennage/outputs/aircraft_viewer.html`.
`data/` is a symlink to the parent repository (prop maps, polars).
