"""Measure a material's in-plane biaxial modulus (DESIGN.md §2.4, §7.2).

The §2.4 strain split places the shared coincidence cell at the
STIFFNESS-weighted average of the two materials' natural sizes, so the
stiffer, thicker slab moves less and neither is over-stressed. That
weighting needs each material's in-plane BIAXIAL MODULUS *under the
current potential* -- not a literature value, because the split must be
true for the model that will actually run the dynamics -- and the same
elastic constants feed the §7.2 potential-quality gate. This module
measures it.

The method is the one the archived T-17 stiffness probe demonstrated,
now with the fit CODED. Strain a slab of the material in-plane by a small
symmetric sweep of biaxial strains, read the mean in-plane stress at each,
and take the slope of stress versus strain. A slab (not a bulk block) is
strained because that is exactly what the split strains; the free surface
adds only a strain-INDEPENDENT offset, so it shifts the line but not its
slope. The sweep stays within the linear-elastic range (a percent or so),
so a straight line through the points is the modulus without provoking
any yielding.

Like :mod:`sabsim.driver.bulk_relax`, the routine is written against the
:class:`~sabsim.driver.engine.Engine` seam, so it is fully tested against
``MockEngine`` here and the real LAMMPS adapter drops in unchanged behind
the same interface on a compute node. The measurement is a sequence of
zero-step stress reads on a deformed box, so it is cheap and deterministic
given the potential.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from sabsim.driver.commands import ForceModel, force_model_commands
from sabsim.driver.engine import Engine

# The default biaxial strains, symmetric about zero. Small enough to stay
# linear-elastic (so the slope is the modulus), spread enough that the fit
# is not dominated by the stress read's noise. A numerical knob in spirit
# (DESIGN.md §1.2): the answer must be invariant to widening or tightening
# it within the linear range; these are a reasonable starting point.
STRAIN_SWEEP = (-0.010, -0.005, 0.0, 0.005, 0.010)

# LAMMPS metal pressure is bar; the modulus is reported in GPa.
_BAR_PER_GPA = 10000.0


@dataclass(frozen=True)
class BiaxialStiffness:
    """A material's measured in-plane biaxial modulus (§2.4).

    ``biaxial_modulus_gpa`` is the headline number the §2.4 split reads.
    ``strains`` and ``in_plane_stress_bar`` are the raw sweep the modulus
    was fit from -- kept so the linearity can be inspected and the fit
    re-derived, exactly as a measurement should carry its evidence.
    """

    biaxial_modulus_gpa: float
    strains: tuple
    in_plane_stress_bar: tuple


def biaxial_stiffness_commands(
        data_file: str,
        force_model: ForceModel) -> list:
    """The LAMMPS setup stream for a strained-slab stress measurement.

    A slab box is periodic in-plane and OPEN along z (``boundary p p f``,
    the same as the activation and press boxes), loaded with the given
    force model. No integrator and no minimize: the strain sweep only
    deforms the box and reads the resulting stress, so this is setup only.
    """
    return [
        "units metal",
        "atom_style atomic",
        "boundary p p f",
        f"read_data {data_file}",
        *force_model_commands(force_model),
    ]


def strain_step_commands(relative_factor: float) -> list:
    """Deform the in-plane box by ``relative_factor`` and refresh the stress.

    ``change_box`` scales the x and y box lengths RELATIVE to the current
    box (``remap`` carries the atoms with the box, so fractional positions
    are held -- a pure biaxial in-plane stretch), then a zero-step ``run``
    re-evaluates the pressure tensor so the next stress read is current.
    The caller steps from one sweep strain to the next with the ratio of
    their ``(1 + strain)`` factors, so the box lands at the absolute strain
    even though each step is relative.
    """
    factor = f"{relative_factor:.12g}"
    return [
        f"change_box all x scale {factor} y scale {factor} remap units box",
        "run 0",
    ]


def fit_biaxial_modulus(strains, in_plane_stress_bar) -> float:
    """The biaxial modulus (GPa) from a stress-versus-strain sweep.

    LAMMPS pressure is POSITIVE under compression, so stretching a slab
    (positive strain) puts it in tension and the mean in-plane stress goes
    NEGATIVE: to first order ``stress = -modulus * strain``. The modulus is
    therefore MINUS the least-squares slope of stress against strain,
    converted from bar to GPa. A plain closed-form least-squares slope
    (covariance over variance) is used -- no numpy polynomial helper -- so
    there is nothing to deprecate and the arithmetic is legible.
    """
    strain = np.asarray(strains, dtype=float)
    stress = np.asarray(in_plane_stress_bar, dtype=float)
    strain_centered = strain - strain.mean()
    slope = float(
        np.sum(strain_centered * (stress - stress.mean()))
        / np.sum(strain_centered ** 2))
    return -slope / _BAR_PER_GPA


def measure_biaxial_modulus(
        engine: Engine,
        data_file: str,
        force_model: ForceModel,
        strains=STRAIN_SWEEP) -> BiaxialStiffness:
    """Strain a slab through the sweep and fit its biaxial modulus (§2.4).

    Sets the slab up once, then walks the strain sweep: each step deforms
    the box from the PREVIOUS strain to the next (the relative factor is
    the ratio of their ``1 + strain`` values, so the box sits at the
    absolute strain), and reads the mean in-plane stress there. The slope
    of the collected stress-versus-strain points is the modulus. Because
    it talks only to :class:`Engine`, this runs identically against
    ``MockEngine`` (login node) and the real LAMMPS adapter (compute node).
    """
    engine.commands(biaxial_stiffness_commands(data_file, force_model))
    stresses: list = []
    previous_strain = 0.0
    for strain in strains:
        relative_factor = (1.0 + strain) / (1.0 + previous_strain)
        engine.commands(strain_step_commands(relative_factor))
        stresses.append(float(engine.in_plane_stress()))
        previous_strain = strain
    modulus = fit_biaxial_modulus(strains, stresses)
    return BiaxialStiffness(
        biaxial_modulus_gpa=modulus,
        strains=tuple(float(strain) for strain in strains),
        in_plane_stress_bar=tuple(stresses))
