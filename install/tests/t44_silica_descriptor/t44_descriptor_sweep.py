"""T-44 — which descriptor settings tell silica GLASS from warm quartz?

LEDGER T-43 found that a genuine silica liquid (6000 K, every atom
several angstrom from its site) quenches to a glass the silicon-tuned
descriptor (cutoff 4.2 A, weights Si 1.0 / O 0.5) still reads as
mostly crystalline: at three thermal scatters only 29 % of Si and
4 % of O were flagged. The tetrahedron survives in the glass; what
differs is the medium-range order, at 5-6 A. This probe re-describes
ONE fixed set of frames under several settings and replays the §3.5
self-check for each, on a CPU node (sna/atom needs no GPU):

  frames:   the T-42 catalogue's cold bulk, warm NVT/NPT frames and
            clean surface (job 16873844, alpha quartz) and the T-43
            glasses (the final quench frames of the variants that
            melted), all re-described from their atoms;
  settings: cutoff x weights (see SETTINGS below).

For each setting it prints the warm thermal scatter per species and,
at multiples 1, 2 and 3, the warm false-alarm and the glass
disordered fractions — the two numbers the self-check gates on.

Usage (inside the job): python t44_descriptor_sweep.py
"""

from __future__ import annotations

import glob
import os
from pathlib import Path

import numpy as np
from ase.io import read as ase_read

from sabsim.bootstrap.collection1 import _read_dump_frames
from sabsim.driver.descriptors import DescriptorSettings, describe_atoms

SCRATCH = Path(os.environ["SABSIM_SCRATCH"])
CATALOGUE_RUN = (SCRATCH / "CPG/cpg-repo/sabsim/jobs/si_sio2/prep_surf2_sio2"
                 / "bootstrap/sio2-quartz-lean-v0/collection1")
T43_RUN = SCRATCH / "tests/t43_silica_melt/17235970"
GLASS_VARIANTS = ("hot_long_5000K_10ps_2cells", "hotter_6000K_5ps_2cells",
                  "big_5000K_5ps_3cells")
WORK = Path(os.environ["SABSIM_T44_WORK"])
MASSES = {"Si": 28.085, "O": 15.999}

# (label, cutoff A, weights)
SETTINGS = [
    ("cut4.2_Si1.0_O0.5", 4.2, {"Si": 1.0, "O": 0.5}),     # T-42 control
    ("cut5.0_Si1.0_O0.5", 5.0, {"Si": 1.0, "O": 0.5}),
    ("cut6.0_Si1.0_O0.5", 6.0, {"Si": 1.0, "O": 0.5}),
    ("cut4.2_Si0.5_O1.0", 4.2, {"Si": 0.5, "O": 1.0}),
    ("cut6.0_Si0.5_O1.0", 6.0, {"Si": 0.5, "O": 1.0}),
    ("cut6.0_Si1.0_O0.8", 6.0, {"Si": 1.0, "O": 0.8}),
]


def type_map_of(data_path) -> dict:
    """symbol -> LAMMPS type, read from a data file's Masses block.

    The MD data files (write_bulk_data) order species alphabetically
    (O 1, Si 2) while the describe data files follow the recipe's
    weight order (Si 1, O 2) — LEDGER T-42's lesson — so each file is
    asked, never assumed.
    """
    lines = Path(data_path).read_text().split("\n")
    start = next(k for k, line in enumerate(lines)
                 if line.startswith("Masses"))
    type_map = {}
    for line in lines[start + 1:]:
        parts = line.split()
        if not parts:
            if type_map:
                break
            continue
        if not parts[0].isdigit():
            break
        mass = float(parts[1])
        symbol = min(MASSES, key=lambda s: abs(MASSES[s] - mass))
        type_map[symbol] = int(parts[0])
    return type_map


def data_frame(path):
    """One LAMMPS data file as Atoms with real symbols."""
    type_map = type_map_of(path)
    atoms = ase_read(str(path), format="lammps-data", atom_style="atomic")
    by_type = {number: symbol for symbol, number in type_map.items()}
    atoms.set_chemical_symbols(
        [by_type[int(t)] for t in atoms.get_atomic_numbers()]
        if "type" not in atoms.arrays else
        [by_type[int(t)] for t in atoms.arrays["type"]])
    atoms.set_pbc([True, True, True])
    return atoms


def collect_frames():
    """family -> list of Atoms, the fixed set every setting describes."""
    frames = {}
    frames["bulk"] = [data_frame(
        CATALOGUE_RUN / "lattice/silica-alpha-quartz/relaxed_bulk.data")]
    for family in ("warm_nvt", "warm_npt"):
        dumps = sorted(glob.glob(
            str(CATALOGUE_RUN / family / "*/frames.dump")))
        frames[family] = [
            f for dump in dumps for f in _read_dump_frames(
                dump, type_map_of(Path(dump).parent / "start.data"))]
    # The clean surface was described from its own data file in T-42.
    surface = sorted(glob.glob(
        str(CATALOGUE_RUN / "descriptors/describe_surface_*.data")))
    frames["surface"] = [data_frame(path) for path in surface]
    frames["glass"] = []
    for variant in GLASS_VARIANTS:
        dump = T43_RUN / variant / "frames.dump"
        # Only a FINISHED quench has its final data file; a mid-quench
        # frame is not a glass.
        if Path(f"{dump}.final.data").is_file():
            frames["glass"].append(_read_dump_frames(
                str(dump), type_map_of(dump.parent / "start.data"))[-1])
    return frames


def nearest(queries, catalogue):
    out = np.empty(len(queries))
    for start in range(0, len(queries), 256):
        chunk = queries[start:start + 256]
        squared = ((chunk[:, None, :] - catalogue[None, :, :]) ** 2).sum(-1)
        out[start:start + 256] = np.sqrt(np.clip(squared.min(1), 0, None))
    return out


def main() -> None:
    frames = collect_frames()
    for family, items in frames.items():
        print(f"frames: {family} {len(items)} "
              f"({sum(len(a) for a in items)} atoms)", flush=True)
    for label, cutoff, weights in SETTINGS:
        settings = DescriptorSettings(
            descriptor_cutoff=cutoff, expansion_order=6,
            species_weights=weights)
        work = WORK / label
        described = {}
        for family, items in frames.items():
            rows = {"Si": [], "O": []}
            for index, atoms in enumerate(items):
                vectors = describe_atoms(atoms, settings, str(work),
                                         f"{family}_{index}")
                for symbol, vector in zip(atoms.get_chemical_symbols(),
                                          vectors):
                    rows[symbol].append(vector)
            described[family] = {s: np.array(v) for s, v in rows.items()}
        for symbol in ("Si", "O"):
            cold = described["bulk"][symbol]
            warm = np.vstack([described["warm_nvt"][symbol],
                              described["warm_npt"][symbol]])
            catalogue = np.vstack([cold, warm, described["surface"][symbol]])
            glass = described["glass"][symbol]
            warm_distance = nearest(warm, cold)
            scatter = float(np.percentile(warm_distance, 90))
            glass_distance = nearest(glass, catalogue)
            norm = float(np.linalg.norm(cold, axis=1).mean())
            line = (f"T44RESULT {label} {symbol}: scatter {scatter:.2f} "
                    f"(|cold| {norm:.1f}); glass median "
                    f"{np.median(glass_distance) / scatter:.2f}x;")
            for multiple in (1.0, 2.0, 3.0):
                warm_flagged = np.mean(warm_distance > multiple * scatter)
                glass_flagged = np.mean(glass_distance > multiple * scatter)
                line += (f" @{multiple:g}x warm {warm_flagged:.2f} "
                         f"glass {glass_flagged:.2f};")
            print(line, flush=True)


if __name__ == "__main__":
    main()
