# Conventional optimizer (fork)

Clone of the single-empennage toolchain so that folder's results stay
untouched.

**Layout:** one fuselage, one tractor motor/prop, one centerline boom,
conventional tail (H-stab in the wing plane, one V-stab further aft).
No H-stab solar. Packs cap at 3. Props need not be sold in both
rotations.

**Construction:** single 1.5 in boom (FLAGGED: one load path vs two 1 in
twin-boom tubes). Fuselage and ESC fixed masses are not halved.

```bash
.venv/bin/python conventional/scripts/run_phase34.py --search
.venv/bin/python conventional/scripts/visualize.py
```

Viewer (Phase 4 winner): `http://127.0.0.1:8101/`.
`data/` is a symlink to the parent repository (prop maps, polars).
