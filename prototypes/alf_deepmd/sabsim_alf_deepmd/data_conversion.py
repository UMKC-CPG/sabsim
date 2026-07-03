"""Convert ALF's ANI-style HDF5 training data into DeePMD systems.

ALF (the LANL Active Learning Framework) stores every labelled
configuration in an ANI-style HDF5 file, written by
``alframework.tools.tools.store_current_data`` through the
``pyanitools.datapacker`` class.  DeePMD-kit, on the other hand, reads
training data from its own on-disk "system" layout (``type.raw`` plus a
``set.000/`` folder of ``.npy`` arrays).  This module is the bridge
between the two so that a DeePMD backend can consume exactly the data
ALF already produces, with no change to ALF itself.

------------------------------------------------------------------
The ANI-style HDF5 schema (what we read)
------------------------------------------------------------------
The file is a set of groups, one per empirical formula.  Each group
holds these datasets (see ``store_current_data``):

  * ``species``      -- (n_atoms,) chemical symbols, sorted by atomic
                        number; stored as UTF-8 byte strings.
  * ``coordinates``  -- (n_frames, n_atoms, 3) positions, in Angstrom.
  * ``cell``         -- (n_frames, 3, 3) lattice vectors, in Angstrom.
                        Present only for periodic systems.
  * <energy db-key>  -- (n_frames,) total energy, stored as the ASE
                        value multiplied by a unit factor (see below).
  * <force  db-key>  -- (n_frames, n_atoms, 3) forces, likewise scaled.

The energy/force dataset *names* and their unit factors come from the
``properties_list`` mapping in ALF's ``master_config.json``, e.g.::

    "properties_list": {
        "energy": ["energy", "system", 27.211386024367243],
        "forces": ["forces", "atomic", 51.422067090480645]
    }

Each entry is ``[db_key, per_system_or_atomic, unit_factor]``.  ALF
*multiplies* the native ASE value (eV and eV/Angstrom) by ``unit_factor``
before storing.  Therefore, to recover the ASE-native value we simply
*divide* the stored value by the same factor -- a clean, exact round
trip regardless of which unit system the factor encodes.

------------------------------------------------------------------
The DeePMD system layout (what we write)
------------------------------------------------------------------
For each formula-group we emit one DeePMD "system" directory::

    <output_dir>/<formula>/
        type_map.raw          all element symbols, one per line (global)
        type.raw              per-atom type indices into type_map
        nopbc                 empty marker file (only for non-periodic)
        set.000/
            coord.npy         (n_frames, n_atoms*3)  float64, Angstrom
            box.npy           (n_frames, 9)          float64, Angstrom
            energy.npy        (n_frames,)            float64, eV
            force.npy         (n_frames, n_atoms*3)  float64, eV/Angstrom

DeePMD's standard units are eV, eV/Angstrom, and Angstrom, which is
exactly what we hand it after dividing out the ALF unit factors.
"""

import os
import glob

import numpy as np

# ALF ships this loader; it is importable once ALF is on the PYTHONPATH.
from alframework.tools.pyanitools import anidataloader


def _resolve_property_keys(properties_list):
    """Pull the energy and force db-keys and factors from the config.

    Args:
        properties_list (dict): The ``properties_list`` mapping taken
            verbatim from ALF's ``master_config.json``.  Keys are the
            high-level property names ("energy", "forces"); each value
            is ``[db_key, "system"|"atomic", unit_factor]``.

    Returns:
        tuple: ``(energy_db_key, energy_factor, force_db_key,
        force_factor)``.  The force entries are ``None`` when no force
        property is configured (energy-only training).
    """
    energy_entry = properties_list["energy"]
    energy_db_key = energy_entry[0]
    energy_factor = float(energy_entry[2])

    # Forces are optional: a few ALF setups train on energy alone.
    force_db_key = None
    force_factor = None
    if "forces" in properties_list:
        force_entry = properties_list["forces"]
        force_db_key = force_entry[0]
        force_factor = float(force_entry[2])

    return energy_db_key, energy_factor, force_db_key, force_factor


def _build_global_type_map(h5_paths, species_per_group):
    """Collect every element seen anywhere into one ordered type map.

    DeePMD needs a single, stable ``type_map`` shared by all systems so
    that atom type index ``k`` means the same element in every model and
    in the later LAMMPS deployment.  We sort by atomic-number-free
    alphabetical order for reproducibility; the exact order is arbitrary
    but must stay fixed once chosen.

    Args:
        h5_paths (list): Paths of the HDF5 files (only used for the
            error message if nothing was found).
        species_per_group (list): One ``numpy`` array of element symbols
            per formula-group already read from the files.

    Returns:
        list: The global, de-duplicated, sorted list of element symbols.
    """
    all_elements = set()
    for species in species_per_group:
        all_elements.update(str(symbol) for symbol in species)

    if not all_elements:
        raise ValueError(
            "No atomic species found in any HDF5 file: " + str(h5_paths))

    return sorted(all_elements)


def _decode_species(raw_species):
    """Return a clean list of ``str`` symbols from an HDF5 species array.

    The packer stores symbols as UTF-8 byte strings; ``anidataloader``
    usually decodes them already, but we normalise defensively so the
    converter works whether it receives ``bytes`` or ``str``.
    """
    decoded = []
    for symbol in raw_species:
        if isinstance(symbol, bytes):
            decoded.append(symbol.decode("utf-8"))
        else:
            decoded.append(str(symbol))
    return decoded


def ani_h5_to_deepmd(h5_paths, output_dir, properties_list):
    """Convert one or more ANI-style HDF5 files into DeePMD systems.

    This walks every formula-group in every file, recovers ASE-native
    units, and writes a DeePMD system per group under ``output_dir``.

    Args:
        h5_paths (list): Paths to the ALF HDF5 data files to convert.
        output_dir (str): Directory to create the DeePMD systems in.
        properties_list (dict): ALF's ``properties_list`` mapping, used
            to find the energy/force db-keys and to undo the unit
            scaling applied at storage time.

    Returns:
        tuple: ``(type_map, system_dirs)`` where ``type_map`` is the
        global element list and ``system_dirs`` is the list of system
        directories written (handy to feed straight into a DeePMD
        ``input.json``).
    """
    energy_db_key, energy_factor, force_db_key, force_factor = (
        _resolve_property_keys(properties_list))

    # First pass: read every group into memory so we can build a single
    # global type map before writing anything.  Training sets from an
    # active-learning loop are modest, so holding them briefly is fine.
    groups = []
    species_per_group = []
    for h5_path in h5_paths:
        loader = anidataloader(h5_path)
        for group in loader:
            species = _decode_species(group["species"])
            species_per_group.append(species)
            groups.append(group)
        loader.cleanup()

    type_map = _build_global_type_map(h5_paths, species_per_group)
    element_to_type_index = {
        element: index for index, element in enumerate(type_map)}

    os.makedirs(output_dir, exist_ok=True)
    system_dirs = []

    for group, species in zip(groups, species_per_group):
        formula = os.path.basename(str(group["path"]).strip("/"))
        system_dir = os.path.join(output_dir, formula)
        set_dir = os.path.join(system_dir, "set.000")
        os.makedirs(set_dir, exist_ok=True)

        number_of_atoms = len(species)

        # Coordinates: (n_frames, n_atoms, 3) Angstrom -> flat per frame.
        coordinates = np.asarray(group["coordinates"], dtype=np.float64)
        number_of_frames = coordinates.shape[0]
        coord_flat = coordinates.reshape(number_of_frames, -1)

        # Energy: undo the storage factor to return to eV.
        energy = np.asarray(group[energy_db_key], dtype=np.float64)
        energy = energy.reshape(number_of_frames) / energy_factor

        # Per-atom type indices into the global type map.
        type_indices = np.array(
            [element_to_type_index[element] for element in species],
            dtype=np.int64)

        # Write the always-present arrays.
        np.save(os.path.join(set_dir, "coord.npy"), coord_flat)
        np.save(os.path.join(set_dir, "energy.npy"), energy)

        # Forces are optional; only write them when configured/present.
        if force_db_key is not None and force_db_key in group:
            forces = np.asarray(group[force_db_key], dtype=np.float64)
            forces = forces.reshape(number_of_frames, number_of_atoms, 3)
            forces = forces / force_factor
            np.save(os.path.join(set_dir, "force.npy"),
                    forces.reshape(number_of_frames, -1))

        # Periodicity: write the box if a cell was stored, otherwise
        # drop a ``nopbc`` marker so DeePMD treats the system as a
        # gas-phase / cluster configuration.
        if "cell" in group:
            cell = np.asarray(group["cell"], dtype=np.float64)
            cell = cell.reshape(number_of_frames, 9)
            np.save(os.path.join(set_dir, "box.npy"), cell)
        else:
            open(os.path.join(system_dir, "nopbc"), "w").close()

        # The per-atom type list and (redundantly) the per-system map.
        np.savetxt(os.path.join(system_dir, "type.raw"),
                   type_indices, fmt="%d")
        with open(os.path.join(system_dir, "type_map.raw"), "w") as out:
            out.write("\n".join(type_map) + "\n")

        system_dirs.append(system_dir)

    return type_map, system_dirs
