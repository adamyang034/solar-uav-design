Solar UAV optimizer guide — Overleaf pack
========================================

Upload this whole folder to Overleaf (New Project → Upload Project),
or zip main.tex + figures/ + this README and drop the zip on Overleaf.

Compiler: pdfLaTeX
Main file: main.tex
Two passes (table of contents + list of figures).

figures/ were generated from the live nearest-miss on 17 August 2026:

  three_view.png        CAD mesh, four views
  geometry_top.png      planform
  geometry_side.png     independent H/V tails
  mass_breakdown.png    kg lumps
  airfoil_polars.png    NeuralFoil @ Re 150k
  drag_budget.png       night drag shares
  power_vs_speed.png    polar + DV(V) and the 1.3 Vs floor
  solstice_day.png      El Mirage irradiance / sun / cell T
  battery_ocv.png       6S OCV vs SOC
  mission_power.png     array vs night/day bus
  mission_soc.png       24 h march
  tradespace.png        812 DE candidates

To refresh the PNGs from the Python model:

  .venv/bin/python scripts/export_overleaf_figures.py
