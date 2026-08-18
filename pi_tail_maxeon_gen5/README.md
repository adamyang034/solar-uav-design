# π-tail optimizer — Maxeon Gen 5 (Kn)

Clone of the single-empennage toolchain with Maxeon Gen 5 cells. Root
`solar_uav/` stays C60.

**Layout:** twin-boom π-tail. One H-stab spans the booms. H-stab chord
floor is one cell row (elevator keep-out), not a full Voc-legal string.

**Cells:** Kn bin (5.84 W, 22.6%), 161.7 mm, 167 mm pitch, 11.6 g.
GVB-8 8 A input is **FLAGGED** and not a search hard-fail (Kn Imp 9.88 A).

```bash
.venv/bin/python pi_tail_maxeon_gen5/scripts/run_phase34.py
.venv/bin/python pi_tail_maxeon_gen5/scripts/run_phase34.py --search
.venv/bin/python pi_tail_maxeon_gen5/scripts/visualize.py
```

Viewer: `http://127.0.0.1:8100/`.
`data/` is a symlink to the parent repository (prop maps, polars).
