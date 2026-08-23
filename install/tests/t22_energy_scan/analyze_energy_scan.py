"""Recover the Tier-1 energy -> amorphization-depth curve.

The scan's cascades all ran; the jobs died afterwards in reporting, on a
stale API assumption (`activate_one_half` no longer returns a gate
verdict -- the re-arch moved gating into the bond flow). The structures
survive, so the curve is recovered here instead of by re-running.

Depth is measured STATISTICALLY, not by tracking individual atoms. The
written structure is renumbered relative to the input data file (final
id N carries input id N+1's site), so per-atom pairing is not available
-- and it is not needed: amorphization is a property of the local
NETWORK, which is what the §3.5 gate keys on too. For each depth bin
below the surface this reports the fraction of silicon atoms whose
coordination departs from the fourfold diamond value, and the
amorphized depth is the deepest bin still disordered above the
pristine slab's own background.
"""

import glob
import os

import numpy as np

SCRATCH = ("/home/rulisp/data/scratch/sabsim/CPG/cpg-repo/sabsim"
           "/jobs/bulk_si")
SILICON_TYPE = 2
# DPA-3.1's silicon: a = 5.5147 A puts the first neighbour shell at
# a*sqrt(3)/4 = 2.388 A and the second at a/sqrt(2) = 3.900 A, so 3.0 A
# separates them cleanly.
NEIGHBOUR_CUTOFF = 3.0
DIAMOND_COORDINATION = 4
BIN_WIDTH = 3.0                  # angstrom depth bins
DISORDER_MARGIN = 0.10           # above the pristine background
# One impact disorders a COLUMN, not the whole face: averaging over the
# full 745 A^2 cell dilutes it below detection. The profile is therefore
# taken inside a cylinder centred on the impact site that activate_a.in
# records, and the pristine background is taken over the same cylinder.
IMPACT_RADIUS = 10.0             # angstrom


def read_dump(path):
    """Silicon positions and the box, from a custom LAMMPS dump."""
    lines = open(path, encoding="utf-8").read().splitlines()
    box = np.zeros(3)
    positions = []
    for index, line in enumerate(lines):
        if line.startswith("ITEM: BOX BOUNDS"):
            for axis in range(3):
                low, high = map(float, lines[index + 1 + axis].split())
                box[axis] = high - low
        if line.startswith("ITEM: ATOMS"):
            columns = line[len("ITEM: ATOMS"):].split()
            type_col = columns.index("type")
            x_col, y_col, z_col = (
                columns.index(c) for c in ("x", "y", "z"))
            for row in lines[index + 1:]:
                if not row.strip() or row.startswith("ITEM:"):
                    continue
                fields = row.split()
                if int(fields[type_col]) != SILICON_TYPE:
                    continue
                positions.append([float(fields[x_col]),
                                  float(fields[y_col]),
                                  float(fields[z_col])])
            break
    return np.array(positions), box


def read_data(path):
    """Silicon positions and the box, from a LAMMPS data file."""
    box = np.zeros(3)
    positions = []
    section = None
    for line in open(path, encoding="utf-8"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("Masses"):
            section = "masses"
            continue
        if stripped.startswith("Atoms"):
            section = "atoms"
            continue
        for axis, tag in enumerate(("xlo xhi", "ylo yhi", "zlo zhi")):
            if stripped.endswith(tag):
                low, high = stripped.split()[:2]
                box[axis] = float(high) - float(low)
        if section == "atoms":
            fields = stripped.split()
            if len(fields) >= 5 and int(fields[1]) == SILICON_TYPE:
                positions.append([float(f) for f in fields[2:5]])
    return np.array(positions), box


def coordination(positions, box):
    """Neighbour count within the first shell, minimum image in x and y.

    A cell list keeps the search linear; z is open (``p p f``) so it is
    not folded.
    """
    counts = np.zeros(len(positions), dtype=int)
    cell_index = np.floor(positions / NEIGHBOUR_CUTOFF).astype(int)
    cells = {}
    for atom, key in enumerate(map(tuple, cell_index)):
        cells.setdefault(key, []).append(atom)
    cells_x = int(np.ceil(box[0] / NEIGHBOUR_CUTOFF))
    cells_y = int(np.ceil(box[1] / NEIGHBOUR_CUTOFF))
    cutoff_squared = NEIGHBOUR_CUTOFF ** 2
    for atom, key in enumerate(map(tuple, cell_index)):
        for offset_x in (-1, 0, 1):
            for offset_y in (-1, 0, 1):
                for offset_z in (-1, 0, 1):
                    neighbour_key = ((key[0] + offset_x) % cells_x,
                                     (key[1] + offset_y) % cells_y,
                                     key[2] + offset_z)
                    for other in cells.get(neighbour_key, ()):
                        if other == atom:
                            continue
                        separation = positions[other] - positions[atom]
                        for axis in (0, 1):
                            separation[axis] -= box[axis] * round(
                                separation[axis] / box[axis])
                        if np.dot(separation, separation) < cutoff_squared:
                            counts[atom] += 1
    return counts


def impact_site(point_dir):
    """The (x, y) the projectile was created at, from activate_a.in."""
    script = os.path.join(point_dir, "activate_a.in")
    for line in open(script, encoding="utf-8"):
        if line.startswith("create_atoms"):
            fields = line.split()
            return float(fields[4]), float(fields[5])
    raise ValueError(f"no create_atoms line in {script}")


def disorder_profile(positions, box, surface_z, centre=None):
    """Fraction of non-fourfold atoms per depth bin below the surface.

    Coordination is computed on the FULL cell (so atoms near the cylinder
    edge keep their real neighbours); only the BINNING is restricted to
    the cylinder, when one is given.
    """
    counts = coordination(positions.copy(), box)
    depth = surface_z - positions[:, 2]
    if centre is not None:
        lateral = positions[:, :2] - np.array(centre)
        for axis in (0, 1):
            lateral[:, axis] -= box[axis] * np.round(
                lateral[:, axis] / box[axis])
        inside = np.linalg.norm(lateral, axis=1) < IMPACT_RADIUS
        counts = counts[inside]
        depth = depth[inside]
    edges = np.arange(0.0, float(depth.max()) + BIN_WIDTH, BIN_WIDTH)
    which = np.digitize(depth, edges) - 1
    centres, fractions = [], []
    for index in range(len(edges) - 1):
        selected = which == index
        if np.count_nonzero(selected) < 10:
            continue
        centres.append(0.5 * (edges[index] + edges[index + 1]))
        fractions.append(float(np.mean(
            counts[selected] != DIAMOND_COORDINATION)))
    return np.array(centres), np.array(fractions)


print(f"{'energy':>7} {'atoms':>6} {'surface_disorder':>17} "
      f"{'amorph_depth_A':>15} {'note':>28}")

# The pristine slab is the background: a free surface is undercoordinated
# even with no cascade, and that must not be counted as damage.
pristine_positions, pristine_box = read_data(
    os.path.join(SCRATCH, "scan_slab_scan_e020.data"))
pristine_surface = float(pristine_positions[:, 2].max())
# Background over the SAME cylinder each point uses (the sites are
# seed-derived and identical across points, so one background serves).
reference_centre = impact_site(os.path.join(SCRATCH, "scan_e020"))
base_centres, base_fractions = disorder_profile(
    pristine_positions, pristine_box, pristine_surface, reference_centre)
background = {round(c, 1): f for c, f in zip(base_centres, base_fractions)}
print(f"{'pristine':>7} {len(pristine_positions):6d} "
      f"{base_fractions[0]:17.3f} {'--':>15} "
      f"{'(background, free surface)':>28}")

for point_dir in sorted(glob.glob(os.path.join(SCRATCH, "scan_e*")),
                        key=lambda p: int(os.path.basename(p).split("_e")[1])):
    energy = int(os.path.basename(point_dir).split("_e")[1])
    dump_file = os.path.join(point_dir, "activated_a.dump")
    if not os.path.isfile(dump_file):
        continue
    positions, box = read_dump(dump_file)
    centres, fractions = disorder_profile(
        positions, box, pristine_surface, impact_site(point_dir))

    deepest = 0.0
    for centre, fraction in zip(centres, fractions):
        base = background.get(round(centre, 1), 0.0)
        if fraction - base > DISORDER_MARGIN:
            deepest = centre + 0.5 * BIN_WIDTH
    note = "" if deepest > 0 else "no disorder above background"
    print(f"{energy:7d} {len(positions):6d} {fractions[0]:17.3f} "
          f"{deepest:15.2f} {note:>28}")
