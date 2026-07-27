"""The within-run resume checkpoint module (PSEUDOCODE.md §13).

A pull the scheduler kills partway is carried to its proper end by
restoring a CHECKPOINT: a matched pair of the engine's saved state and a
small ledger of the run's progress (DESIGN.md §11). This module holds the
pair's honest core — how it is written so a kill mid-write leaves no
half-pair, how it is read back only when BOTH parts are present, and how a
ledger that ran a few bursts past the saved state is reconciled to it. The
pull's own loop (:mod:`sabsim.driver.press_pull`) calls these; nothing
here runs a simulation, so every routine is tested against ``MockEngine``
with no LAMMPS (§13.7).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

from sabsim.driver.engine import Engine


# The two files that make up the pair on disk (§13.2). Their names are
# fixed, so a rung's own directory is all that is needed to find them.
_ENGINE_STATE_NAME = "engine.restart"
_LEDGER_NAME = "ledger.json"


@dataclass
class Ledger:
    """The pull's progress that lives in program memory (§13.1).

    A resume that restored only the engine would keep the atoms but lose
    this record — the accumulated series the final curves are built from,
    the atom-count baseline the §5.6 gate checks against, and how far the
    run has come. So it is saved beside the engine state and restored with
    it. Every sample is keyed to the engine's ABSOLUTE step
    (``sample_steps``), which is what lets a resume line the record back up
    with the restored atoms and trim any overhang (:func:`reconcile`).
    """

    # The engine step each sample below was taken at — the key that makes
    # reconcile well-defined (§13.2). Row-for-row with the four series.
    sample_steps: list = field(default_factory=list)
    displacement: list = field(default_factory=list)  # grip travel (§9.5)
    force: list = field(default_factory=list)         # top-grip reaction
    opening: list = field(default_factory=list)       # interface opening
    bridges: list = field(default_factory=list)       # cross-interface bonds
    # The §5.6 conservation baseline, measured once as the pull starts.
    starting_atom_count: int = 0
    # The engine step the paired saved state was written at.
    saved_step: int = 0
    # The §13.4 trust field: a hash of the run's inputs, compared on
    # resume. Left empty until the trust check lands (a later increment).
    input_hash: str = ""


@dataclass
class Checkpoint:
    """A restored pair: the engine-state PATH and the loaded ledger (§13.2).

    ``engine_state`` is the path the pull hands to ``read_restart``; the
    ledger is already parsed. The pair is only ever built by
    :func:`load_checkpoint`, which returns ``None`` unless both halves are
    on disk.
    """

    engine_state: str
    ledger: Ledger


def write_checkpoint(engine: Engine, ledger: Ledger,
                     checkpoint_dir: str) -> None:
    """Write the pair TOGETHER, so a kill mid-write leaves no half (§13.2).

    Each half is written to a temporary name and then RENAMED into place;
    the rename is atomic, so the pair becomes visible only once both parts
    are fully on disk. The ledger's ``saved_step`` is stamped from the
    engine here, so it always matches the state just written.
    """
    os.makedirs(checkpoint_dir, exist_ok=True)
    ledger.saved_step = engine.step()

    engine_final = os.path.join(checkpoint_dir, _ENGINE_STATE_NAME)
    ledger_final = os.path.join(checkpoint_dir, _LEDGER_NAME)
    engine_temp = engine_final + ".tmp"
    ledger_temp = ledger_final + ".tmp"

    engine.write_restart(engine_temp)
    with open(ledger_temp, "w", encoding="utf-8") as ledger_file:
        json.dump(asdict(ledger), ledger_file)
    # os.replace is atomic on POSIX, so a reader never sees a partial
    # file. The ORDER of the two renames matters: the LEDGER is made
    # durable before the engine state, so a kill landing between them
    # leaves the ledger AHEAD of the engine, never behind. That direction
    # is the recoverable one — :func:`reconcile` can trim a ledger down to
    # the restored step, but could not fill a gap if the engine were ahead
    # of the ledger (§13.2). The worst case is thus resuming from the
    # previous complete checkpoint, never a corrupted one.
    os.replace(ledger_temp, ledger_final)
    os.replace(engine_temp, engine_final)


def load_checkpoint(checkpoint_dir: str) -> Checkpoint | None:
    """Read the pair back, or report none if it is absent or half-present.

    A checkpoint EXISTS only when BOTH parts are on disk; a lone restart
    or a lone ledger is treated as no checkpoint at all, so the pair
    discipline of §13.2 never restores from half a pair.
    """
    engine_state = os.path.join(checkpoint_dir, _ENGINE_STATE_NAME)
    ledger_path = os.path.join(checkpoint_dir, _LEDGER_NAME)
    if not (os.path.exists(engine_state) and os.path.exists(ledger_path)):
        return None
    with open(ledger_path, encoding="utf-8") as ledger_file:
        ledger = Ledger(**json.load(ledger_file))
    return Checkpoint(engine_state=engine_state, ledger=ledger)


def reconcile(ledger: Ledger, restored_step: int) -> Ledger:
    """Trim the ledger to the saved engine step, dropping any overhang.

    The ledger is appended every burst but the engine is saved on a
    COARSER cadence, so a resume may find a ledger that runs a few bursts
    PAST the last saved state. Every sample taken beyond ``restored_step``
    is dropped, so the record and the restored atoms agree before the run
    goes on (§13.2). Keying each sample to its engine step is exactly what
    makes this trim well-defined.
    """
    keep = [index for index, step in enumerate(ledger.sample_steps)
            if step <= restored_step]

    def _kept(series: list) -> list:
        return [series[index] for index in keep]

    return Ledger(
        sample_steps=_kept(ledger.sample_steps),
        displacement=_kept(ledger.displacement),
        force=_kept(ledger.force),
        opening=_kept(ledger.opening),
        bridges=_kept(ledger.bridges),
        starting_atom_count=ledger.starting_atom_count,
        saved_step=restored_step,
        input_hash=ledger.input_hash)
