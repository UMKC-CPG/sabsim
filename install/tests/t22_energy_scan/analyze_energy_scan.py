"""Recover the Tier-1 energy -> damage-reach curve from a scan.

Two instruments, and which one answers the question depends on the dose.

REACH (primary). The deepest lattice site the cascade EMPTIED, printed
by the scan itself on its `SCANRESULT` lines and simply collected here.
It is a per-site measure, so a single impact is enough to place it, and
it is what brackets the operating energy.

DISORDER PROFILE (secondary). The fraction of atoms per depth bin whose
coordination departs from the fourfold diamond value. This is the skin
measure -- what the §3.5 gate keys on -- and at one impact per point it
reads flat, because one ion disorders a track rather than a layer.

The profile is referenced to the run's NULL CONTROL: the zero-impact
point that went through the identical path. Referencing it to the as-cut
data file instead, which the first version did, compares an unrelaxed
surface against relaxed ones and measures RELAXATION -- which is how the
bombarded slabs came out reading LESS disordered (0.26-0.48) than their
own "pristine" background (0.52).
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
# A bin's disorder fraction is a proportion measured on the handful of
# atoms that bin holds, so it carries real sampling noise: for a fraction
# near 0.3 over ~15 atoms the standard error is ~0.12. A FIXED margin of
# 0.10, which this used, therefore sat BELOW one sigma and duly reported
# 30-39 A "amorphized skins" at every energy including 20 eV, where the
# ion cannot physically have reached. The margin is now the combined
# standard error of the two proportions being differenced, times this
# many sigma -- so a bin has to beat its own counting noise before it is
# called disordered, and thin statistics produce silence instead of a
# number.
SIGNIFICANCE_SIGMA = 3.0
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
    centres, fractions, populations = [], [], []
    for index in range(len(edges) - 1):
        selected = which == index
        population = int(np.count_nonzero(selected))
        if population < 10:
            continue
        centres.append(0.5 * (edges[index] + edges[index + 1]))
        fractions.append(float(np.mean(
            counts[selected] != DIAMOND_COORDINATION)))
        populations.append(population)
    return (np.array(centres), np.array(fractions),
            np.array(populations))


def significance_margin(fraction, population, base_fraction,
                        base_population):
    """How far a bin must exceed background before the excess is real.

    Both numbers are proportions estimated from a finite sample, so each
    carries a standard error of sqrt(p(1-p)/n); the error on their
    DIFFERENCE is those two added in quadrature. Requiring the excess to
    clear several of those keeps thin bins — the deep ones, where the
    impact cylinder holds barely a dozen atoms — from being read as
    damage on the strength of one or two miscounted neighbours.
    """
    variance = (fraction * (1.0 - fraction) / max(population, 1)
                + base_fraction * (1.0 - base_fraction)
                / max(base_population, 1))
    return SIGNIFICANCE_SIGMA * float(np.sqrt(variance))


SCAN_LOGS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))),
    "jobs", "bulk_si", "scan_logs")


def collect_reach(log_directory):
    """The `SCANRESULT` lines the scan printed, newest job first.

    Each array task prints exactly one, so the curve is assembled by
    reading them rather than by re-deriving anything. Only the most
    recent job's lines are kept: an older, superseded scan's logs sit in
    the same directory and silently interleaving two runs would blend
    two different models or two different harness versions into one
    curve.
    """
    lines = []
    for log in glob.glob(os.path.join(log_directory, "escan-*.out")):
        job = os.path.basename(log).split("-")[1].split("_")[0]
        for line in open(log, encoding="utf-8"):
            if line.startswith("SCANRESULT"):
                fields = dict(
                    pair.split("=", 1) for pair in line.split()[1:])
                lines.append((job, fields))
    if not lines:
        return None, []
    newest = max(job for job, _ in lines)
    kept = [fields for job, fields in lines if job == newest]
    kept.sort(key=lambda f: float(f["energy_eV"]))
    return newest, kept


job, results = collect_reach(SCAN_LOGS)
if results:
    print(f"REACH by vacated lattice site -- job {job}\n")
    print(f"{'energy':>7} {'impacts':>8} {'vacated':>8} {'reach_A':>9} "
          f"{'sputtered':>10} {'above_null':>11}")
    floor = next((int(f["vacated_sites"]) for f in results
                  if f.get("null") == "1"), None)
    for fields in results:
        energy = float(fields["energy_eV"])
        vacated = int(fields["vacated_sites"])
        above = "--" if floor is None else str(vacated - floor)
        label = "null" if fields.get("null") == "1" else f"{energy:.0f}"
        print(f"{label:>7} {fields['impacts']:>8} {vacated:8d} "
              f"{float(fields['reach_depth']):9.2f} "
              f"{fields['sputtered']:>10} {above:>11}")
    if floor is None:
        print("\n  NOTE: no null control in this job -- the vacated "
              "counts have no measured floor.")
    print()
else:
    print(f"No SCANRESULT lines under {SCAN_LOGS}; "
          f"showing the disorder profile only.\n")

# The zero-impact null is the right background for REACH but the WRONG
# one for coordination. Zero impacts means the impact loop never runs,
# and the relaxation lives INSIDE that loop, so the null issues no `run`
# command at all: it is a minimized, effectively 0 K structure, while
# every bombarded point ran ~1 ps of finite-temperature MD. Differencing
# the two measures TEMPERATURE — thermal displacement pushes neighbours
# across the 3.0 A coordination cutoff — which is why the fixed-margin
# version reported a 30-39 A "skin" at 20 eV, where the ion cannot have
# reached. A depth is therefore not claimed here; the column is printed
# so the noise stays visible, not so it can be quoted.
profile_is_thermally_matched = any(
    f.get("null") == "1" and int(f["impacts"]) > 0 for f in results)
print("DISORDER PROFILE (skin measure)")
if not profile_is_thermally_matched:
    print("  NOT A RESULT: the null ran 0 impacts, so it ran no MD and\n"
          "  sits near 0 K while every point below ran ~1 ps of warm MD.\n"
          "  The differences below are dominated by temperature. A skin\n"
          "  depth needs BOTH dose and a thermally matched null.")
print()
print(f"{'energy':>7} {'atoms':>6} {'surface_disorder':>17} "
      f"{'bin_atoms':>9} {'amorph_depth_A':>15} {'note':>26}")

# The background is the NULL CONTROL -- the zero-impact point that took
# the identical path, pre-relax included. A free surface is
# undercoordinated with no cascade at all, and the pre-relax settles it
# further; neither is damage, and both must be subtracted by comparing
# like with like.
null_dump = os.path.join(SCRATCH, "scan_null", "activated_a.dump")
if not os.path.isfile(null_dump):
    raise SystemExit(
        f"no null control at {null_dump} -- the scan must include its "
        f"zero-impact task (array index 12) for the profile to have a "
        f"background it can honestly be read against")
pristine_positions, pristine_box = read_dump(null_dump)
pristine_surface = float(pristine_positions[:, 2].max())
# Background over the SAME cylinder each point uses. The null control
# has no `create_atoms` line to read a centre from -- it never fired a
# projectile -- so the centre is borrowed from an energy point. The
# impact sites are seed-derived and every point shares the one seed, so
# they are all the same site and any point serves.
reference_centre = impact_site(
    sorted(glob.glob(os.path.join(SCRATCH, "scan_e[0-9]*")))[0])
base_centres, base_fractions, base_populations = disorder_profile(
    pristine_positions, pristine_box, pristine_surface, reference_centre)
background = {round(c, 1): (f, n) for c, f, n
              in zip(base_centres, base_fractions, base_populations)}
print(f"{'null':>7} {len(pristine_positions):6d} "
      f"{base_fractions[0]:17.3f} "
      f"{int(np.median(base_populations)):9d} {'--':>15} "
      f"{'(background, 0 impacts)':>26}")

energy_points = [p for p in glob.glob(os.path.join(SCRATCH, "scan_e*"))
                 if os.path.basename(p).split("_e")[1].isdigit()]
for point_dir in sorted(
        energy_points,
        key=lambda p: int(os.path.basename(p).split("_e")[1])):
    energy = int(os.path.basename(point_dir).split("_e")[1])
    dump_file = os.path.join(point_dir, "activated_a.dump")
    if not os.path.isfile(dump_file):
        continue
    positions, box = read_dump(dump_file)
    centres, fractions, populations = disorder_profile(
        positions, box, pristine_surface, impact_site(point_dir))

    deepest = 0.0
    for centre, fraction, population in zip(
            centres, fractions, populations):
        base_fraction, base_population = background.get(
            round(centre, 1), (0.0, 1))
        margin = significance_margin(
            fraction, population, base_fraction, base_population)
        if fraction - base_fraction > margin:
            deepest = centre + 0.5 * BIN_WIDTH
    note = "" if deepest > 0 else "not resolved at this dose"
    print(f"{energy:7d} {len(positions):6d} {fractions[0]:17.3f} "
          f"{int(np.median(populations)):9d} "
          f"{deepest:15.2f} {note:>26}")
