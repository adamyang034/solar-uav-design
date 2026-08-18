"""Phase 2 — propeller databases: APC PER3 + Mejzlik 2-blade electrics.

APC publishes computer-generated performance files (vortex theory) for every
production prop. Mejzlik publishes datasheet PDFs and Ct/Cp workbooks for
carbon 2-blade electrics (in-house BEM / vortex). Both already tabulate the
nondimensional coefficients. Queries use the standard similarity laws
(McCormick; MIT 16.unified §11.7; SFTE propeller handbook):

    J  = V / (n D)                 n in rev/s
    T  = C_T(J) ρ n² D⁴
    P  = C_P(J) ρ n³ D⁵
    η  = J C_T / C_P

C_T(J) and C_P(J) come from the published maps. Queries use the
manufacturer T,P when that speed is on a map block. Similarity is the
sanity check, and the fallback only when the map does not cover the
point and the blade is still below zero-thrust J. n²-scaling RPM down
at fixed speed is not allowed: that invented a 22×12E cruise past
zero-thrust.

IMPORTANT: both sources are computational, not measured. Wrapper methods
apply the FLAGGED uncertainty factors from config (thrust derated, power
inflated) unless nominal=True; calibrate against a thrust stand in Phase 6.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from .. import config

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "apc"
DOWNLOADS_PAGE = "https://www.apcprop.com/technical-information/file-downloads/"
# APC sits behind Cloudflare; a real browser UA + referer is required.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0 Safari/537.36"),
    "Referer": DOWNLOADS_PAGE,
    "Accept": "*/*",
}

# Unit conversions for the first 8 (imperial) columns of every PER3 block.
MPH_TO_MS = 0.44704
HP_TO_W = 745.699872
INLBF_TO_NM = 0.1129848
LBF_TO_N = 4.4482216
IN_TO_M = 0.0254
# Standard-atmosphere sea-level density used to reconstruct APC dimensional
# T, P from C_T, C_P. Verified on 22x12E static: C_T ρ n² D⁴ matches PER3 N.
APC_RHO_REF = 1.225


def download_database(dest: Path = DATA_DIR, force: bool = False) -> Path:
    """Download and extract the full APC performance-file archive."""
    dest.mkdir(parents=True, exist_ok=True)
    existing = list(dest.glob("PER3_*.dat")) + list(dest.glob("PER3_*.DAT"))
    if existing and not force:
        return dest

    page = requests.get(DOWNLOADS_PAGE, timeout=60, headers=HEADERS)
    page.raise_for_status()
    links = re.findall(r'href="([^"]+\.zipx?[^"]*)"', page.text, flags=re.I)
    zip_links = [l for l in links if "perfile" in l.lower()]
    if not zip_links:
        raise RuntimeError("No PERFILES archive link on APC downloads page")
    url = zip_links[0]
    if url.startswith("/"):
        url = "https://www.apcprop.com" + url

    resp = requests.get(url, timeout=300, headers=HEADERS)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        for member in zf.namelist():
            name = Path(member).name
            if name.lower().endswith(".dat") and "per3" in name.lower():
                (dest / name).write_bytes(zf.read(member))
    return dest


def _infer_geometry(stem: str) -> tuple[float | None, float | None, str]:
    """Diameter/pitch (inches) + style suffix from a PER3 filename stem,
    handling implied decimals (e.g. '1225x375' = 12.25 x 3.75)."""
    m = re.match(r"^(\d+)x(\d+)(.*)$", stem, flags=re.I)
    if not m:
        return None, None, stem

    def plausible(raw: str, lo: float, hi: float) -> float | None:
        for div in (1.0, 10.0, 100.0):
            v = float(raw) / div
            if lo <= v <= hi:
                return v
        return None

    dia = plausible(m.group(1), 3.5, 30.0)
    pitch = plausible(m.group(2), 1.0, 25.0)
    return dia, pitch, m.group(3)


def build_index(data_dir: Path = DATA_DIR) -> pd.DataFrame:
    rows = []
    for f in sorted(data_dir.glob("PER3_*.dat")):
        stem = f.stem.replace("PER3_", "")
        dia, pitch, style = _infer_geometry(stem)
        rows.append({"name": stem, "file": str(f), "diameter_in": dia,
                     "pitch_in": pitch, "style": style})
    return pd.DataFrame(rows)


def parse_per3(path: str | Path) -> pd.DataFrame:
    """Parse one PER3 file into a tidy DataFrame in SI units.

    Columns: rpm, v_ms, j, eta, ct, cp, power_w, torque_nm, thrust_n
    """
    rpm = None
    records = []
    for raw in Path(path).read_text(errors="ignore").splitlines():
        line = raw.strip()
        m = re.search(r"PROP RPM\s*=\s*(\d+)", line)
        if m:
            rpm = float(m.group(1))
            continue
        if rpm is None or not line:
            continue
        parts = line.split()
        try:
            vals = [float(p) for p in parts]
        except ValueError:
            continue
        if len(vals) < 8:
            continue
        v_mph, j, pe, ct, cp, pwr_hp, torque_inlbf, thrust_lbf = vals[:8]
        records.append({
            "rpm": rpm,
            "v_ms": v_mph * MPH_TO_MS,
            "j": j,
            "eta": pe,
            "ct": ct,
            "cp": cp,
            "power_w": pwr_hp * HP_TO_W,
            "torque_nm": torque_inlbf * INLBF_TO_NM,
            "thrust_n": thrust_lbf * LBF_TO_N,
        })
    df = pd.DataFrame(records)
    if df.empty:
        raise ValueError(f"No data parsed from {path}")
    return df


_MASS_CACHE: dict[str, float] = {}


def estimate_prop_mass_kg(diameter_in: float,
                          name: str | None = None) -> float:
    """Mass of one propeller.

    Named Mejzlik / APC props use the catalog (datasheet grams for Mejzlik,
    APC thin-electric power law otherwise). Diameter-only is the APC fit:
    10x7E 24 g, 16x10E 57 g, 18x8E 76 g. FLAGGED until the chosen prop is
    weighed.
    """
    if name:
        if name not in _MASS_CACHE:
            try:
                _MASS_CACHE[name] = float(Propeller.load(name).mass_kg)
            except Exception:
                _MASS_CACHE[name] = 0.263e-3 * float(diameter_in) ** 1.96
        return _MASS_CACHE[name]
    return 0.263e-3 * float(diameter_in) ** 1.96


def combined_index() -> pd.DataFrame:
    """APC electric archive plus Mejzlik 2-blade electric maps."""
    from . import mejzlik
    apc = build_index()
    if apc.empty:
        apc = pd.DataFrame(columns=["name", "file", "diameter_in",
                                    "pitch_in", "style"])
    apc = apc.copy()
    apc["manufacturer"] = "apc"
    apc["vendor_name"] = apc["name"]
    apc["mass_kg"] = np.nan
    apc["datasheet"] = ""
    try:
        mj = mejzlik.build_index()
    except Exception:
        mj = pd.DataFrame()
    if mj.empty:
        return apc
    cols = ["name", "vendor_name", "file", "datasheet", "diameter_in",
            "pitch_in", "style", "manufacturer", "mass_kg"]
    for c in cols:
        if c not in apc.columns:
            apc[c] = "" if c in ("vendor_name", "datasheet") else np.nan
        if c not in mj.columns:
            mj[c] = "" if c in ("vendor_name", "datasheet") else np.nan
    return pd.concat([apc[cols], mj[cols]], ignore_index=True)


@dataclass
class Propeller:
    """Queryable performance model for one APC or Mejzlik prop."""

    name: str
    data: pd.DataFrame = field(repr=False)
    diameter_in: float | None = None
    pitch_in: float | None = None
    manufacturer: str = "apc"
    catalog_mass_kg: float | None = None
    vendor_name: str | None = None
    rho_ref: float = APC_RHO_REF

    @classmethod
    def load(cls, name: str, data_dir: Path | None = None) -> "Propeller":
        key = name.strip().lower()
        if key.startswith("mj-") or "2b e" in key:
            from . import mejzlik
            mejzlik.download_database()
            row, data = mejzlik.load_map(name)
            mass = row["mass_kg"]
            return cls(
                name=row["name"], data=data,
                diameter_in=float(row["diameter_in"]),
                pitch_in=float(row["pitch_in"]),
                manufacturer="mejzlik",
                catalog_mass_kg=(None if pd.isna(mass) else float(mass)),
                vendor_name=row["vendor_name"],
                rho_ref=1.221,
            )
        idx = build_index(data_dir or DATA_DIR)
        row = idx[idx["name"].str.lower() == key]
        if row.empty:
            # Vendor string for a Mejzlik prop ("21x13 2B E L").
            from . import mejzlik
            try:
                mejzlik.download_database()
                mrow, data = mejzlik.load_map(name)
                mass = mrow["mass_kg"]
                return cls(
                    name=mrow["name"], data=data,
                    diameter_in=float(mrow["diameter_in"]),
                    pitch_in=float(mrow["pitch_in"]),
                    manufacturer="mejzlik",
                    catalog_mass_kg=(None if pd.isna(mass) else float(mass)),
                    vendor_name=mrow["vendor_name"],
                    rho_ref=1.221,
                )
            except KeyError:
                pass
            raise KeyError(f"Prop {name!r} not in APC or Mejzlik index")
        r = row.iloc[0]
        return cls(name=r["name"], data=parse_per3(r["file"]),
                   diameter_in=r["diameter_in"], pitch_in=r["pitch_in"],
                   manufacturer="apc", vendor_name=r["name"])

    @property
    def mass_kg(self) -> float:
        if self.catalog_mass_kg is not None and np.isfinite(self.catalog_mass_kg):
            return float(self.catalog_mass_kg)
        return 0.263e-3 * (self.diameter_in or 12.0) ** 1.96

    @property
    def diameter_m(self) -> float:
        return float(self.diameter_in or 0.0) * IN_TO_M

    @property
    def rpm_grid(self) -> np.ndarray:
        return np.sort(self.data["rpm"].unique())

    def _blocks(self) -> dict[float, pd.DataFrame]:
        if not hasattr(self, "_block_cache"):
            self._block_cache = {rpm: self.data[self.data["rpm"] == rpm]
                                 for rpm in self.rpm_grid}
        return self._block_cache

    @property
    def j_windmill(self) -> float:
        """Smallest J at which C_T crosses zero (conservative across RPM)."""
        if not hasattr(self, "_j_windmill"):
            zeros: list[float] = []
            for blk in self._blocks().values():
                j = blk["j"].to_numpy(dtype=float)
                ct = blk["ct"].to_numpy(dtype=float)
                order = np.argsort(j)
                j, ct = j[order], ct[order]
                neg = np.where(ct <= 0.0)[0]
                if neg.size:
                    i = int(neg[0])
                    if i == 0:
                        zeros.append(float(j[0]))
                    else:
                        j0, j1 = float(j[i - 1]), float(j[i])
                        c0, c1 = float(ct[i - 1]), float(ct[i])
                        zeros.append(j0 if abs(c1 - c0) < 1e-12 else
                                     j0 + (0.0 - c0) * (j1 - j0) / (c1 - c0))
                elif j.size:
                    zeros.append(float(j[-1]))
            self._j_windmill = float(np.min(zeros)) if zeros else 0.0
        return self._j_windmill

    def advance_ratio(self, v_ms: float, rpm: float) -> float:
        n = float(rpm) / 60.0
        d = self.diameter_m
        if n * d <= 0.0:
            return np.inf
        return float(v_ms) / (n * d)

    def _ct_cp(self, j: float) -> tuple[float, float]:
        """Conservative C_T, C_P at advance ratio J.

        Each RPM block is interpolated in J. Across Reynolds (RPM), average
        the coefficients — C_T(J) and C_P(J) are first-order independent of
        n. Past windmill J, C_T is zero.
        """
        if not np.isfinite(j) or j < 0.0:
            return np.nan, np.nan
        if j >= self.j_windmill:
            return 0.0, np.nan
        cts: list[float] = []
        cps: list[float] = []
        for blk in self._blocks().values():
            jj = blk["j"].to_numpy(dtype=float)
            if jj.size < 2 or j < jj.min() or j > jj.max():
                continue
            order = np.argsort(jj)
            jj = jj[order]
            cts.append(float(np.interp(j, jj, blk["ct"].to_numpy(dtype=float)[order])))
            cps.append(float(np.interp(j, jj, blk["cp"].to_numpy(dtype=float)[order])))
        if not cts:
            return np.nan, np.nan
        # First-order similarity: C_T and C_P depend on J, not RPM. Mean
        # across the RPM blocks that contain this J. Do not pair min C_T
        # with max C_P from different Reynolds numbers — that is a second
        # stacked knockdown, not the textbook law.
        return float(np.mean(cts)), float(np.mean(cps))

    def _rho(self, rho: float | None) -> float:
        return self.rho_ref if rho is None else float(rho)

    def _table_at_v(self, col: str, v_ms: float) -> tuple[np.ndarray, np.ndarray]:
        """Hard map: column vs RPM, only at RPM blocks that include this speed."""
        rpms: list[float] = []
        vals: list[float] = []
        for rpm, blk in self._blocks().items():
            vv = blk["v_ms"].to_numpy(dtype=float)
            if vv.size < 2 or v_ms < vv.min() - 1e-9 or v_ms > vv.max() + 1e-9:
                continue
            order = np.argsort(vv)
            y = blk[col].to_numpy(dtype=float)[order]
            rpms.append(float(rpm))
            vals.append(float(np.interp(v_ms, vv[order], y)))
        if not rpms:
            return np.array([]), np.array([])
        order = np.argsort(rpms)
        return np.asarray(rpms)[order], np.asarray(vals)[order]

    def _table_query(self, col: str, v_ms: float, rpm: float) -> float:
        rpms, vals = self._table_at_v(col, v_ms)
        if rpms.size == 0 or rpm < rpms[0] - 1e-6 or rpm > rpms[-1] + 1e-6:
            return np.nan
        return float(np.interp(rpm, rpms, vals))

    def _dim(self, v_ms: float, rpm: float, rho: float) -> tuple[float, float, float]:
        """Similarity: (thrust N, shaft W, torque N·m) from C_T(J), C_P(J)."""
        d = self.diameter_m
        n = float(rpm) / 60.0
        if d <= 0.0 or n <= 0.0:
            return np.nan, np.nan, np.nan
        j = float(v_ms) / (n * d)
        ct, cp = self._ct_cp(j)
        if not np.isfinite(ct):
            return np.nan, np.nan, np.nan
        t = ct * rho * n ** 2 * d ** 4
        if not np.isfinite(cp) or cp <= 0.0:
            return t, np.nan, np.nan
        p = cp * rho * n ** 3 * d ** 5
        q = p / (2.0 * np.pi * n)
        return float(t), float(p), float(q)

    def _from_table(self, v_ms: float, rpm: float, rho: float
                    ) -> tuple[float, float, float]:
        """Hard map T,P,Q at (V, RPM), scaled to flight density. NaN if off map."""
        t = self._table_query("thrust_n", v_ms, rpm)
        p = self._table_query("power_w", v_ms, rpm)
        q = self._table_query("torque_nm", v_ms, rpm)
        if not np.isfinite(t):
            return np.nan, np.nan, np.nan
        scale = rho / max(self.rho_ref, 1e-9)
        t = t * scale
        p = p * scale if np.isfinite(p) else np.nan
        q = q * scale if np.isfinite(q) else np.nan
        return t, p, q

    def _prefer(self, v_ms: float, rpm: float, rho: float
                ) -> tuple[float, float, float, str]:
        """Table if the point is on the map, else similarity."""
        t_t, p_t, q_t = self._from_table(v_ms, rpm, rho)
        if np.isfinite(t_t):
            return t_t, p_t, q_t, "table"
        t_s, p_s, q_s = self._dim(v_ms, rpm, rho)
        return t_s, p_s, q_s, "similarity"

    def _sanity(self, v_ms: float, rpm: float, rho: float,
                t: float, p: float, source: str) -> str | None:
        """Flag if table and similarity disagree by more than PROP_SANITY_REL."""
        t_t, p_t, _ = self._from_table(v_ms, rpm, rho)
        t_s, p_s, _ = self._dim(v_ms, rpm, rho)
        notes = []
        if source == "similarity":
            notes.append(
                f"FLAG {self.name}: ({v_ms:.2f} m/s, {rpm:.0f} rpm) not on "
                f"the map; used C_T(J) similarity")
        if np.isfinite(t_t) and np.isfinite(t_s) and max(abs(t_t), abs(t_s)) > 1e-6:
            rel_t = abs(t_t - t_s) / max(abs(t_t), abs(t_s))
            if rel_t > config.PROP_SANITY_REL:
                notes.append(
                    f"FLAG {self.name}: thrust table {t_t:.2f} N vs "
                    f"similarity {t_s:.2f} N ({rel_t:.0%}) at {rpm:.0f} rpm, "
                    f"{v_ms:.2f} m/s")
        if np.isfinite(p_t) and np.isfinite(p_s) and max(abs(p_t), abs(p_s)) > 1e-6:
            rel_p = abs(p_t - p_s) / max(abs(p_t), abs(p_s))
            if rel_p > config.PROP_SANITY_REL:
                notes.append(
                    f"FLAG {self.name}: shaft power table {p_t:.1f} W vs "
                    f"similarity {p_s:.1f} W ({rel_p:.0%}) at {rpm:.0f} rpm, "
                    f"{v_ms:.2f} m/s")
        if np.isfinite(t) and t <= 0.0:
            notes.append(
                f"FLAG {self.name}: no pull at {rpm:.0f} rpm, {v_ms:.2f} m/s "
                f"(past zero-thrust advance ratio {self.j_windmill:.2f})")
        return "; ".join(notes) if notes else None

    # -- queries: table first, similarity to fill / check --------------------
    def thrust_n(self, v_ms: float, rpm: float, nominal: bool = False,
                 rho: float | None = None) -> float:
        rho_use = self._rho(rho)
        t, _, _, _ = self._prefer(v_ms, rpm, rho_use)
        return t if nominal else t * config.PROP_THRUST_DERATE

    def shaft_power_w(self, v_ms: float, rpm: float, nominal: bool = False,
                      rho: float | None = None) -> float:
        rho_use = self._rho(rho)
        _, p, _, _ = self._prefer(v_ms, rpm, rho_use)
        return p if nominal else p * config.PROP_POWER_INFLATE

    def torque_nm(self, v_ms: float, rpm: float, nominal: bool = False,
                  rho: float | None = None) -> float:
        rho_use = self._rho(rho)
        _, _, q, _ = self._prefer(v_ms, rpm, rho_use)
        return q if nominal else q * config.PROP_POWER_INFLATE

    def static_thrust_n(self, rpm: float, nominal: bool = False,
                        rho: float | None = None) -> float:
        return self.thrust_n(0.0, rpm, nominal, rho=rho)

    def _similarity_op(self, t_need: float, v_ms: float, rho: float,
                       thrust_req_n: float) -> dict | None:
        """Solve T = C_T(J) ρ n² D⁴. No solution if J ≥ J_windmill."""
        d = self.diameter_m
        rpm_lo = float(self.rpm_grid.min())
        rpm_hi = float(self.rpm_grid.max())
        n_lo, n_hi = rpm_lo / 60.0, rpm_hi / 60.0
        j_w = self.j_windmill

        def at_j(j: float) -> tuple[float, float, float, float]:
            ct, cp = self._ct_cp(j)
            n = float(v_ms) / (j * d) if j > 0.0 else np.inf
            if not np.isfinite(ct) or ct <= 0.0 or not np.isfinite(n):
                return 0.0, np.nan, np.nan, n
            t = ct * rho * n ** 2 * d ** 4
            if not np.isfinite(cp) or cp <= 0.0:
                return t, np.nan, np.nan, n
            p = cp * rho * n ** 3 * d ** 5
            q = p / (2.0 * np.pi * n)
            return t, p, q, n

        if float(v_ms) < 1e-6:
            ct0, cp0 = self._ct_cp(0.0)
            if not np.isfinite(ct0) or ct0 <= 0.0:
                return None
            n = np.sqrt(t_need / (ct0 * rho * d ** 4))
            rpm = float(n * 60.0)
            if rpm < rpm_lo - 1.0 or rpm > rpm_hi + 1.0:
                return None
            p = cp0 * rho * n ** 3 * d ** 5
            q = p / (2.0 * np.pi * n)
            if not np.isfinite(p) or p <= 0.0:
                return None
            return {"rpm": rpm, "thrust_n": float(thrust_req_n),
                    "torque_nm": float(q), "shaft_power_w": float(p),
                    "j": 0.0, "source": "similarity"}

        j_min = float(v_ms) / (n_hi * d)
        j_max = min(j_w - 1e-4, float(v_ms) / (n_lo * d))
        if j_min >= j_w or j_max <= j_min:
            return None
        js = np.linspace(j_min, j_max, 80)
        ts = np.array([at_j(j)[0] for j in js])
        if not np.isfinite(ts[0]) or ts[0] < t_need:
            return None
        below = np.where(ts < t_need)[0]
        if below.size == 0:
            j = float(js[-1])
        else:
            i = int(below[0])
            if i == 0:
                return None
            t0, t1 = float(ts[i - 1]), float(ts[i])
            j0, j1 = float(js[i - 1]), float(js[i])
            j = j0 if abs(t1 - t0) < 1e-12 else j0 + (t_need - t0) * (j1 - j0) / (t1 - t0)
        t, p, q, n = at_j(j)
        if not np.isfinite(p) or p <= 0.0 or not np.isfinite(n):
            return None
        rpm = float(n * 60.0)
        if rpm < rpm_lo - 1.0 or rpm > rpm_hi + 1.0:
            return None
        return {
            "rpm": rpm,
            "thrust_n": float(thrust_req_n),
            "torque_nm": float(q),
            "shaft_power_w": float(p),
            "j": float(j),
            "source": "similarity",
        }

    def operating_point(self, thrust_req_n: float, v_ms: float,
                        nominal: bool = False,
                        rho: float | None = None) -> dict | None:
        """RPM that produces thrust_req_n at airspeed v_ms.

        Uses the manufacturer map when that speed is tabulated. Similarity
        is the check, and the fallback only if the map does not cover the
        point and the advance ratio is still below windmill. Never n²-scales
        RPM below the first map block that covers this speed.
        """
        rho_use = self._rho(rho)
        d = self.diameter_m
        if d <= 0.0 or thrust_req_n <= 0.0 or not np.isfinite(thrust_req_n):
            return None
        scale = 1.0 if nominal else config.PROP_THRUST_DERATE
        t_need = float(thrust_req_n) / max(scale, 1e-9)

        op = None
        rpms, thrusts = self._table_at_v("thrust_n", v_ms)
        if rpms.size:
            thrusts = thrusts * (rho_use / max(self.rho_ref, 1e-9))
            if float(thrusts.max()) >= t_need:
                above = np.where(thrusts >= t_need)[0]
                i_hi = int(above[0])
                if i_hi > 0:
                    t0, t1 = float(thrusts[i_hi - 1]), float(thrusts[i_hi])
                    r0, r1 = float(rpms[i_hi - 1]), float(rpms[i_hi])
                    rpm = r1 if abs(t1 - t0) < 1e-9 else (
                        r0 + (t_need - t0) * (r1 - r0) / (t1 - t0))
                    t, p, q = self._from_table(v_ms, rpm, rho_use)
                    if np.isfinite(p) and p > 0.0:
                        op = {
                            "rpm": float(rpm),
                            "thrust_n": float(thrust_req_n),
                            "torque_nm": float(q),
                            "shaft_power_w": float(p),
                            "j": self.advance_ratio(v_ms, rpm),
                            "source": "table",
                        }
                # i_hi == 0: first covering RPM already makes enough thrust.
                # Slowing further would walk toward windmill. Do not n²-scale.

        if op is None:
            op = self._similarity_op(t_need, v_ms, rho_use, thrust_req_n)
            if op is None:
                return None

        t_used, p_used, _, _ = self._prefer(v_ms, op["rpm"], rho_use)
        note = self._sanity(v_ms, op["rpm"], rho_use, t_used, p_used, op["source"])
        if note:
            op["notes"] = note
        return op
