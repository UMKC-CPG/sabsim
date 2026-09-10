"""T-43 — which recipe settings actually MELT alpha quartz?

LEDGER T-42 ended with a melt-quench that never melted: 72 atoms of
quartz held at 3500 K at the crystal's own volume only vibrated (every
atom within 1.6 A of its lattice site for the whole run), so the §3.5
self-check truthfully found nothing disordered. This probe runs ONE
melt-quench variant per Slurm array task through the real script
builder (`melt_quench_script`, now with the melt-check dump), then
reports three things a person can choose a recipe from:

  1. the diffusion ratio `verify_melt` judges (>= 2 means liquid);
  2. how far the atoms ended from their starting lattice sites;
  3. the §3.5 separation of the FINAL quenched frame from the warm
     catalogue that job 16873844 already described (same descriptor
     settings), per species, as a multiple of the warm scatter.

Usage (inside the array job): python t43_melt_probe.py <variant index>
"""

from __future__ import annotations

import dataclasses
import glob
import os
import re
import sys
from pathlib import Path

import numpy as np

from sabsim.bootstrap.collection1 import (
    _generator_model,
    _read_dump_frames,
    derive_phase_lattices,
    melt_check_dump_path,
    melt_diffusion_ratio,
    melt_quench_script,
)
from sabsim.bootstrap.recipe import Quantity, load_recipe
from sabsim.driver.cascade_subprocess import run_activate_subprocess
from sabsim.driver.commands import to_metal
from sabsim.driver.descriptors import describe_atoms
from sabsim.structure.slab_builder import (
    bulk_atoms,
    rescale_crystal_to_cell,
    write_bulk_data,
)

REPO = Path(os.environ["SABSIM_T43_REPO"])
RECIPE = REPO / "share" / "templates" / "recipes" / "sio2.toml"
# The catalogue job 16873844 described (cold bulk, warm runs, surface),
# reused so every variant is judged against the same ruler.
CATALOGUE = (Path(os.environ["SABSIM_SCRATCH"]) / "CPG/cpg-repo/sabsim/jobs"
             / "si_sio2/prep_surf2_sio2/bootstrap/sio2-quartz-lean-v0"
             / "collection1/descriptors")

# (label, melt K, hold ps, cells per axis, linear cell scale)
VARIANTS = [
    ("baseline_3500K_5ps_2cells", 3500.0, 5.0, 2, 1.0),
    ("hot_5000K_5ps_2cells", 5000.0, 5.0, 2, 1.0),
    ("hot_long_5000K_10ps_2cells", 5000.0, 10.0, 2, 1.0),
    ("hotter_6000K_5ps_2cells", 6000.0, 5.0, 2, 1.0),
    ("big_5000K_5ps_3cells", 5000.0, 5.0, 3, 1.0),
    # Quartz is 2.65 g/cc, silica glass 2.2: a liquid held at the
    # crystal's volume is 20 % too dense. Linear scale (2.65/2.2)^(1/3).
    ("glass_density_3500K_5ps_2cells", 3500.0, 5.0, 2, 1.064),
]


def read_descriptor_dump(path):
    """(types, vectors) of one describe_*.dump, rows sorted by id."""
    lines = Path(path).read_text().split("\n")
    start = next(k for k, line in enumerate(lines)
                 if line.startswith("ITEM: ATOMS"))
    rows = np.array([[float(v) for v in line.split()]
                     for line in lines[start + 1:] if line.strip()])
    return rows[:, 1].astype(int), rows[:, 5:]


def nearest(queries, catalogue):
    """Distance from each query row to its nearest catalogue row."""
    squared = ((queries[:, None, :] - catalogue[None, :, :]) ** 2).sum(-1)
    return np.sqrt(np.clip(squared.min(axis=1), 0.0, None))


def catalogue_by_species():
    """cold, warm, and full catalogue rows per LAMMPS type (1 Si, 2 O)."""
    families = {}
    for path in sorted(glob.glob(str(CATALOGUE / "describe_*.dump"))):
        family = re.match(r"describe_(.*)_\d+\.dump",
                          os.path.basename(path)).group(1)
        families.setdefault(family, []).append(read_descriptor_dump(path))
    out = {}
    for lammps_type, symbol in ((1, "Si"), (2, "O")):
        def rows(names):
            return np.vstack([v[t == lammps_type]
                              for name in names for t, v in families[name]])
        cold = rows(["bulk"])
        warm = rows(["warm_nvt", "warm_npt"])
        full = np.vstack([cold, warm, rows(["surface"])])
        scatter = float(np.percentile(nearest(warm, cold), 90))
        out[symbol] = (full, scatter)
    return out


def main(index: int) -> None:
    label, melt_kelvin, hold_ps, cells, scale = VARIANTS[index]
    work = Path(os.environ["SABSIM_T43_WORK"]) / label
    work.mkdir(parents=True, exist_ok=True)
    print(f"=== T-43 variant {index}: {label} ===", flush=True)

    recipe = load_recipe(RECIPE)
    lattices = derive_phase_lattices(recipe, work)
    phase_name = recipe.phases[0].name
    crystal, _ = lattices[phase_name]
    if scale != 1.0:
        crystal = rescale_crystal_to_cell(
            crystal, np.array(crystal.lattice.matrix) * scale)
    base = recipe.starting_collection.melt_quench[0]
    spec = dataclasses.replace(
        base, cells_per_axis=cells,
        melt_temperature=Quantity(melt_kelvin, "K"),
        melt_duration=Quantity(hold_ps, "ps"))

    data_file = str(work / "start.data")
    type_map = write_bulk_data(crystal, cells, data_file)
    dump_file = str(work / "frames.dump")
    timestep_ps = to_metal(recipe.generator.md_timestep, "time")
    script = melt_quench_script(
        spec, data_file, _generator_model(recipe, type_map), timestep_ps,
        dump_file, spec.seed)
    run_activate_subprocess(script, str(work), f"{dump_file}.final.data",
                            script_name="melt_quench.in",
                            log_name="log.melt_quench")

    ratio = melt_diffusion_ratio(melt_check_dump_path(dump_file))
    frames = _read_dump_frames(dump_file, type_map)
    final = frames[-1]
    start = bulk_atoms(crystal, cells)
    delta = final.get_positions() - start.get_positions()
    fractional = np.linalg.solve(np.array(start.cell).T, delta.T).T
    fractional -= np.round(fractional)
    site_shift = np.linalg.norm(fractional @ np.array(start.cell), axis=1)

    settings = recipe.descriptor_settings
    vectors = describe_atoms(final, settings, str(work / "describe"),
                             "final")
    symbols = np.array(final.get_chemical_symbols())
    catalogue = catalogue_by_species()
    print(f"T43RESULT {label}: atoms {len(final)} melt_diffusion_ratio "
          f"{ratio:.2f} ({'LIQUID' if ratio >= 2.0 else 'CRYSTAL'})")
    print(f"T43RESULT {label}: final-frame shift from lattice site "
          f"median {np.median(site_shift):.2f} A, p90 "
          f"{np.percentile(site_shift, 90):.2f} A, fraction > 1.6 A "
          f"{np.mean(site_shift > 1.6):.2f}")
    for symbol in ("Si", "O"):
        full, scatter = catalogue[symbol]
        distance = nearest(vectors[symbols == symbol], full)
        multiples = distance / scatter
        print(f"T43RESULT {label}: {symbol} final-frame distance to "
              f"catalogue / warm scatter ({scatter:.2f}): median "
              f"{np.median(multiples):.2f}x, fraction > 3x "
              f"{np.mean(multiples > 3.0):.2f}, > 2x "
              f"{np.mean(multiples > 2.0):.2f}, > 1x "
              f"{np.mean(multiples > 1.0):.2f}")


if __name__ == "__main__":
    main(int(sys.argv[1]))
