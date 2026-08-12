#!/usr/bin/env python
"""Pair 1 surfaces: the PRISTINE matched crystal (no bombardment, no relax).

The perfect-crystal lower-bound case. "No pre-relax, no bombardment" through
the cascade stage IS the as-built matched half — the commensurate crystal
slab `build_matched_halves.py` cut, untouched. So there is no GPU cascade to
run: this just reads each pre-built half and writes it in the activated-
surface format the press/pull chain consumes (substrate atoms, tagged
SiO2 -> wafer A, LiNbO3 -> wafer B).

Env: T12_BUILD_DIR (holds sio2_half.pkl / linbo3_half.pkl), VALWORK (output).
"""

import os
import pickle

from ase.io import write as ase_write

from sabsim.structure.wafer_tags import WAFER_A_TAG, WAFER_B_TAG

_WAFER_TAG = {"sio2": WAFER_A_TAG, "linbo3": WAFER_B_TAG}


def main() -> None:
    build_directory = os.environ["T12_BUILD_DIR"]
    work_directory = os.environ["VALWORK"]
    os.makedirs(work_directory, exist_ok=True)

    for name in ("sio2", "linbo3"):
        with open(os.path.join(build_directory, f"{name}_half.pkl"),
                  "rb") as handle:
            half = pickle.load(handle)
        atoms = half.atoms.copy()
        atoms.set_tags([_WAFER_TAG[name]] * len(atoms))
        out = os.path.join(work_directory, f"{name}_activated.extxyz")
        ase_write(out, atoms, format="extxyz", parallel=False)
        z = atoms.get_positions()[:, 2]
        print(f"{name}: {len(atoms)} pristine atoms | z {z.min():.1f}.."
              f"{z.max():.1f} -> {out}")
    print("PAIR-1 PRISTINE SURFACES READY")


if __name__ == "__main__":
    main()
