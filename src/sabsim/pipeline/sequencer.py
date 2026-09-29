"""The Tier-A sequencer: the top-level control flow (PSEUDOCODE.md §1).

This is ``exec_full_project`` and ``exec_one_pair`` made real. The
sequencer owns the eight pipeline steps and the (v1-open) quality-gate
loop, running the project's ONE pair to a self-standing report. Every
stage is routed through the ``run_to_contract`` guard, so the pipeline
advances only while each stage produces a contract-valid artifact and
HALTS loudly otherwise (ARCHITECTURE.md §4.1, §5.1).

Revised 2026-08-30: a project holds exactly one wafer pair and its work
falls into FOUR stage folders — ``prep_surf1_<a>/``, ``prep_surf2_<b>/``,
``bond_<a>_<b>/``, ``analysis_<a>_<b>/`` — each mirrored under
``intermediate/`` for the bulky files (ARCHITECTURE.md §1). The whole-chain
run below walks those same four stages in ONE process; the per-job run
selector (:mod:`sabsim.pipeline.pair_jobs`) runs any one of them in a fresh
process, reading the earlier stages' deliverables from their folders. Both
call the SAME stage functions here (:func:`prep_stage`, :func:`bond_stage`,
:func:`analysis_stage`), so the two entry points cannot drift apart. There
is no relation layer: a comparison between two pairs is the person's, made
from two projects' summaries (DESIGN.md §1.1).

In the walking skeleton (ARCHITECTURE.md §5, wave 0) the stage bodies
are stand-ins (:mod:`sabsim.pipeline.skeleton_stages`), so the number a
pair produces is plumbing, not physics — every ``PairResult`` is
stamped ``trusted=False``. What is REAL here is the control flow, the
contract guarding, the provenance stamp, and the machine-readable
emission; later waves deepen the stages behind these same seams.
"""

from __future__ import annotations

from dataclasses import replace

from sabsim.deploy.registry import (
    ACTIVATED_HALF,
    ASSEMBLED_PAIR,
    MEASURE_VECTOR,
    PULL_RESULTS,
)
from sabsim.deploy.scratch import (
    deliverable_directory,
    run_subfolder,
    stage_scratch,
)
from sabsim.pipeline.contracts import (
    ACTIVATED_HALF_CONTRACT,
    BOND_DEBOND_CONTRACT,
    DERIVED_LATTICES_CONTRACT,
    MEASURE_VECTOR_CONTRACT,
    SLABS_CONTRACT,
    STRUCTURE_CONTRACT,
    run_to_contract,
)
from sabsim.pipeline.exec_artifacts import (
    ActivatedSlabs,
    GateReport,
    PairResult,
    ProjectReport,
    Provenance,
    build_provenance,
)
from sabsim.pipeline.handoff import (
    check_shared_cells_agree,
    read_artifact,
    write_artifact,
)
from sabsim.pipeline.measures import MeasureVector, merge_measures
from sabsim.pipeline.skeleton_stages import W0_STAGES
from sabsim.spec.loader import load_and_validate_project
from sabsim.spec.records import (
    PairSpecification,
    StageFolders,
    stage_folders,
)
from sabsim.spec.references import check_project_references

# The wafer tags, inlined so this module stays free of the slab builder's
# pymatgen import (the authoritative constants are WAFER_A_TAG /
# WAFER_B_TAG in :mod:`sabsim.structure.slab_builder`).
_WAFER_A_TAG = 1
_WAFER_B_TAG = 2


def exec_full_project(
        project_specification, project_directory=None,
        stage_set=W0_STAGES, comm=None) -> ProjectReport:
    """Run a whole project: its one pair, end to end (§1).

    Loads and validates the project file, then walks the four stages in
    this one process. Returns the :class:`ProjectReport`; also emits the
    machine-readable record (DESIGN.md §6.6).

    ``project_directory`` is the project folder — normally left None so
    the folder the project file was read from is used (that is where
    the stage folders and both prep folders live, ARCHITECTURE.md §1);
    a test may point it elsewhere. Each stage's bulky intermediates go
    under ``intermediate/<stage folder>/run-<id>/`` and its deliverables
    into ``<project>/<stage folder>/``, both threaded EXPLICITLY into the
    stages that write files, so every written byte stays traceable to
    its inputs (VISION.md goal 3).

    ``stage_set`` chooses WHICH bodies run at each seam (ARCHITECTURE.md
    §5.1): the default ``W0_STAGES`` is the login-node walking skeleton
    (no LAMMPS); a real run passes ``LIVE_STAGES`` (from
    :mod:`sabsim.pipeline.live_stages`) and the MPI ``comm`` its engines
    use. The control flow and the contracts are identical either way.
    """
    project = load_and_validate_project(project_specification)
    if project_directory is None:
        project_directory = project.project_directory
    # Phase three (DESIGN.md §1.5): the file parsed and is executable in
    # principle — but does everything it POINTS AT actually exist? This
    # needs the filesystem rather than the file's text, which is why it
    # is separate from the loader, and it runs HERE because here is the
    # last moment before node-hours are spent. The skeleton never opens
    # the §3.5 gate, so only a live stage set is held to the environment
    # libraries (DESIGN §3.5).
    check_project_references(
        project,
        libraries_needed=(() if stage_set is W0_STAGES
                          else ("wafer_a", "wafer_b")))

    result = exec_one_pair(
        project.pair, project_directory, stage_folders(project.pair),
        stage_set, comm)
    report = ProjectReport(
        description=project.description,
        pair_label=project.pair.pair_label,
        result=result)
    emit_project(report)
    return report


def exec_one_pair(
        pair: PairSpecification,
        project_directory,
        folders: StageFolders,
        stage_set=W0_STAGES,
        comm=None) -> PairResult:
    """Run the four stages for ONE pair, in this process (PSEUDOCODE §1).

    Prepare surface 1, prepare surface 2, bond, analyse — the same four
    functions the per-job selector runs one at a time, here in order.
    Each hands the next its deliverable THROUGH ITS FOLDER, exactly as
    separately submitted jobs would, so a chain that completes here has
    exercised every file hand-off (ARCHITECTURE.md §4.3). In v1 the
    quality-gate loop executes its body ONCE and reports (VISION
    principle 5); the closed loop is a future target, so it is not
    iterated here.
    """
    prep_stage(pair, _WAFER_A_TAG, project_directory, folders,
               stage_set, comm)
    prep_stage(pair, _WAFER_B_TAG, project_directory, folders,
               stage_set, comm)
    bond_stage(pair, project_directory, folders, stage_set, comm)
    result = analysis_stage(
        pair, project_directory, folders, stage_set, comm)
    emit_pair(result)
    return result


# ---------------------------------------------------------------------
# The four stages. Each takes the pair, the project folder, and the four
# folder names; works in a FRESH run subfolder of its stage's scratch
# mirror; and leaves its deliverable in its stage folder in the project
# (ARCHITECTURE.md §1, DESIGN.md §10.8). A stage reads what it needs
# from the EARLIER stages' deliverable folders, never from memory.
# ---------------------------------------------------------------------

def _stage_directories(project_directory, stage_folder: str) -> tuple:
    """The (working, deliverables) directories for one stage's run."""
    working = run_subfolder(stage_scratch(project_directory, stage_folder))
    deliverables = deliverable_directory(project_directory, stage_folder)
    return str(working), str(deliverables), working.name


def prep_stage(
        pair: PairSpecification,
        wafer_tag: int,
        project_directory,
        folders: StageFolders,
        stage_set=W0_STAGES,
        comm=None) -> str:
    """Prepare ONE surface: build its half, activate, heal, gate (§10.2).

    Derives the working lattices for BOTH materials (the shared cell
    needs both, §2.2), builds both halves' geometry in that shared cell
    (cheap, deterministic — the other half's file is simply not used),
    then activates ONLY this surface's half and writes it as the
    ACTIVATED_HALF deliverable into its prep folder. Returns the
    deliverable folder's path. ``wafer_tag`` says which surface: bottom
    A (surface 1) or top B (surface 2).
    """
    stage_folder = (folders.prep_surf1 if wafer_tag == _WAFER_A_TAG
                    else folders.prep_surf2)
    working, deliverables, run_id = _stage_directories(
        project_directory, stage_folder)

    # Step 2b: the model-relaxed working lattice per material (§2.2).
    # The whole chain and every per-job path MUST run it before build,
    # or build receives a directory in the DerivedLattices slot (the
    # regression when step 2b was wired, commit cf92d30).
    derived_lattices = run_to_contract(
        lambda: stage_set.derive_lattices(pair, working, comm),
        DERIVED_LATTICES_CONTRACT)
    handle_a, handle_b, shared = run_to_contract(
        lambda: stage_set.build(pair, derived_lattices, working, comm),
        SLABS_CONTRACT)
    handle = handle_a if wafer_tag == _WAFER_A_TAG else handle_b

    # The verdict is printed BEFORE the contract judges it, so a halted
    # job's log still shows every metric, not only the one the halt
    # message names (2026-08-28, job 16843986).
    def _activate_and_report():
        half = stage_set.activate_surface(
            handle, shared, pair, working, comm)
        half = replace(half, run_id=run_id)
        if comm is None or comm.Get_rank() == 0:
            _report_activation(pair.pair_label, half)
        return half
    half = run_to_contract(_activate_and_report, ACTIVATED_HALF_CONTRACT)
    _publish(comm, lambda: write_artifact(deliverables, ACTIVATED_HALF,
                                          half))
    return deliverables


def bond_stage(
        pair: PairSpecification,
        project_directory,
        folders: StageFolders,
        stage_set=W0_STAGES,
        comm=None) -> str:
    """Read both halves, check they match, assemble, press, pull (§10.2).

    Reads the two ACTIVATED_HALF deliverables from the prep folders,
    REFUSES them if they were not built in the same shared cell, stacks
    them at the press-start opening, and runs the press, settle, and
    pull ladder. Leaves the assembled pair and the PULL_RESULTS in the
    bond folder for analysis; the dumps and logs stay under the run's
    scratch subfolder. Returns the deliverable folder's path.
    """
    working, deliverables, run_id = _stage_directories(
        project_directory, folders.bond)
    half_a = read_artifact(
        deliverable_directory(project_directory, folders.prep_surf1),
        ACTIVATED_HALF)
    half_b = read_artifact(
        deliverable_directory(project_directory, folders.prep_surf2),
        ACTIVATED_HALF)
    check_shared_cells_agree(half_a, half_b)
    activated = ActivatedSlabs(
        slab_a=half_a.slab, slab_b=half_b.slab,
        verdict_a=half_a.verdict, verdict_b=half_b.verdict)

    # Assembly reads both healed halves back and stacks them (§2.6).
    structure = run_to_contract(
        lambda: stage_set.assemble(
            activated, half_a.shared, pair, working, comm),
        STRUCTURE_CONTRACT)
    if structure.built is not None:
        # A real pair is handed on through its folder; the W0 placeholder
        # has no geometry to write, and analysis re-reads nothing then.
        _publish(comm, lambda: write_artifact(
            deliverables, ASSEMBLED_PAIR, structure))

    # Steps 6-7: press then pull, over the rate ladder (§9.1).
    bond_debond = run_to_contract(
        lambda: stage_set.bond_debond(structure, pair, working, comm),
        BOND_DEBOND_CONTRACT)
    bond_debond = replace(bond_debond, run_id=run_id)
    _publish(comm, lambda: write_artifact(
        deliverables, PULL_RESULTS, bond_debond))
    if comm is None or comm.Get_rank() == 0:
        _report_bond(pair.pair_label, bond_debond)
    return deliverables


def analysis_stage(
        pair: PairSpecification,
        project_directory,
        folders: StageFolders,
        stage_set=W0_STAGES,
        comm=None) -> PairResult:
    """Reduce the bond result to the measure vector (§6, §8).

    Reads the bond folder's deliverables — the pull results and, when
    the bond wrote one, the assembled pair (the measure needs the
    interface geometry the pull result does not carry) — runs the
    analyzer and the (mocked) characterization, and writes the
    MEASURE_VECTOR into the analysis folder: the terminal artifact of
    the chain. Returns the :class:`PairResult`.
    """
    _working, deliverables, _run_id = _stage_directories(
        project_directory, folders.analysis)
    bond_folder = deliverable_directory(project_directory, folders.bond)
    bond_debond = read_artifact(bond_folder, PULL_RESULTS)
    structure = _read_assembled_pair_if_present(bond_folder)

    measures = run_to_contract(
        lambda: stage_set.analyze(structure, bond_debond, pair),
        MEASURE_VECTOR_CONTRACT)
    characterization = run_to_contract(
        lambda: stage_set.characterize(structure, bond_debond, pair),
        MEASURE_VECTOR_CONTRACT)
    measures = merge_measures(measures, characterization)

    # The gate READS the measure vector and REPORTS; in v1 it never acts
    # and never edits a measure (DESIGN.md §7).
    gate = evaluate_pair_gates(measures, pair)
    result = PairResult(
        specification=pair,
        potential=build_provenance(pair),
        measures=measures,
        gate=gate,
        trusted=False)              # walking-skeleton plumbing (§5.3)
    _publish(comm, lambda: write_artifact(
        deliverables, MEASURE_VECTOR, result))
    return result


def _read_assembled_pair_if_present(bond_folder):
    """The assembled pair from the bond folder, or a placeholder.

    A real bond leaves the pair's artifact behind (its geometry is what
    the measure divides by); a W0 run writes none, so the analyzer stub
    gets a placeholder :class:`Structure` and ignores it.
    """
    from sabsim.pipeline.exec_artifacts import Structure
    from sabsim.pipeline.handoff import HandoffError
    try:
        return read_artifact(bond_folder, ASSEMBLED_PAIR)
    except HandoffError:
        return Structure(
            note="no assembled pair on disk (placeholder)",
            labeled_groups=("interface_z",))


def evaluate_pair_gates(
        measures: MeasureVector,
        pair: PairSpecification) -> GateReport:
    """Read the measure vector and report a verdict (DESIGN.md §7).

    In wave 0 the live gate and its five-way diagnosis (§7.7) are not
    built yet, so this collects the measure names it saw and states
    plainly that the result is untrusted skeleton plumbing. The gate
    judges ONE pair; forming the ratio against a reference pair is the
    person's, from two projects (DESIGN.md §7.4, revised 2026-08-30).
    """
    measures_seen = tuple(
        measure.name for measure in measures.measures)
    return GateReport(
        summary=("wave 0 walking skeleton: measures collected, not "
                 "graded (the live §7 gate lands in wave 1); result is "
                 "untrusted."),
        acted=False,
        measures_seen=measures_seen)


# ---------------------------------------------------------------------
# What a job log states. Printed on one rank, before the contract judges
# the artifact, so a halted job still shows every number.
# ---------------------------------------------------------------------

def _report_activation(pair_label: str, half) -> None:
    """Print a prep job's gate verdict so the job log states it.

    The §3.5 gate verdict for the healed surface, with its measured skin
    depth and every metric's number against its threshold — where a
    reader of a prep job's output looks first.
    """
    role = "A (surface 1)" if half.wafer_tag == _WAFER_A_TAG else (
        "B (surface 2)")
    print(f"\nactivation verdict for pair '{pair_label}', "
          f"surface {role}:")
    verdict = half.verdict
    if verdict is None:
        print("  not gated")
        return
    state = "PASSED" if verdict.passed else "FAILED"
    print(f"  gate {state}, activated depth "
          f"{verdict.activated_depth:.1f} A"
          + (f" — {verdict.reason}" if verdict.reason else ""))
    for name, metric in verdict.per_metric.items():
        print(f"    {name:22s} measured={metric.measured} "
              f"threshold={metric.threshold} "
              f"{'ok' if metric.passed else 'FAIL'}")


def _report_bond(pair_label: str, bond_debond) -> None:
    """Print the bond job's outcome so the job log states it plainly.

    The press outcome, its stage ledger (the step each phase began at,
    §9.3), and each pull rung's note — the facts a reader wants from the
    job output without opening the manifest.
    """
    print(f"\nbond verdicts for pair '{pair_label}':")
    print(f"  press: bonded={bond_debond.press.bonded} — "
          f"{bond_debond.press.note}")
    ledger = bond_debond.press.stage_steps
    if ledger is not None:
        print(f"  stage ledger (MD steps): press_start="
              f"{ledger.press_start} contact={ledger.contact} "
              f"hold_end={ledger.hold_end} settle_start="
              f"{ledger.settle_start} settle_end={ledger.settle_end}")
    for pull in bond_debond.pulls:
        print(f"  pull {pull.rate_value:g} {pull.rate_unit}: {pull.note}")


def _publish(comm, write_action) -> None:
    """Run a WRITE on the primary rank, then publish it with a barrier.

    A hand-off artifact must be written by exactly ONE rank and be
    visible to every rank before any of them proceeds (the §4.1
    serial-IO discipline the live stages already follow). With no
    communicator (a W0 or single-process run) the write is plain. The
    read side needs no such guard — every rank reads the finished file
    for itself.
    """
    if comm is None:
        write_action()
        return
    if comm.Get_rank() == 0:
        write_action()
    comm.Barrier()


# ---------------------------------------------------------------------
# Machine-readable emission (DESIGN.md §6.6). to_record builds a plain,
# JSON-serializable view; emit_* are the emission seam. Persisting to
# the §4.1 file contract on the shared filesystem is a later-wave slice.
# ---------------------------------------------------------------------

def _measure_to_record(measure) -> dict:
    """Serialize one Measure to a plain dict (no bare numbers, §6.6)."""
    return {
        "name": measure.name,
        "value": measure.value,
        "uncertainty": measure.uncertainty,
        "realization_count": measure.realization_count,
        "unit_native": measure.unit_native,
        "unit_si": measure.unit_si,
        "fidelity": measure.fidelity,
        "method": measure.method,
        "status": measure.status.value,
    }


def _provenance_to_record(provenance: Provenance) -> dict:
    """Serialize the provenance stamp to a plain dict (§1.6)."""
    return {
        "potential_ref": provenance.potential_ref,
        "universal_model": provenance.universal_model,
        "production_weights": provenance.production_weights,
        "master_seed": provenance.master_seed,
        "protocol_fingerprint": provenance.protocol_fingerprint,
    }


def _verdicts_to_record(measures: MeasureVector) -> dict | None:
    """Serialize the vector's press Verdicts, or None if it carries none.

    The bond decision is read once by the §4 analyzer and rides the
    vector as its own field (not a measure), so it is emitted alongside
    the measures rather than folded into them.
    """
    verdicts = measures.verdicts
    if verdicts is None:
        return None
    return {
        "bonded": verdicts.bonded,
        "contact_quality": verdicts.contact_quality,
    }


def _pair_to_record(result: PairResult) -> dict:
    """Serialize one pair's result to a plain dict."""
    return {
        "pair": result.specification.pair_label,
        "trusted": result.trusted,
        "potential": _provenance_to_record(result.potential),
        "measures": [
            _measure_to_record(measure)
            for measure in result.measures.measures],
        "verdicts": _verdicts_to_record(result.measures),
        "gate": {
            "summary": result.gate.summary,
            "acted": result.gate.acted,
            "measures_seen": list(result.gate.measures_seen),
        },
    }


def to_record(report: ProjectReport) -> dict:
    """Build the project's machine-readable record (DESIGN.md §6.6)."""
    return {
        "project": report.description,
        "pair": report.pair_label,
        "result": _pair_to_record(report.result),
    }


def emit_pair(result: PairResult) -> dict:
    """Emit one pair's machine-readable record (the emission seam)."""
    return _pair_to_record(result)


def emit_project(report: ProjectReport) -> dict:
    """Emit the project's machine-readable record (the emission seam).

    Wave 0 returns the record; writing it to the §4.1 file contract on
    the shared filesystem is a later slice.
    """
    return to_record(report)
