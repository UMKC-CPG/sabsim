"""The bispectrum descriptor engine — LAMMPS ``compute sna/atom`` adapter.

The §3.5 activation gate decides whether an atom is CRYSTALLINE by
asking whether its neighbourhood exists anywhere in the undamaged
material (DESIGN §3.5, revised 2026-08-29). To ask that, every atom's
neighbourhood must be turned into a set of numbers that does not change
when the neighbourhood is rotated, shifted, or two atoms of the same
species are swapped: the **bispectrum components** at a SHORT cutoff,
the first neighbour shell. The same numbers are computed for the
undamaged material (the bootstrap's environment library,
:mod:`sabsim.driver.environment_library`) and for the healed slab, and
the comparison is only meaningful if BOTH sides come from the SAME
engine with the SAME settings — which is why this module is the one
place the descriptor is computed (ARCHITECTURE §2.3).

The engine bound here is LAMMPS's own ``compute sna/atom`` (the ML-SNAP
package), which LEDGER T-35 showed compiled into the deepmd bundle's
LAMMPS: no new dependency, run out-of-process exactly like the cascade
(:mod:`sabsim.driver.cascade_subprocess`), the per-atom components read
back from a dump. The seam stays pluggable — a Python descriptor library
or Imago's bispectrum could be bound instead — but whichever engine is
bound records its name in every library it builds, and the gate refuses
a library from a different engine.

One trap, fallen into by T-35 and documented so nobody falls in twice:
SNAP's pair cutoff is ``rcutfac x (R_i + R_j)``, the SUM of two per-
species radii scaled by a factor, not a radius. The settings therefore
state the PHYSICAL first-shell cutoff as a length, and this adapter
derives LAMMPS's parameters from it so every species pair is cut at
exactly that length.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
from ase import Atoms

from sabsim.driver.cascade_subprocess import run_activate_subprocess

# The name the engine records in every library it builds, and the gate
# compares against before trusting one (ARCHITECTURE §2.3).
DESCRIPTOR_ENGINE_NAME = "lammps-sna/atom"

# SNAP's radial-function parameters that are NOT physics choices here:
# ``rfac0`` sets how the radial coordinate is mapped onto the hypersphere
# (LAMMPS's documented default) and ``rmin0`` is the inner radius of
# that mapping (zero: the whole shell counts). Neither changes what
# "the same neighbourhood" means, so neither is a recipe setting.
_RADIAL_MAPPING_FACTOR = 0.99363
_INNER_RADIUS = 0.0
# The overall SNAP cutoff factor. With every per-species radius set to
# HALF the physical cutoff, a factor of exactly one makes every pair
# cutoff equal the physical cutoff (see ``to_lammps_parameters``).
_CUTOFF_FACTOR = 1.0
# The neighbour list must reach at least as far as the SNAP cutoff or
# LAMMPS refuses ("Compute sna/atom cutoff is longer than pairwise
# cutoff", T-35); this margin keeps the list comfortably wider.
_NEIGHBOUR_MARGIN = 0.5


@dataclass(frozen=True)
class DescriptorSettings:
    """How the bispectrum is computed — the gate's RULER (DESIGN §4.8).

    ``first_shell_cutoff`` is the PHYSICAL radius, in angstrom, within
    which neighbours count: the first neighbour shell (2.6 Å for silicon,
    where the first shell sits at 2.35 Å and the second at 3.84 Å).
    ``expansion_order`` is SNAP's ``twojmax``, which sets how many
    components describe a neighbourhood (30 at order 6). ``species_
    weights`` lets species be told apart inside one descriptor: each
    neighbour's contribution is scaled by its species' weight, so two
    neighbourhoods that differ only in WHICH species sits where get
    different components.

    These settings live in the force-model recipe and are recorded in
    the library they built; the gate reads them from the library, never
    from a copy of its own, so both sides of the comparison agree.
    """

    first_shell_cutoff: float          # angstrom, a physical length
    expansion_order: int               # SNAP twojmax
    species_weights: dict              # element symbol -> weight


def to_lammps_parameters(
        settings: DescriptorSettings, species_order: list) -> tuple:
    """Derive ``compute sna/atom``'s parameters from the physical cutoff.

    Returns ``(rcutfac, rfac0, twojmax, radii, weights)`` with ``radii``
    and ``weights`` in ``species_order`` (LAMMPS type order). SNAP cuts
    each species PAIR at ``rcutfac x (R_i + R_j)``, so giving every
    species the radius ``first_shell_cutoff / 2`` with ``rcutfac = 1``
    makes every pair cutoff exactly the physical cutoff — the first
    shell in, the second out, for every species combination alike. A
    species with no weight in the settings is a loud error, not a
    silent one: a default weight would change what "the same
    neighbourhood" means without anyone having written it down.
    """
    radii = [settings.first_shell_cutoff / 2.0] * len(species_order)
    weights = []
    for symbol in species_order:
        if symbol not in settings.species_weights:
            raise ValueError(
                f"descriptor settings carry no species weight for "
                f"'{symbol}' (have {sorted(settings.species_weights)}); "
                f"every species the structure contains needs one")
        weights.append(float(settings.species_weights[symbol]))
    return (_CUTOFF_FACTOR, _RADIAL_MAPPING_FACTOR,
            int(settings.expansion_order), radii, weights)


def neighbour_cutoff(settings: DescriptorSettings) -> float:
    """The pair cutoff the descriptor script's neighbour list must use.

    At least the SNAP cutoff, plus a margin, or LAMMPS refuses to build
    the compute (the T-35 trap).
    """
    return settings.first_shell_cutoff + _NEIGHBOUR_MARGIN


def sna_compute_commands(
        settings: DescriptorSettings, species_order: list,
        dump_file: str) -> list:
    """The LAMMPS lines that compute and dump the bispectrum per atom.

    One ``compute sna/atom`` over every atom at the derived parameters,
    a per-atom dump of ``id type x y z`` followed by every component
    (``c_sna[*]``), sorted by atom id so the rows pair with the caller's
    atom order, and a zero-step run to trigger the dump. The components
    are written with ten significant figures: a thermal-scatter
    tolerance is a small number, and the default six figures would
    round a genuine difference away.
    """
    rcutfac, rfac0, twojmax, radii, weights = to_lammps_parameters(
        settings, species_order)
    radii_text = " ".join(f"{radius:g}" for radius in radii)
    weights_text = " ".join(f"{weight:g}" for weight in weights)
    return [
        f"compute sna all sna/atom {rcutfac:g} {rfac0:g} {twojmax} "
        f"{radii_text} {weights_text} rmin0 {_INNER_RADIUS:g}",
        f"dump descriptors all custom 1 {dump_file} id type x y z "
        f"c_sna[*]",
        "dump_modify descriptors sort id format float %.10g",
        "run 0",
    ]


def descriptor_script(
        data_file: str, settings: DescriptorSettings, species_order: list,
        dump_file: str) -> list:
    """The whole LAMMPS input that describes one structure.

    No real potential is needed — the descriptor depends on geometry
    alone — so ``pair_style zero`` supplies nothing but a neighbour list
    wide enough for the compute (:func:`neighbour_cutoff`). Every
    structure is written fully periodic: a bulk cell is periodic by
    nature, and a slab's data file carries enough vacuum that no atom
    sees its own image across it (:func:`describe_structure` pads the
    box to guarantee that).
    """
    return [
        "units metal",
        "atom_style atomic",
        "boundary p p p",
        f"read_data {data_file}",
        f"pair_style zero {neighbour_cutoff(settings):g}",
        "pair_coeff * *",
        *sna_compute_commands(settings, species_order, dump_file),
    ]


def read_dump_columns(dump_path: str, prefix: str = "c_sna") -> np.ndarray:
    """Read the per-atom columns named ``<prefix>[k]`` from a LAMMPS dump.

    Returns an ``(N, K)`` array with rows in ascending atom-id order and
    the columns in ascending component order, read from the ``ITEM:
    ATOMS`` header rather than assumed, so a reordered dump still parses.
    Only the LAST frame of the dump is read (the descriptor run writes
    exactly one).
    """
    with open(dump_path, encoding="utf-8") as dump_file:
        raw_lines = dump_file.read().splitlines()

    header = None
    rows: list = []
    reading = False
    for line in raw_lines:
        if line.startswith("ITEM: ATOMS"):
            header = line[len("ITEM: ATOMS"):].split()
            rows = []                          # a new frame starts
            reading = True
            continue
        if line.startswith("ITEM:"):
            reading = False
            continue
        if reading and line.strip():
            rows.append(line.split())

    if header is None:
        raise ValueError(f"no 'ITEM: ATOMS' section in dump {dump_path}")
    component_columns = [
        index for index, name in enumerate(header)
        if name.startswith(prefix + "[")]
    if not component_columns:
        raise ValueError(
            f"dump {dump_path} carries no '{prefix}[...]' columns")
    id_column = header.index("id")
    rows.sort(key=lambda fields: int(fields[id_column]))
    return np.array(
        [[float(fields[column]) for column in component_columns]
         for fields in rows], dtype=float)


def _type_map_for(symbols: list, settings: DescriptorSettings) -> dict:
    """A deterministic species -> LAMMPS type map for one structure.

    Species are numbered in the order the settings list their weights,
    restricted to the species present, so the same material always gets
    the same type ids whatever frame is being described.
    """
    present = set(symbols)
    ordered = [symbol for symbol in settings.species_weights
               if symbol in present]
    missing = present - set(ordered)
    if missing:
        raise ValueError(
            f"descriptor settings carry no species weight for "
            f"{sorted(missing)}; every species present needs one")
    return {symbol: index + 1 for index, symbol in enumerate(ordered)}


def describe_atoms(
        atoms: Atoms, settings: DescriptorSettings, work_directory: str,
        tag: str) -> np.ndarray:
    """Bispectrum components of every atom of an ASE structure.

    Writes the structure as a LAMMPS data file, runs the descriptor
    script under the bundle's ``lmp`` out-of-process, and reads the
    ``(N, K)`` component matrix back, rows in the structure's own atom
    order. ``tag`` names the files so several structures can share one
    working directory (``describe_<tag>.data``, ``.in``, ``.dump``).
    The structure is written exactly as given — a bulk cell periodic,
    a slab with its vacuum — under a fully periodic boundary.
    """
    from sabsim.structure.slab_builder import _write_atoms_as_lammps_data
    os.makedirs(work_directory, exist_ok=True)
    symbols = list(atoms.get_chemical_symbols())
    type_map = _type_map_for(symbols, settings)
    species_order = sorted(type_map, key=lambda symbol: type_map[symbol])
    data_file = os.path.join(work_directory, f"describe_{tag}.data")
    dump_file = os.path.join(work_directory, f"describe_{tag}.dump")
    periodic = atoms.copy()
    periodic.set_pbc((True, True, True))
    _write_atoms_as_lammps_data(periodic, type_map, data_file)
    run_activate_subprocess(
        descriptor_script(data_file, settings, species_order, dump_file),
        work_directory, dump_file,
        script_name=f"describe_{tag}.in",
        log_name=f"log.describe_{tag}")
    vectors = read_dump_columns(dump_file)
    if vectors.shape[0] != len(symbols):
        raise RuntimeError(
            f"the descriptor dump for '{tag}' holds {vectors.shape[0]} "
            f"atoms but the structure has {len(symbols)}")
    return vectors


def describe_structure(
        positions: np.ndarray, cell: np.ndarray, symbols: list,
        settings: DescriptorSettings, work_directory: str,
        tag: str) -> np.ndarray:
    """Bispectrum components of a SLAB given as bare arrays.

    The gate's entry point: the healed half comes back from its cascade
    session as positions and species under the slab's cell, whose z
    boundary was open (``p p f``) so atoms may sit anywhere along z.
    The descriptor script is fully periodic, so the slab is re-boxed
    along z — the in-plane cell kept, the z extent set to the atoms'
    span plus a vacuum wider than the cutoff on each side — before
    being described. Descriptors are translation-invariant, so the
    shift changes nothing physical; it only guarantees no atom sees its
    own image across the vacuum.
    """
    positions = np.asarray(positions, dtype=float)
    cell = np.asarray(cell, dtype=float)
    padding = 2.0 * neighbour_cutoff(settings)
    z_low = float(positions[:, 2].min()) - padding
    z_high = float(positions[:, 2].max()) + padding
    boxed = positions.copy()
    boxed[:, 2] -= z_low
    reboxed_cell = cell.copy()
    reboxed_cell[2] = np.array([0.0, 0.0, z_high - z_low])
    atoms = Atoms(symbols=list(symbols), positions=boxed,
                  cell=reboxed_cell, pbc=True)
    return describe_atoms(atoms, settings, work_directory, tag)


def descriptor_distance(a: np.ndarray, b: np.ndarray) -> float:
    """The Euclidean distance between two descriptor vectors."""
    return float(np.linalg.norm(np.asarray(a, float) - np.asarray(b, float)))
