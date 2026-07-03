"""Unit test for the ANI-HDF5 -> DeePMD converter (round-trip check).

This test validates the central correctness claim of the DeePMD
prototype: that ``ani_h5_to_deepmd`` reads ALF's ANI-style HDF5 training
data and emits DeePMD "system" directories whose numbers exactly match
the inputs, with the ALF unit factors cleanly undone.

Why a *synthetic* input file instead of a real ``data-*.h5``:
we have not run ALF yet, so no real file exists -- but more importantly,
by generating the file ourselves we know every native (eV, eV/Angstrom,
Angstrom) value that went in.  That lets us assert the *exact* value that
should come out, which a real file (whose native values we would not
know) could never give us.  To make the synthetic file schema-identical
to what a production run writes, we build it with ALF's own
``pyanitools.datapacker`` -- the very writer that pairs with the
``anidataloader`` the converter consumes.

The test covers both branches of the converter:

  * a **periodic** system (a stored ``cell`` -> a ``box.npy`` is written,
    and no ``nopbc`` marker appears), and
  * a **non-periodic** system (no ``cell`` -> a ``nopbc`` marker file is
    written, and no ``box.npy`` appears).

Run it either way::

    pytest prototypes/alf_deepmd/tests/test_data_conversion.py -v
    python  prototypes/alf_deepmd/tests/test_data_conversion.py
"""

import os
import sys
import tempfile

import numpy as np

# Make the prototype package importable whether or not it is installed:
# the package root is the parent directory of this ``tests`` folder.
PROTOTYPE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROTOTYPE_ROOT not in sys.path:
    sys.path.insert(0, PROTOTYPE_ROOT)

from sabsim_alf_deepmd.data_conversion import ani_h5_to_deepmd
from alframework.tools.pyanitools import datapacker


# ---------------------------------------------------------------------
# Fixed, known-native test data (the values a real run would *not* let
# us know a priori).  Energies are in eV, forces in eV/Angstrom, and
# coordinates / cells in Angstrom -- DeePMD's native units.
# ---------------------------------------------------------------------

# The ``properties_list`` mirrors a real ALF ``master_config.json``.
# The factors are the Hartree-based scalings ALF applies before storing;
# the converter must divide them back out.  Their exact meaning does not
# matter to the test -- only that store-then-convert is the identity.
ENERGY_FACTOR = 27.211386024367243        # eV -> Hartree at storage time
FORCE_FACTOR = 51.422067090480645         # eV/Ang -> Hartree/Bohr, say
PROPERTIES_LIST = {
    "energy": ["energy", "system", ENERGY_FACTOR],
    "forces": ["forces", "atomic", FORCE_FACTOR],
}

# A periodic 3-atom water-like group, two frames.  Species are given in
# atomic-number-sorted order (H, H, O) exactly as ALF stores them.
WATER_SPECIES = ["H", "H", "O"]
WATER_COORDS_ANG = np.array(
    [[[0.00, 0.00, 0.00],
      [0.96, 0.00, 0.00],
      [0.24, 0.93, 0.00]],
     [[0.01, 0.02, 0.00],
      [0.97, 0.00, 0.01],
      [0.25, 0.92, 0.02]]], dtype=np.float64)
WATER_CELL_ANG = np.array(
    [[[10.0, 0.0, 0.0], [0.0, 10.0, 0.0], [0.0, 0.0, 10.0]],
     [[10.1, 0.0, 0.0], [0.0, 10.0, 0.0], [0.0, 0.0, 9.9]]],
    dtype=np.float64)
WATER_ENERGY_EV = np.array([-14.221, -14.198], dtype=np.float64)
WATER_FORCES_EV_ANG = np.array(
    [[[0.10, -0.20, 0.00],
      [-0.05, 0.15, 0.00],
      [-0.05, 0.05, 0.00]],
     [[0.11, -0.19, 0.01],
      [-0.06, 0.14, -0.01],
      [-0.05, 0.05, 0.00]]], dtype=np.float64)

# A non-periodic 2-atom hydrogen-molecule group, three frames.  No cell
# is stored, so the converter should emit a ``nopbc`` marker instead of a
# ``box.npy``.
H2_SPECIES = ["H", "H"]
H2_COORDS_ANG = np.array(
    [[[0.00, 0.0, 0.0], [0.74, 0.0, 0.0]],
     [[0.00, 0.0, 0.0], [0.75, 0.0, 0.0]],
     [[0.00, 0.0, 0.0], [0.76, 0.0, 0.0]]], dtype=np.float64)
H2_ENERGY_EV = np.array([-31.4, -31.5, -31.45], dtype=np.float64)
H2_FORCES_EV_ANG = np.array(
    [[[0.30, 0.0, 0.0], [-0.30, 0.0, 0.0]],
     [[0.20, 0.0, 0.0], [-0.20, 0.0, 0.0]],
     [[0.10, 0.0, 0.0], [-0.10, 0.0, 0.0]]], dtype=np.float64)


def _write_synthetic_h5(h5_path):
    """Write a two-group ANI-style HDF5 file with ALF's own packer.

    Values are stored exactly as ALF stores them: the native eV /
    eV-per-Angstrom arrays multiplied by the configured unit factors.
    The converter under test must divide those factors back out.

    Args:
        h5_path (str): Destination path for the HDF5 file to create.
    """
    packer = datapacker(h5_path)

    # Periodic water group -- note the *scaled* energy/forces going in.
    packer.store_data(
        "H2O",
        species=WATER_SPECIES,
        coordinates=WATER_COORDS_ANG,
        cell=WATER_CELL_ANG,
        energy=WATER_ENERGY_EV * ENERGY_FACTOR,
        forces=WATER_FORCES_EV_ANG * FORCE_FACTOR,
    )

    # Non-periodic hydrogen group -- deliberately no ``cell`` dataset.
    packer.store_data(
        "H2",
        species=H2_SPECIES,
        coordinates=H2_COORDS_ANG,
        energy=H2_ENERGY_EV * ENERGY_FACTOR,
        forces=H2_FORCES_EV_ANG * FORCE_FACTOR,
    )

    packer.cleanup()


def test_ani_h5_to_deepmd_round_trip():
    """Convert a synthetic file and assert every DeePMD array is exact.

    Verifies: the global ``type_map``; per-frame coordinate/energy/force
    shapes and values (with the unit factors undone); the presence of
    ``box.npy`` for the periodic system and of a ``nopbc`` marker for the
    non-periodic one; and the per-atom ``type.raw`` indices.
    """
    with tempfile.TemporaryDirectory() as work_dir:
        h5_path = os.path.join(work_dir, "data-000.h5")
        output_dir = os.path.join(work_dir, "deepmd_data")
        _write_synthetic_h5(h5_path)

        type_map, system_dirs = ani_h5_to_deepmd(
            [h5_path], output_dir, PROPERTIES_LIST)

        # --- global type map: sorted unique elements across all groups.
        assert type_map == ["H", "O"], type_map
        assert len(system_dirs) == 2, system_dirs

        # ---------------------------------------------------------------
        # Periodic water system: box.npy present, no nopbc marker.
        # ---------------------------------------------------------------
        water_dir = os.path.join(output_dir, "H2O")
        water_set = os.path.join(water_dir, "set.000")

        coord = np.load(os.path.join(water_set, "coord.npy"))
        energy = np.load(os.path.join(water_set, "energy.npy"))
        force = np.load(os.path.join(water_set, "force.npy"))
        box = np.load(os.path.join(water_set, "box.npy"))

        # Shapes follow the DeePMD system layout exactly.
        assert coord.shape == (2, 9), coord.shape
        assert energy.shape == (2,), energy.shape
        assert force.shape == (2, 9), force.shape
        assert box.shape == (2, 9), box.shape

        # Values: coordinates/cells pass through; energy/force are the
        # stored (scaled) values divided by the factors == the natives.
        np.testing.assert_allclose(
            coord, WATER_COORDS_ANG.reshape(2, 9))
        np.testing.assert_allclose(box, WATER_CELL_ANG.reshape(2, 9))
        np.testing.assert_allclose(energy, WATER_ENERGY_EV)
        np.testing.assert_allclose(
            force, WATER_FORCES_EV_ANG.reshape(2, 9))

        # A periodic system must NOT carry a nopbc marker.
        assert not os.path.exists(os.path.join(water_dir, "nopbc"))

        # Per-atom types index into the global map: H=0, H=0, O=1.
        water_types = np.loadtxt(
            os.path.join(water_dir, "type.raw"), dtype=np.int64)
        np.testing.assert_array_equal(water_types, [0, 0, 1])

        # ---------------------------------------------------------------
        # Non-periodic hydrogen system: nopbc marker, no box.npy.
        # ---------------------------------------------------------------
        h2_dir = os.path.join(output_dir, "H2")
        h2_set = os.path.join(h2_dir, "set.000")

        h2_coord = np.load(os.path.join(h2_set, "coord.npy"))
        h2_energy = np.load(os.path.join(h2_set, "energy.npy"))
        h2_force = np.load(os.path.join(h2_set, "force.npy"))

        assert h2_coord.shape == (3, 6), h2_coord.shape
        assert h2_energy.shape == (3,), h2_energy.shape
        assert h2_force.shape == (3, 6), h2_force.shape

        np.testing.assert_allclose(
            h2_coord, H2_COORDS_ANG.reshape(3, 6))
        np.testing.assert_allclose(h2_energy, H2_ENERGY_EV)
        np.testing.assert_allclose(
            h2_force, H2_FORCES_EV_ANG.reshape(3, 6))

        # A gas-phase system MUST carry a nopbc marker and no box.npy.
        assert os.path.exists(os.path.join(h2_dir, "nopbc"))
        assert not os.path.exists(os.path.join(h2_set, "box.npy"))

        # Both atoms are hydrogen -> both index 0 in the global map.
        h2_types = np.loadtxt(
            os.path.join(h2_dir, "type.raw"), dtype=np.int64)
        np.testing.assert_array_equal(h2_types, [0, 0])


if __name__ == "__main__":
    # Allow a plain ``python test_data_conversion.py`` run without pytest
    # so the converter can be exercised inside the ALF environment with
    # nothing but numpy, h5py, and ALF on the path.
    test_ani_h5_to_deepmd_round_trip()
    print("PASS: ANI-HDF5 -> DeePMD round-trip is exact "
          "(periodic + non-periodic).")
