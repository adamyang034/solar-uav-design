"""Mejzlik 2-blade electric propeller catalog.

Mejzlik publishes a datasheet PDF (mass, limit RPM, geometry) and a
forward-flight performance workbook (Ct, Cp vs airspeed at tabulated RPM)
for off-the-shelf carbon electrics: https://www.mejzlik.eu/propeller-data

The workbooks are manufacturer in-house simulation (lifting-line / BEM /
vortex), same class of data as APC PER3. Apply the same FLAGGED thrust
derate / power inflate unless Phase 6 thrust-stand data says otherwise.
AirShaper vs Brno tunnel on the 21x13 2B E L showed the in-house Ct about
8–12% high at J = 0.2–0.4.

Only 2-blade electric (2B E / E L / E W) maps are ingested. Gas, MC,
folding, 3-blade, and pusher-front props are skipped.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "mejzlik"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0 Safari/537.36"),
    "Referer": "https://www.mejzlik.eu/propeller-data",
    "Accept": "*/*",
}
FILES_BASE = "https://www.mejzlik.eu/files"
IN_TO_M = 0.0254

# Dealer masses (Esprit, 2026) used only if the datasheet PDF is missing.
# FLAGGED: replace with the PDF "Mass [g]" once every file is on disk.
DEALER_MASS_G = {
    "18x8 2B E L": 28.0,
    "18x10 2B E L": 28.0,
    "20x8 2B E L": 34.0,
    "20x10 2B E L": 36.0,
    "20x12 2B E L": 36.0,
    "20x13 2B E L": 41.0,
    "20.5x12 2B E L W": 45.0,
    "21x13 2B E L": 38.0,   # Mejzlik datasheet PN 421135
    "21x14 2B E L": 40.0,
    "22x10 2B E L": 45.0,
    "22x12 2B E W": 50.0,
    "23x8 2B E L": 54.0,
    "23x10 2B E L": 54.0,
    "24x10 2B E L": 55.0,
    "26x15 2B E L": 95.0,
}


# Vendor filename stems on mejzlik.eu/files. Performance is xlsx or zip.
CATALOG: tuple[dict, ...] = (
    {"vendor": "18x8 2B E",
     "datasheet": "18x8-2b-e-rev03.pdf",
     "performance": "18x8-2b-e-fc-0-55ms-1000-9900rpm.xlsx"},
    {"vendor": "18x8 2B E L",
     "datasheet": "18x8-2b-e-l-rev03.pdf",
     "performance": "18x8-2b-e-l-fc-0-55ms-1000-9900rpm.xlsx"},
    {"vendor": "18x10 2B E",
     "datasheet": "18x10-2b-e-datasheet.pdf",
     "performance": "18x10-2b-e-performance.zip"},
    {"vendor": "20x8 2B E",
     "datasheet": "20x8-2b-e-rev30.pdf",
     "performance": "20x8-2b-e-fc-0-55ms-1000-8900rpm.xlsx"},
    {"vendor": "20x8 2B E L",
     "datasheet": "20x8-2b-e-l-rev30.pdf",
     "performance": "20x8-2b-e-l-fc-0-55ms-1000-8900rpm.xlsx"},
    {"vendor": "20x10 2B E",
     "datasheet": "20x10-2b-e-rev30.pdf",
     "performance": "20x10-2b-e-fc-0-55ms-1000-8900rpm.xlsx"},
    {"vendor": "20x10 2B E L",
     "datasheet": "20x10-2b-e-l-rev30.pdf",
     "performance": "20x10-2b-e-l-fc-0-55ms-1000-8900rpm.xlsx"},
    {"vendor": "20x11 2B E",
     "datasheet": "20x11-2b-e-rev03.pdf",
     "performance": "20x11-2b-e-fc-0-55ms-1000-8900rpm.xlsx"},
    {"vendor": "20x11 2B E W",
     "datasheet": "20x11-2b-e-w-rev03.pdf",
     "performance": "20x11-2b-w-e-fc-0-55ms-1000-8900rpm.xlsx"},
    {"vendor": "20x11 2B E W L",
     "datasheet": "20x11-2b-e-w-l-rev30.pdf",
     "performance": "20x11-2b-we-l-fc-0-55ms-1000-8900rpm.xlsx"},
    {"vendor": "20x13 2B E",
     "datasheet": "20x13-2b-e-rev30.pdf",
     "performance": "20x13-2b-e-fc-0-55ms-1000-8900rpm.xlsx"},
    {"vendor": "20x13 2B E L",
     "datasheet": "20x13-2b-e-l-rev30.pdf",
     "performance": "20x13-2b-e-l-fc-0-55ms-1000-8900rpm.xlsx"},
    {"vendor": "20.5x12 2B E W",
     "datasheet": "205x12-2b-e-w-rev30.pdf",
     "performance": "205x12-2b-we-fc-0-55ms-1000-8700rpm.xlsx"},
    {"vendor": "20.5x12 2B E L W",
     "datasheet": "205x12-2b-e-l-w-datasheet.pdf",
     "performance": "205x12-2b-e-l-w-performance.zip"},
    {"vendor": "21x10 2B E L",
     "datasheet": "21x10-2b-e-l-datasheet-1.pdf",
     "performance": "21x10-2b-e-l-performance-1.zip"},
    {"vendor": "21x13 2B E",
     "datasheet": "21x13-2b-e-datasheet.pdf",
     "performance": "21x13-2b-e-performance.zip"},
    {"vendor": "21x13 2B E L",
     "datasheet": "21x13-2b-e-l-datasheet.pdf",
     "performance": "21x13-2b-e-l-performance.zip"},
    {"vendor": "21x13.5 2B E L",
     "datasheet": "21x135-2b-e-l-datasheet.pdf",
     "performance": "21x135-2b-e-l-performance.zip"},
    {"vendor": "21x14 2B E L",
     "datasheet": "21x14-2b-e-l-datasheet.pdf",
     "performance": "21x14-2b-e-l-performance.zip"},
    {"vendor": "22x12 2B E W",
     "datasheet": "22x12-2b-e-w-datasheet.pdf",
     "performance": "22x12-2b-e-w-performance.zip"},
    {"vendor": "23x8 2B E",
     "datasheet": "23x8-2b-e-datasheet.pdf",
     "performance": "23x8-2b-e-performance.zip"},
    {"vendor": "23x8 2B E L",
     "datasheet": "23x8-2b-e-l-datasheet.pdf",
     "performance": "23x8-2b-e-l-performance.zip"},
    {"vendor": "24x10 2B E L",
     "datasheet": "24x10-2b-e-l-datasheet.pdf",
     "performance": "24x10-2b-e-l-performance.xlsx"},
    {"vendor": "26x15 2B E",
     "datasheet": "26x15-2b-e-datasheet.pdf",
     "performance": "26x15-2b-e-performance.zip"},
    {"vendor": "26x15 2B E L",
     "datasheet": "26x15-2b-e-l-datasheet.pdf",
     "performance": "26x15-2b-e-l-performance.zip"},
)


def catalog_name(vendor: str) -> str:
    """Solver name: MJ-21x13EL, unique vs APC 21x13E."""
    m = re.match(
        r"^(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)\s+2B\s+E(.*)$", vendor.strip(), re.I)
    if not m:
        slug = re.sub(r"[^A-Za-z0-9]+", "", vendor)
        return f"MJ-{slug}"
    rest = re.sub(r"\s+", "", m.group(3).upper())
    suffix = rest if rest.startswith("E") else ("E" + rest)
    if not suffix:
        suffix = "E"
    dia, pitch = m.group(1), m.group(2)
    if "." in dia:
        dia = dia.replace(".", "p")
    if "." in pitch:
        pitch = pitch.replace(".", "p")
    return f"MJ-{dia}x{pitch}{suffix}"


def _geometry(vendor: str) -> tuple[float, float, str]:
    m = re.match(
        r"^(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)\s+2B\s+(E.*)$", vendor.strip(), re.I)
    if not m:
        return float("nan"), float("nan"), vendor
    style = re.sub(r"\s+", "", m.group(3).upper())  # E, EL, EW, EWL
    return float(m.group(1)), float(m.group(2)), style


def _fetch(url: str) -> bytes:
    resp = requests.get(url, timeout=120, headers=HEADERS)
    resp.raise_for_status()
    return resp.content


def _extract_xlsx_bytes(raw: bytes, filename: str) -> bytes:
    if filename.lower().endswith(".zip") or raw[:2] == b"PK" and filename.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            xlsx = [n for n in zf.namelist()
                    if n.lower().endswith(".xlsx") and not n.startswith("__")]
            if not xlsx:
                raise RuntimeError(f"No xlsx inside {filename}")
            return zf.read(xlsx[0])
    return raw


def download_database(dest: Path = DATA_DIR, force: bool = False) -> Path:
    """Download datasheet PDFs and performance workbooks for 2B electrics."""
    ds_dir = dest / "datasheets"
    map_dir = dest / "maps"
    ds_dir.mkdir(parents=True, exist_ok=True)
    map_dir.mkdir(parents=True, exist_ok=True)
    for row in CATALOG:
        name = catalog_name(row["vendor"])
        pdf_path = ds_dir / f"{name}.pdf"
        xlsx_path = map_dir / f"{name}.xlsx"
        if force or not pdf_path.exists():
            try:
                pdf_path.write_bytes(_fetch(f"{FILES_BASE}/{row['datasheet']}"))
            except Exception as exc:
                print(f"  skip datasheet {name}: {exc}")
        if force or not xlsx_path.exists():
            try:
                raw = _fetch(f"{FILES_BASE}/{row['performance']}")
                xlsx_path.write_bytes(_extract_xlsx_bytes(raw, row["performance"]))
            except Exception as exc:
                print(f"  skip map {name}: {exc}")
    idx = build_index(dest, rescan=True)
    if not idx.empty:
        idx.to_csv(dest / "catalog.csv", index=False)
    return dest


def _pdf_text(path: Path) -> str:
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def parse_datasheet_mass_kg(pdf_path: Path) -> float | None:
    """Mass [g] from the Mejzlik datasheet first page."""
    try:
        text = _pdf_text(pdf_path)
    except Exception:
        return None
    m = re.search(r"Mass\s*\[g\]\s*:\s*([0-9]+(?:\.[0-9]+)?)", text, re.I)
    if m:
        return float(m.group(1)) / 1000.0
    m = re.search(r"\b([0-9]+(?:\.[0-9]+)?)\s*g\b", text)
    if m:
        return float(m.group(1)) / 1000.0
    return None


def parse_performance_xlsx(path: Path) -> pd.DataFrame:
    """Workbook → SI table matching APC columns.

    Mejzlik sheets list Ct, Cp vs v_inf at one RPM. Definitions on the
    Info sheet use n in rev/s despite writing 'rpm' in the formula:
        T = Ct * ρ * n² * D⁴
        P = Cp * ρ * n³ * D⁵
    """
    xl = pd.ExcelFile(path)
    rho = 1.221
    d_in = None
    info_name = xl.sheet_names[0]
    info = pd.read_excel(path, sheet_name=info_name, header=None)
    for _, row in info.iterrows():
        key = str(row.iloc[0]).strip().lower() if pd.notna(row.iloc[0]) else ""
        val = row.iloc[2] if len(row) > 2 else None
        if "air density" in key and pd.notna(val):
            rho = float(val)
        if "diameter" in key and pd.notna(val):
            d_in = float(val)
    if d_in is None:
        raise ValueError(f"No diameter in {path}")
    d_m = d_in * IN_TO_M

    records = []
    skip = {info_name.lower(), "static cond.", "static cond"}
    for sheet in xl.sheet_names:
        if sheet.strip().lower() in skip:
            continue
        df = pd.read_excel(path, sheet_name=sheet)
        cols = {str(c).strip().lower(): c for c in df.columns}
        if "v_inf" not in cols or "rpm" not in cols:
            continue
        ct_col = cols.get("ct")
        cp_col = cols.get("cp")
        if ct_col is None or cp_col is None:
            continue
        vcol, rcol = cols["v_inf"], cols["rpm"]
        jcol = cols.get("advance ratio")
        ecol = next((c for k, c in cols.items() if "efficien" in k), None)
        for _, row in df.iterrows():
            try:
                v = float(row[vcol])
                rpm = float(row[rcol])
                ct = float(row[ct_col])
                cp = float(row[cp_col])
            except (TypeError, ValueError):
                continue
            if not np.isfinite(rpm) or rpm <= 0:
                continue
            n = rpm / 60.0
            thrust = ct * rho * n ** 2 * d_m ** 4
            power = cp * rho * n ** 3 * d_m ** 5
            omega = 2.0 * np.pi * n
            torque = power / omega if omega > 0 else 0.0
            j = float(row[jcol]) if jcol is not None and pd.notna(row[jcol]) else (
                v / (n * d_m) if n * d_m > 0 else 0.0)
            if ecol is not None and pd.notna(row[ecol]):
                eta = float(row[ecol])
            else:
                eta = (ct * j / cp) if abs(cp) > 1e-12 else 0.0
            records.append({
                "rpm": rpm,
                "v_ms": v,
                "j": j,
                "eta": eta,
                "ct": ct,
                "cp": cp,
                "power_w": power,
                "torque_nm": torque,
                "thrust_n": thrust,
            })
    out = pd.DataFrame.from_records(records)
    if out.empty:
        raise ValueError(f"No performance rows in {path}")
    return out.sort_values(["rpm", "v_ms"]).reset_index(drop=True)


def build_index(data_dir: Path = DATA_DIR, rescan: bool = False) -> pd.DataFrame:
    csv = data_dir / "catalog.csv"
    if csv.exists() and not rescan:
        return pd.read_csv(csv)
    rows = []
    map_dir = data_dir / "maps"
    ds_dir = data_dir / "datasheets"
    for spec in CATALOG:
        vendor = spec["vendor"]
        name = catalog_name(vendor)
        xlsx = map_dir / f"{name}.xlsx"
        if not xlsx.exists():
            continue
        dia, pitch, style = _geometry(vendor)
        pdf = ds_dir / f"{name}.pdf"
        mass = parse_datasheet_mass_kg(pdf) if pdf.exists() else None
        if mass is None:
            g = DEALER_MASS_G.get(vendor)
            mass = None if g is None else g / 1000.0
        rows.append({
            "name": name,
            "vendor_name": vendor,
            "file": str(xlsx),
            "datasheet": str(pdf) if pdf.exists() else "",
            "diameter_in": dia,
            "pitch_in": pitch,
            "style": style,
            "manufacturer": "mejzlik",
            "mass_kg": mass,
        })
    return pd.DataFrame(rows)


def load_map(name: str, data_dir: Path = DATA_DIR) -> tuple[pd.Series, pd.DataFrame]:
    idx = build_index(data_dir)
    if idx.empty:
        raise KeyError("Mejzlik index empty — run download_database() first")
    key = str(name).strip().lower()
    hit = idx[idx["name"].str.lower() == key]
    if hit.empty:
        hit = idx[idx["vendor_name"].str.lower() == key]
    if hit.empty:
        raise KeyError(f"Prop {name!r} not in Mejzlik 2B electric catalog")
    row = hit.iloc[0]
    return row, parse_performance_xlsx(Path(row["file"]))
