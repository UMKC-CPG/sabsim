"""Unit tests for the biaxial-stiffness measurement (sabsim.driver).

The modulus is fit from a stress-versus-strain sweep, so these tests pin
the fit (a known slope in, the modulus out, a surface offset ignored) and
the sweep orchestration (the command stream deforms the box once per
strain and the scripted stresses feed the fit) -- all against MockEngine,
no LAMMPS.
"""

from sabsim.driver.biaxial_stiffness import (
    STRAIN_SWEEP,
    fit_biaxial_modulus,
    measure_biaxial_modulus,
    strain_step_commands,
)
from sabsim.driver.commands import ForceModel
from sabsim.driver.engine import MockEngine


def _stress_for(modulus_gpa, strains, offset_bar=0.0):
    """LAMMPS-sign stress for a modulus: stress = offset - M * strain.

    Pressure is positive in compression, so stretching (+strain) gives a
    negative (tension) stress; the free surface adds a constant offset.
    """
    modulus_bar = modulus_gpa * 10000.0
    return tuple(offset_bar - modulus_bar * strain for strain in strains)


def test_fit_recovers_a_known_modulus_ignoring_the_surface_offset():
    """A clean line in gives the modulus out; a constant offset is ignored."""
    strains = STRAIN_SWEEP
    clean = fit_biaxial_modulus(strains, _stress_for(200.0, strains))
    assert abs(clean - 200.0) < 1.0e-6
    # A big strain-INDEPENDENT surface offset shifts the line, not its slope.
    offset = fit_biaxial_modulus(
        strains, _stress_for(200.0, strains, offset_bar=5.0e5))
    assert abs(offset - 200.0) < 1.0e-6
    # A different stiffness comes back correctly.
    stiffer = fit_biaxial_modulus(strains, _stress_for(276.0, strains))
    assert abs(stiffer - 276.0) < 1.0e-6


def test_measure_walks_the_sweep_and_fits_the_modulus():
    """measure_biaxial_modulus deforms once per strain and fits the slope."""
    strains = STRAIN_SWEEP
    scripted = _stress_for(234.0, strains)
    engine = MockEngine(in_plane_stress=scripted)
    model = ForceModel(pair_style="sw", pair_coeff=("* * Si.sw Si",))
    result = measure_biaxial_modulus(engine, "slab.data", model, strains)

    assert abs(result.biaxial_modulus_gpa - 234.0) < 1.0e-6
    assert result.strains == tuple(float(strain) for strain in strains)
    assert result.in_plane_stress_bar == scripted
    # One box deformation per strain in the sweep.
    deforms = [line for line in engine.received_commands
               if line.startswith("change_box")]
    assert len(deforms) == len(strains)
    # Setup ran once: the slab box is open along z and the data is read.
    assert "boundary p p f" in engine.received_commands
    assert "read_data slab.data" in engine.received_commands


def test_strain_step_scales_x_and_y_together_and_refreshes():
    """A strain step scales x and y by the same factor, remaps, runs 0."""
    commands = strain_step_commands(1.01)
    assert commands == [
        "change_box all x scale 1.01 y scale 1.01 remap units box",
        "run 0",
    ]
