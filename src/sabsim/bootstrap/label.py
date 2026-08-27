"""The direct VASP labeller (PSEUDOCODE.md §11.4, first slice).

Turns a set of structures into one VASP calculation each, writes ONE
SLURM job array that runs them, and afterwards harvests the energies,
forces and stresses back into a label set. Like ``sabsim prepare`` it
is a WRITER: it submits nothing, and a person submits the array.

Three things are decided here and nowhere else:

* the INCAR comes from the recipe's production settings block, so every
  label — and, later, every reference differenced against the model —
  is computed with the same settings (DESIGN.md §4.8, the inheritance
  rule);
* the k-points follow the recipe's rule: Γ only for every structure that
  is not a bulk crystal, a spacing for the two bulk families; a Γ-only
  structure is run with ``vasp_gam``, which is about twice as fast;
* a calculation that did not converge is DROPPED from the label set and
  logged, never carried as a half-converged energy.

The label set is written as extended XYZ — one frame per structure,
with ``energy``, ``forces`` and ``stress`` — because that is the form
ASE reads back directly and the prototype ANI-HDF5 converter consumes,
so ``sabsim bootstrap train`` can follow without a format change.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from ase import Atoms
from ase.io import read as ase_read
from ase.io import write as ase_write

from sabsim.bootstrap.recipe import ForceModelRecipe, ReferenceSettings
from sabsim.deploy.config import DeploymentConfig

# The two Collection-1 families that are periodic bulk crystals and so
# get real Brillouin-zone sampling; every other family is Γ only.
BULK_FAMILIES = frozenset({"bulk", "strain"})

# Label directories are numbered so the job array's task id maps to one.
_LABEL_DIRECTORY = "label_{index:05d}"
_MANIFEST = "labels.manifest.toml"
LABEL_SET_FILE = "labels.extxyz"

# The smearing schemes v0 knows, as VASP ISMEAR values.
_ISMEAR = {"gaussian": 0, "fermi": -1}


@dataclass(frozen=True)
class LabelTask:
    """One structure queued for a VASP calculation."""
    index: int
    family: str
    source: str                 # where the structure came from
    directory: str
    gamma_only: bool


def _element_order(atoms: Atoms) -> list:
    """The species in POSCAR block order — first appearance, kept."""
    order = []
    for symbol in atoms.get_chemical_symbols():
        if symbol not in order:
            order.append(symbol)
    return order


def write_incar(settings: ReferenceSettings, path: Path) -> None:
    """The INCAR every label inherits (DESIGN.md §4.8, part 3)."""
    scheme = settings.smearing_scheme.lower()
    if scheme not in _ISMEAR:
        raise ValueError(
            f"smearing scheme '{settings.smearing_scheme}' is not one this "
            f"writer knows {sorted(_ISMEAR)}")
    lines = [
        f"SYSTEM = sabsim label ({settings.functional})",
        "PREC   = Normal",
        f"ENCUT  = {settings.plane_wave_cutoff.value:g}",
        f"ISMEAR = {_ISMEAR[scheme]}",
        f"SIGMA  = {settings.smearing_width.value:g}",
        f"EDIFF  = {settings.electronic_tolerance.value:g}",
        f"NELM   = {settings.max_electronic_steps}",
        "ALGO   = Fast",
        f"LREAL  = {settings.real_space_projection}",
        f"ISPIN  = {2 if settings.spin_polarized else 1}",
        "NSW    = 0",                # single point: no relaxation
        "IBRION = -1",
        "LWAVE  = .FALSE.",
        "LCHARG = .FALSE.",
        "LASPH  = .TRUE.",
    ]
    if settings.functional.upper() != "PBE":
        lines.append(f"GGA    = {settings.functional}")
    path.write_text("\n".join(lines) + "\n")


def write_kpoints(settings: ReferenceSettings, gamma_only: bool,
                  path: Path) -> None:
    """Γ only, or a spacing rule — never a fixed mesh (DESIGN.md §4.8)."""
    if gamma_only:
        path.write_text("Gamma only\n0\nGamma\n1 1 1\n0 0 0\n")
        return
    # VASP's "fully automatic" scheme takes a length parameter R_k such
    # that N_i = max(1, R_k * |b_i| + 0.5); a spacing s (1/Å, including
    # the 2π) corresponds to R_k = 2π / s ... but VASP's |b_i| omits 2π,
    # so R_k = 1 / s in those units. Stated as the spacing the recipe
    # carries, converted here in one place.
    length = 1.0 / settings.reciprocal_spacing.value
    path.write_text(f"Automatic mesh\n0\nAuto\n{length:.4f}\n")


def write_potcar(settings: ReferenceSettings, elements: list,
                 path: Path) -> None:
    """Concatenate the recipe's PAW choices in POSCAR species order."""
    with path.open("w") as potcar:
        for element in elements:
            paw_name = settings.paw.get(element)
            if paw_name is None:
                raise KeyError(
                    f"the settings block names no PAW for '{element}'")
            source = Path(settings.paw_library) / paw_name / "POTCAR"
            potcar.write(source.read_text())


def write_label_directory(
        atoms: Atoms, settings: ReferenceSettings, directory: Path,
        gamma_only: bool) -> None:
    """POSCAR + INCAR + KPOINTS + POTCAR for one structure."""
    directory.mkdir(parents=True, exist_ok=True)
    elements = _element_order(atoms)
    ase_write(str(directory / "POSCAR"), atoms, format="vasp",
              direct=True, sort=False, parallel=False)
    write_incar(settings, directory / "INCAR")
    write_kpoints(settings, gamma_only, directory / "KPOINTS")
    write_potcar(settings, elements, directory / "POTCAR")


def select_for_labelling(structures: list, budget_per_family: int) -> list:
    """The first-slice selection rule: evenly strided, per family.

    ``structures`` is a list of ``(family, source, Atoms)``. Each family
    contributes at most ``budget_per_family`` structures, taken evenly
    across the family so a long trajectory is sampled along its whole
    length rather than only at its start.
    """
    by_family: dict = {}
    for family, source, atoms in structures:
        by_family.setdefault(family, []).append((family, source, atoms))
    chosen = []
    for family in sorted(by_family):
        members = by_family[family]
        if len(members) <= budget_per_family:
            chosen.extend(members)
            continue
        picks = np.linspace(0, len(members) - 1, budget_per_family)
        chosen.extend(members[int(round(pick))] for pick in picks)
    return chosen


def _slurm_walltime(hours: float) -> str:
    whole_hours = int(hours)
    minutes = int(round((hours - whole_hours) * 60.0))
    return f"{whole_hours:02d}:{minutes:02d}:00"


def write_label_array(
        recipe: ForceModelRecipe, deployment: DeploymentConfig,
        tasks: list, out_dir: Path) -> Path:
    """Write the one SLURM job array that labels every task (§11.4).

    Routed by the rc's ``[usage.label]`` block: partition, nodes, ranks,
    walltime and memory come from there; the VASP module from its
    ``modules`` list; the binaries from its ``environment`` map
    (``VASP_GAMMA`` for Γ-only tasks, ``VASP_STANDARD`` otherwise,
    defaulting to ``vasp_gam`` / ``vasp_std`` on the module's PATH). Each
    array task changes into its own label directory and runs. Submits
    nothing.
    """
    usage = deployment.usage["label"]
    partition = deployment.partition_for("label")
    environment = dict(usage.environment)
    gamma_binary = environment.pop("VASP_GAMMA", "vasp_gam")
    standard_binary = environment.pop("VASP_STANDARD", "vasp_std")
    hours = usage.walltime.value * (
        1.0 if usage.walltime.unit == "h" else 1.0 / 60.0)
    lines = [
        "#!/bin/bash",
        f"# VASP labelling for recipe '{recipe.name}' — written by",
        "# `sabsim bootstrap label` (DESIGN §4.8, PSEUDOCODE §11.4).",
        "# One array task per structure; submits nothing itself.",
        f"#SBATCH --job-name=sabsim-label-{recipe.name}",
        f"#SBATCH --partition={partition.name}",
        f"#SBATCH --account={deployment.default_account}",
        f"#SBATCH --nodes={usage.nodes}",
        f"#SBATCH --ntasks-per-node={usage.tasks_per_node}",
        f"#SBATCH --time={_slurm_walltime(hours)}",
        f"#SBATCH --mem={int(usage.memory.value)}"
        f"{'G' if usage.memory.unit == 'GB' else 'M'}",
        f"#SBATCH --array=0-{len(tasks) - 1}",
        f"#SBATCH --output={out_dir}/label-%A_%a.out",
        f"#SBATCH --error={out_dir}/label-%A_%a.err",
        "set -uo pipefail",
    ]
    if usage.gpus_per_node > 0:
        gres = (f"gpu:{partition.gpu_type}:{usage.gpus_per_node}"
                if partition.gpu_type else f"gpu:{usage.gpus_per_node}")
        lines.insert(12, f"#SBATCH --gres={gres}")
    for root in deployment.module_paths:
        lines.append(f"module use {root}")
    for module in usage.modules:
        lines.append(f"module load {module}")
    for name, value in sorted(environment.items()):
        lines.append(f'export {name}="{value}"')
    lines += [
        # One OpenMP thread per MPI rank. Without this the site build
        # spawns a thread per core in EVERY rank — 32 ranks x 32 threads
        # on a 64-core node (T-27's first attempt, job 16823627): the
        # first SCF step had not finished after ten minutes. A rank per
        # core with no threading is the plain, fast layout for VASP.
        "export OMP_NUM_THREADS=1",
        "unset SLURM_MEM_PER_NODE SLURM_MEM_PER_CPU SLURM_MEM_PER_GPU",
        f'TASKS="{out_dir}/{_MANIFEST}"',
        'DIRECTORY=$(python - "$SLURM_ARRAY_TASK_ID" "$TASKS" <<\'EOF\'',
        "import sys, tomllib",
        "index = int(sys.argv[1])",
        "with open(sys.argv[2], 'rb') as handle:",
        "    tasks = tomllib.load(handle)['task']",
        "task = tasks[index]",
        "print(task['directory'] + ' ' + ('gamma' if task['gamma_only']"
        " else 'standard'))",
        "EOF",
        ")",
        'set -- $DIRECTORY; cd "$1" || exit 2',
        f'if [ "$2" = gamma ]; then BINARY="{gamma_binary}"; '
        f'else BINARY="{standard_binary}"; fi',
        'echo "=== $(date) label task $SLURM_ARRAY_TASK_ID in $1 '
        'with $BINARY ==="',
        'srun --mpi=pmix "$BINARY" > vasp.out 2>&1',
        'echo "=== exit $? ==="',
    ]
    script = out_dir / f"label_{recipe.name}.slurm"
    script.write_text("\n".join(lines) + "\n")
    return script


def write_task_manifest(tasks: list, out_dir: Path) -> Path:
    """The task list the array script and the harvester both read."""
    lines = ["# label tasks written by sabsim bootstrap label", ""]
    for task in tasks:
        lines += [
            "[[task]]",
            f"index = {task.index}",
            f'family = "{task.family}"',
            f'source = "{task.source}"',
            f'directory = "{task.directory}"',
            f"gamma_only = {'true' if task.gamma_only else 'false'}",
            "",
        ]
    path = out_dir / _MANIFEST
    path.write_text("\n".join(lines))
    return path


def prepare_labels(
        recipe: ForceModelRecipe, deployment: DeploymentConfig,
        structures: list, out_dir: Path) -> tuple:
    """Select, write every label directory, the manifest and the array.

    Returns ``(tasks, script_path)``. ``structures`` is the list of
    ``(family, source, Atoms)`` the generate phase produced.
    """
    chosen = select_for_labelling(
        structures, recipe.labelling.budget_per_family)
    settings = recipe.production_settings
    tasks = []
    for index, (family, source, atoms) in enumerate(chosen):
        directory = out_dir / _LABEL_DIRECTORY.format(index=index)
        gamma_only = (settings.gamma_only_off_bulk
                      and family not in BULK_FAMILIES)
        write_label_directory(atoms, settings, directory, gamma_only)
        ase_write(str(directory / "structure.extxyz"), atoms,
                  format="extxyz", parallel=False)
        tasks.append(LabelTask(
            index=index, family=family, source=source,
            directory=str(directory), gamma_only=gamma_only))
    write_task_manifest(tasks, out_dir)
    script = write_label_array(recipe, deployment, tasks, out_dir)
    return tasks, script


# ---------------------------------------------------------------------
# Harvest: read the results back, drop what did not converge.
# ---------------------------------------------------------------------

_NELM_PATTERN = re.compile(r"NELM\s*=\s*(\d+)")


def _electronic_steps(oszicar: Path) -> int | None:
    """How many electronic steps the last ionic step took, from OSZICAR."""
    if not oszicar.is_file():
        return None
    steps = 0
    for line in oszicar.read_text().splitlines():
        if line.lstrip().startswith(("DAV:", "RMM:")):
            steps += 1
    return steps


def read_label(directory: Path, max_steps: int) -> tuple:
    """Read one finished calculation: ``(atoms_with_labels, reason)``.

    Returns ``(None, reason)`` when the calculation is unusable: no
    ``vasprun.xml``, no "General timing" line in OUTCAR (VASP did not
    finish), or as many electronic steps as ``NELM`` allowed (did not
    converge). A converged result carries ``energy`` (eV), ``forces``
    (eV/Å) and ``stress`` (eV/Å³, ASE convention) on the returned Atoms.
    """
    vasprun = directory / "vasprun.xml"
    outcar = directory / "OUTCAR"
    if not vasprun.is_file() or not outcar.is_file():
        return None, "no vasprun.xml / OUTCAR (did not run)"
    if "General timing" not in outcar.read_text(errors="replace"):
        return None, "VASP did not finish (no timing block in OUTCAR)"
    steps = _electronic_steps(directory / "OSZICAR")
    if steps is None or steps >= max_steps:
        return None, f"did not converge ({steps} electronic steps)"
    atoms = ase_read(str(vasprun), index=-1, parallel=False)
    labelled = atoms.copy()
    labelled.info["energy"] = float(atoms.get_potential_energy())
    labelled.arrays["forces"] = np.asarray(atoms.get_forces(), dtype=float)
    try:
        labelled.info["stress"] = np.asarray(
            atoms.get_stress(voigt=False), dtype=float).reshape(9)
    except Exception:              # noqa: BLE001 — stress is optional
        pass
    return labelled, "converged"


def harvest_labels(out_dir: Path, max_steps: int) -> tuple:
    """Read every task, keep the converged ones, write the label set.

    Returns ``(kept_count, dropped)`` where ``dropped`` is a list of
    ``(directory, reason)``; the label set lands at
    ``out_dir / labels.extxyz``.
    """
    import tomllib
    with (out_dir / _MANIFEST).open("rb") as handle:
        tasks = tomllib.load(handle)["task"]
    kept: list = []
    dropped: list = []
    for task in tasks:
        directory = Path(task["directory"])
        atoms, reason = read_label(directory, max_steps)
        if atoms is None:
            dropped.append((str(directory), reason))
            continue
        atoms.info["family"] = task["family"]
        atoms.info["source"] = task["source"]
        kept.append(atoms)
    if kept:
        ase_write(str(out_dir / LABEL_SET_FILE), kept, format="extxyz",
                  parallel=False)
    return len(kept), dropped
