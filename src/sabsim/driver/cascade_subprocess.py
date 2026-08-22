"""The OUT-OF-PROCESS cascade engine — the universal-MLIP activate stage.

ARCHITECTURE §4.1/§4.4 fix the normal engine model: sabsim loads LAMMPS
IN-PROCESS and shares one ``MPI_COMM_WORLD`` between ``mpi4py`` and
``liblammps``, so both link the same conda ``libmpi``. The universal
foundation MLIP that drives the default cascade (DESIGN §4.7) breaks that
assumption: it runs inside deepmd-kit's OWN self-contained bundle — its own
torch, its own LAMMPS, its own MPI — which cannot be loaded into the sabsim
process or share its communicator. (That is exactly why a self-built stack
crashed these models; the official bundle is the one that runs them.)

So for the universal cascade the WHOLE LAMMPS half of the activate stage —
cascade AND re-anneal, assembled by :func:`sabsim.driver.cascade.
build_activate_script` — is run OUT-OF-PROCESS as the bundle's ``lmp -in
<script>`` in one subprocess, and its result is handed back through a FILE
(the §4.3 file-handoff model). The sabsim process builds the slab before and
gates the written structure after; nothing is read back mid-run, which is
sound because every impact is seed-derived and the per-impact halt ends each
cascade from inside LAMMPS.

The classical cascade is unaffected: it is a built-in LAMMPS pair style, so
it keeps running in-process on CPU through :class:`~sabsim.driver.lammps_
engine.LammpsEngine`. Only the universal path comes here.
"""

from __future__ import annotations

import os
import subprocess

import numpy as np

# Where the deepmd-official bundle (the universal cascade engine) is
# installed. The registry PINS the MODEL identity (DESIGN §4.7); this names
# the ENGINE that runs it — a self-contained conda prefix with ``lmp`` and a
# ``deepmd`` pair style built in. It is a deploy-time, per-machine path (the
# bundle is GPU-architecture-specific), so it is supplied at run time here,
# the same override-by-environment discipline the model path uses.
_CASCADE_ENGINE_PREFIX_VARIABLE = "SABSIM_CASCADE_ENGINE_PREFIX"


def resolve_cascade_engine_prefix() -> str:
    """Resolve the deepmd-bundle conda prefix that runs the universal cascade.

    Read from ``SABSIM_CASCADE_ENGINE_PREFIX``. A missing or non-directory
    prefix is a LOUD stop naming the variable — never a silent fall-through
    to the in-process engine, which would run the cascade under the wrong
    LAMMPS (or crash loading the wrong torch).
    """
    prefix = os.environ.get(_CASCADE_ENGINE_PREFIX_VARIABLE, "").strip()
    if not prefix:
        raise RuntimeError(
            f"the universal cascade runs out-of-process under the deepmd "
            f"bundle, but {_CASCADE_ENGINE_PREFIX_VARIABLE} is unset. Point "
            f"it at the bundle's conda prefix (the one with bin/lmp), or "
            f"request a classical cascade (SABSIM_CASCADE_CLASSICAL).")
    if not os.path.isdir(prefix):
        raise RuntimeError(
            f"{_CASCADE_ENGINE_PREFIX_VARIABLE} names a directory that does "
            f"not exist: {prefix}")
    return prefix


def _isolated_lammps_wrapper(prefix: str, script_file: str) -> str:
    """Build the bash that activates the bundle IN ISOLATION and runs ``lmp``.

    The bundle's ``lmp`` loads its own libtorch and the deepmd pair style at
    run time; if any OTHER conda / torch env leaks in through ``PATH`` or the
    library paths, it loads the wrong libtorch and crashes. So the wrapper
    fully resets the environment before activating the prefix — the same
    reset the validated benchmark jobs use — and then hard-verifies that
    ``python`` is the bundle's before running the script. ``CUDA_VISIBLE_
    DEVICES`` is deliberately NOT unset: it carries the allocation's GPU in.

    It ALSO strips the PMIx / Open MPI runtime variables (``PMIX_*``,
    ``OMPI_*``, ``PMI_*``). The parent ``sabsim`` process is launched under
    ``srun --mpi=pmix``, so it is a legitimate PMIx client and those vars
    live in its environment. A child ``lmp`` that inherits them tries, in
    MPI_Init, to join the PARENT's PMIx namespace as an unexpected extra
    client — the first bundle subprocess in a run may get away with it, but
    a SECOND one (now that the §2.2 lattice derivation ALSO runs a bundle
    subprocess before the cascade, DESIGN §2.2/§4.7) collides with the
    stale server state and HANGS in MPI_Init (observed: a cascade `lmp`
    asleep for hours, GPU idle, only PMIx `psec/munge` warnings in its
    log). Each bundle ``lmp`` is a single ``-n1`` process that needs no MPI
    rendezvous, so clearing these vars makes it initialize as a clean
    singleton. ``compgen -e`` enumerates the exported names (the wrapper
    runs under ``bash -c``), so the strip catches whatever the launcher set
    without hard-coding the exact list.
    """
    return "\n".join([
        "set -uo pipefail",
        "unset PYTHONPATH LD_LIBRARY_PATH LAMMPS_PLUGIN_PATH "
        "DEEPMD_LMP_PLUGIN",
        "unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_PREFIX_1 CONDA_PREFIX_2 "
        "CONDA_PROMPT_MODIFIER",
        # Run each bundle lmp as an MPI SINGLETON: drop the parent's PMIx /
        # Open MPI client vars so MPI_Init does not try to join its namespace.
        'for mpi_var in $(compgen -e); do case "$mpi_var" in '
        'PMIX_*|OMPI_*|PMI_*) unset "$mpi_var" ;; esac; done',
        "export CONDA_SHLVL=0",
        "export PATH=/usr/bin:/bin",
        f'source "{prefix}/etc/profile.d/conda.sh"',
        f'conda activate "{prefix}"',
        f'case "$(command -v python)" in "{prefix}"/*) : ;; '
        '*) echo "WRONG cascade-engine python" >&2; exit 2 ;; esac',
        f'exec lmp -in "{script_file}"',
    ])


def run_activate_subprocess(
        script_lines,
        work_directory: str,
        output_structure_file: str,
        script_name: str = "activate.in",
        log_name: str = "log.activate_cascade") -> None:
    """Run the assembled activate script under the bundle's ``lmp``.

    Writes ``script_lines`` to a file in ``work_directory``, runs the bundle
    ``lmp`` on it in an isolated environment (:func:`_isolated_lammps_
    wrapper`), and confirms the run finished AND produced
    ``output_structure_file`` — the structure the caller reads back. A
    non-zero exit or a missing handoff file is a loud stop that surfaces the
    tail of the LAMMPS log, so a broken cascade never masquerades as an
    empty-but-successful one.
    """
    prefix = resolve_cascade_engine_prefix()
    script_path = os.path.join(work_directory, script_name)
    log_path = os.path.join(work_directory, log_name)
    with open(script_path, "w", encoding="utf-8") as script_file:
        script_file.write("\n".join(script_lines) + "\n")

    wrapper = _isolated_lammps_wrapper(prefix, script_path)
    with open(log_path, "w", encoding="utf-8") as log_file:
        completed = subprocess.run(
            ["bash", "-c", wrapper],
            cwd=work_directory, stdout=log_file,
            stderr=subprocess.STDOUT, check=False)

    if completed.returncode != 0 or not os.path.isfile(output_structure_file):
        raise RuntimeError(
            f"the universal cascade subprocess failed "
            f"(exit {completed.returncode}); see {log_path}. "
            f"{_log_tail(log_path)}")


def _log_tail(log_path: str, lines: int = 20) -> str:
    """The last ``lines`` of a log, for a failure message (best effort)."""
    try:
        with open(log_path, encoding="utf-8", errors="replace") as log_file:
            tail = log_file.readlines()[-lines:]
    except OSError:
        return ""
    return "Last log lines:\n" + "".join(tail)


def read_dump_structure(dump_path: str) -> tuple:
    """Read a custom LAMMPS dump into ``(positions, type_ids)`` arrays.

    Parses the handoff :func:`sabsim.driver.cascade.build_activate_script`
    writes — ``write_dump all custom <f> id type x y z modify sort id`` — for
    the gate and the amorphized-half snapshot. Column positions are read from
    the ``ITEM: ATOMS`` header rather than assumed, so a reordered dump still
    parses. Rows are sorted by atom id, giving the consecutive-id order the
    caller pairs row-for-row with the type map. The box is NOT read here: the
    cascade never changes it (open ``p p f`` box, ``minimize`` leaves the box
    untouched), so the caller reuses the slab's own cell.

    Returns ``(positions (N, 3) float, type_ids (N,) int)``.
    """
    with open(dump_path, encoding="utf-8") as dump_file:
        raw_lines = dump_file.read().splitlines()

    atom_header = None
    atom_rows = []
    reading_atoms = False
    for line in raw_lines:
        if line.startswith("ITEM: ATOMS"):
            # e.g. "ITEM: ATOMS id type x y z" -> the column names.
            atom_header = line[len("ITEM: ATOMS"):].split()
            reading_atoms = True
            continue
        if line.startswith("ITEM:"):
            reading_atoms = False           # some other section began
            continue
        if reading_atoms and line.strip():
            atom_rows.append(line.split())

    if atom_header is None:
        raise ValueError(
            f"no 'ITEM: ATOMS' section in dump {dump_path}")
    id_col = atom_header.index("id")
    type_col = atom_header.index("type")
    x_col = atom_header.index("x")
    y_col = atom_header.index("y")
    z_col = atom_header.index("z")

    atom_rows.sort(key=lambda fields: int(fields[id_col]))
    positions = np.array(
        [[float(row[x_col]), float(row[y_col]), float(row[z_col])]
         for row in atom_rows], dtype=float)
    type_ids = np.array(
        [int(row[type_col]) for row in atom_rows], dtype=int)
    return positions, type_ids
