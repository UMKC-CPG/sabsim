"""Login-node checks on the real LAMMPS adapter skeleton (driver).

The adapter cannot be RUN without LAMMPS on a compute node, but two
things ARE checkable here and worth pinning: the module imports with no
LAMMPS present (the binding is imported lazily in the constructor), and
the class implements the WHOLE Engine interface (no abstract method left
unfilled). That guarantees the compute-node work is fill-in-and-debug,
not discovering a missing method.
"""

from sabsim.driver.engine import Engine
from sabsim.driver.lammps_engine import LammpsEngine


def test_adapter_is_a_concrete_engine():
    """LammpsEngine is an Engine with every abstract method implemented."""
    assert issubclass(LammpsEngine, Engine)
    # An empty __abstractmethods__ means nothing is left unimplemented,
    # so the class is instantiable once LAMMPS is present.
    assert LammpsEngine.__abstractmethods__ == frozenset()


def test_adapter_module_imports_without_lammps():
    """Importing the adapter needs no LAMMPS (the binding is lazy)."""
    import sabsim.driver.lammps_engine as adapter
    # The module loaded (this test ran), and the class is exposed; the
    # `from lammps import ...` lives inside __init__, not at module top.
    assert hasattr(adapter, "LammpsEngine")
