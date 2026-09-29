"""Cut an interface frame down to a labelling sub-cell (DESIGN.md §6.4).

An all-electron calculation on a whole production cell (~2000 atoms) is
an order of magnitude beyond a routine budget, and the potential is
short-ranged, so a training configuration only needs to keep the
neighbourhood the model actually learns from: the two activated skins
and a little ordered crystal beneath each. This module keeps exactly
that — the skin depth plus a stated number of whole crystalline layers
under it on each wafer — and drops the deeper crystal.

The cut is made in WHOLE LAYERS of the crystal (the layer spacing along
the surface normal is a property of the phase and face), so the last
kept plane is a complete crystal plane rather than a ragged one, and the
result is closed with a vacuum gap so the two cut planes become ordinary
free surfaces. That is the lean choice (2026-08-26): the surface atoms are
what the training is for, and a free crystalline face is valid physics, not
contamination. (§6.4's seamless re-join across the periodic boundary —
removing layers and closing the gap with no surface at all — is the tighter
alternative for the audit block; it needs the two kept blocks to be
commensurate in z, which a same-material pair allows and a dissimilar pair
does not.)
"""

from __future__ import annotations

import numpy as np
from ase import Atoms

from sabsim.structure.slab_builder import WAFER_A_TAG, WAFER_B_TAG


def cut_interface_subcell(
        atoms: Atoms,
        tags: np.ndarray,
        interface_z: float,
        skin_depth: float,
        layer_spacing: float,
        crystalline_layers: int,
        vacuum: float) -> Atoms:
    """Keep each wafer's skin plus ``crystalline_layers`` beneath it.

    ``tags`` mark each atom as wafer A (bottom) or B (top), ``interface_z``
    is the plane between them, ``skin_depth`` how far the activated
    disorder reaches into each wafer (the project's build-time estimate, or
    the gate's measured depth once it exists), and ``layer_spacing`` the
    crystal's plane spacing along z for this face. Wafer A keeps
    everything above ``interface_z - skin_depth - n*d`` and wafer B
    everything below ``interface_z + skin_depth + n*d``; the kept slab is
    shifted to start at ``z = 0`` and closed with ``vacuum`` above it. In
    x and y the cell is unchanged, so the full lateral periodicity of the
    shared cell survives (§6.4 rule 1).
    """
    positions = np.asarray(atoms.get_positions(), dtype=float)
    tags = np.asarray(tags)
    reach = skin_depth + crystalline_layers * layer_spacing
    keep_a = (tags == WAFER_A_TAG) & (positions[:, 2] >= interface_z - reach)
    keep_b = (tags == WAFER_B_TAG) & (positions[:, 2] <= interface_z + reach)
    keep = keep_a | keep_b
    if keep.sum() == 0:
        raise ValueError(
            "the interface sub-cell would be empty: check interface_z, "
            "the wafer tags and the skin depth")
    kept = atoms[keep]
    kept_positions = np.asarray(kept.get_positions(), dtype=float)
    kept_positions[:, 2] -= kept_positions[:, 2].min()
    kept.set_positions(kept_positions)
    cell = np.asarray(atoms.get_cell(), dtype=float).copy()
    cell[2] = [0.0, 0.0, kept_positions[:, 2].max() + vacuum]
    kept.set_cell(cell)
    kept.set_pbc([True, True, True])   # periodic z across the vacuum
    kept.set_tags(tags[keep])
    return kept


def layer_spacing_along_normal(
        lattice_constant: float, face: tuple) -> float:
    """The plane spacing along the surface normal of a CUBIC crystal.

    For a cubic lattice the spacing of the ``(h k l)`` planes is
    ``a / sqrt(h^2 + k^2 + l^2)``. Diamond silicon (100) has atomic
    planes every ``a/4`` — half the (200) spacing this returns — so the
    caller that wants ATOMIC layers rather than lattice planes divides
    accordingly; the recipe counts crystalline layers in atomic planes,
    which :func:`atomic_layer_spacing` supplies for the common faces.
    """
    h, k, l = (int(component) for component in face)
    return lattice_constant / float(np.sqrt(h * h + k * k + l * l))


# Atomic-plane spacing along the normal, as a fraction of the cubic
# lattice constant, for the diamond structure's low-index faces: (100)
# planes every a/4, (110) every a/(2*sqrt 2), (111) bilayers every
# a*sqrt(3)/4 on average. A face not listed falls back to the lattice-
# plane spacing (a conservative, slightly thicker cut).
_DIAMOND_ATOMIC_PLANE_FRACTION = {
    (1, 0, 0): 0.25,
    (1, 1, 0): 1.0 / (2.0 * np.sqrt(2.0)),
    (1, 1, 1): np.sqrt(3.0) / 4.0,
}


def atomic_layer_spacing(lattice_constant: float, face: tuple) -> float:
    """Atomic-plane spacing along the normal for a diamond-cubic face."""
    key = tuple(abs(int(component)) for component in face)
    fraction = _DIAMOND_ATOMIC_PLANE_FRACTION.get(key)
    if fraction is None:
        return layer_spacing_along_normal(lattice_constant, face)
    return lattice_constant * float(fraction)
