"""Small helpers shared by the driver unit tests.

The command generators are tested against ``MockEngine`` with no LAMMPS
present, so they only need SOME well-formed :class:`ForceModel` to emit.
The one here is a minimal analytic pair style used purely as a fixture —
it is not a potential SABSIM runs under (the pipeline uses the universal
foundation MLIP and the DeePMD production model, DESIGN.md §4.7).
"""

from sabsim.driver.commands import ForceModel


def stand_in_force_model(type_map: dict) -> ForceModel:
    """A minimal, plugin-free ForceModel whose element list follows
    ``type_map`` order, so LAMMPS type ids line up with the species."""
    elements = " ".join(
        sorted(type_map, key=lambda symbol: type_map[symbol]))
    return ForceModel(
        pair_style="sw",
        pair_coeff=(f"* * Si.sw {elements}",))
