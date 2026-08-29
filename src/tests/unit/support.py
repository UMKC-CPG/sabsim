"""Small helpers shared by the driver unit tests.

The command generators are tested against ``MockEngine`` with no LAMMPS
present, so they only need SOME well-formed :class:`ForceModel` to emit.
The one here is LAMMPS's built-in ``zero`` pair style — a style that
computes no forces at all — used purely as a fixture: it is not a
potential SABSIM runs under (the pipeline uses the universal foundation
MLIP and the DeePMD production model, DESIGN.md §4.7), and it names no
interatomic model, so no test can mistake it for one.
"""

from sabsim.driver.commands import ForceModel


def stand_in_force_model(type_map: dict) -> ForceModel:
    """A minimal, plugin-free, force-free ForceModel over ``type_map``.

    ``pair_style zero`` takes only a cutoff and one ``pair_coeff * *``
    line, whatever the species, so the fixture is the same shape for any
    type map — the command generators only need SOME well-formed model.
    """
    del type_map                     # any species set: zero has no coeffs
    return ForceModel(
        pair_style="zero 6.0",
        pair_coeff=("* *",))
