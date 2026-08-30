"""Unit tests for the ordered job registry (sabsim.deploy.registry).

These pin the registry's job as the SINGLE source of truth for what the
pair jobs are, in what order they run, and which may run side by side
(PSEUDOCODE.md §14.2, DESIGN.md §10.3): four jobs in submission order —
two independent surface preparations, the bond, the analysis — each
owning a contiguous sub-stage of the §1 chain, and, the property that
makes a mid-chain start possible, a file handoff where each job READS
exactly what an earlier job WROTE into a named stage folder
(ARCHITECTURE.md §4.3).
"""

from types import SimpleNamespace

import pytest

from sabsim.deploy import (
    ACTIVATED_HALF,
    JOB_NAMES,
    JOB_REGISTRY,
    MEASURE_VECTOR,
    PULL_RESULTS,
    JobKind,
    jobs_depending_on,
    registry_lookup,
)
from sabsim.deploy.registry import (
    ANALYSIS_FOLDER,
    BOND_FOLDER,
    PREP_SURF1_FOLDER,
    PREP_SURF2_FOLDER,
)


def test_four_jobs_in_submission_order():
    """The registry is prep_surf1, prep_surf2, bond, analysis (§10.2)."""
    assert JOB_NAMES == ("prep_surf1", "prep_surf2", "bond", "analysis")
    assert all(isinstance(job, JobKind) for job in JOB_REGISTRY)


def test_usage_keys_share_one_prep_block():
    """Both preps read [usage.prep]; the others read their own name.

    The two surfaces want the same hardware, so the rc carries ONE prep
    block rather than two copies that could drift apart (§14.1).
    """
    by_name = {job.name: job for job in JOB_REGISTRY}
    assert by_name["prep_surf1"].usage_key == "prep"
    assert by_name["prep_surf2"].usage_key == "prep"
    assert by_name["bond"].usage_key == "bond"
    assert by_name["analysis"].usage_key == "analysis"


def test_resource_classes_match_the_design():
    """The preps and bond are GPU, analysis is CPU (DESIGN.md §10.2).

    The universal-MLIP cascade runs on the GPU, so each surface
    preparation is a GPU job; analysis (the M1 mechanical measure) is
    pure Python, so it stays CPU.
    """
    by_name = {job.name: job for job in JOB_REGISTRY}
    assert by_name["prep_surf1"].resource_class == "gpu"
    assert by_name["prep_surf2"].resource_class == "gpu"
    assert by_name["bond"].resource_class == "gpu"
    assert by_name["analysis"].resource_class == "cpu"


def test_the_two_preps_are_independent_and_bond_waits_for_both():
    """Dependencies encode the fan-out: preps first, bond after both.

    Empty ``depends_on`` on both preps is what lets the scheduler run
    them at once (ARCHITECTURE.md §4.3, Approach C through the files);
    bond names both, analysis names bond.
    """
    prep_1, prep_2, bond, analysis = JOB_REGISTRY
    assert prep_1.depends_on == ()
    assert prep_2.depends_on == ()
    assert set(bond.depends_on) == {"prep_surf1", "prep_surf2"}
    assert analysis.depends_on == ("bond",)


def test_the_handoff_chain_is_contiguous():
    """Each job reads exactly what an earlier job wrote (§4.3, §14.2).

    A prep job starts from the project file (reads nothing) and writes
    its activated half into ITS OWN folder; bond reads BOTH halves from
    the two prep folders; analysis reads bond's pull results.
    """
    prep_1, prep_2, bond, analysis = JOB_REGISTRY

    assert prep_1.reads == ()
    assert prep_1.writes == ACTIVATED_HALF
    assert prep_2.reads == ()
    assert prep_2.writes == ACTIVATED_HALF

    assert set(bond.reads) == {(PREP_SURF1_FOLDER, ACTIVATED_HALF),
                               (PREP_SURF2_FOLDER, ACTIVATED_HALF)}
    assert bond.writes == PULL_RESULTS

    assert analysis.reads == ((BOND_FOLDER, PULL_RESULTS),)
    assert analysis.writes == MEASURE_VECTOR     # last in the chain

    # State the contiguity as one invariant: every artifact a job reads
    # is written by a job it depends on, in that job's own folder — so a
    # future inserted job (§10.3) cannot silently break the handoff.
    by_name = {job.name: job for job in JOB_REGISTRY}
    for job in JOB_REGISTRY:
        for folder_key, artifact in job.reads:
            producers = [by_name[name] for name in job.depends_on
                         if by_name[name].folder_key == folder_key]
            assert producers, (
                f"{job.name} reads from {folder_key} but depends on no "
                f"job that fills it")
            assert all(producer.writes == artifact
                       for producer in producers)


def test_every_job_fills_its_own_stage_folder():
    """Each job names one of the four stage folders; the keys are distinct."""
    keys = [job.folder_key for job in JOB_REGISTRY]
    assert keys == [PREP_SURF1_FOLDER, PREP_SURF2_FOLDER,
                    BOND_FOLDER, ANALYSIS_FOLDER]
    assert len(set(keys)) == 4


def test_folder_resolves_to_the_pairs_folder_name():
    """``JobKind.folder`` reads the name off a StageFolders record.

    The registry never spells a folder name — the labels belong to the
    pair — so a stand-in record with the four attributes is all it needs.
    """
    folders = SimpleNamespace(
        prep_surf1="prep_surf1_si", prep_surf2="prep_surf2_sio2",
        bond="bond_si_sio2", analysis="analysis_si_sio2")
    by_name = {job.name: job for job in JOB_REGISTRY}
    assert by_name["prep_surf1"].folder(folders) == "prep_surf1_si"
    assert by_name["prep_surf2"].folder(folders) == "prep_surf2_sio2"
    assert by_name["bond"].folder(folders) == "bond_si_sio2"
    assert by_name["analysis"].folder(folders) == "analysis_si_sio2"


def test_run_flags_are_spelled_from_the_names():
    """The ``sabsim run`` flag is the job name with dashes (§10.4)."""
    assert [job.flag for job in JOB_REGISTRY] == [
        "--prep-surf1", "--prep-surf2", "--bond", "--analysis"]


def test_every_job_owns_a_nonempty_sub_stage():
    """Each job's sub-stage runs at least one stage of the §1 chain."""
    for job in JOB_REGISTRY:
        assert job.stages, f"job '{job.name}' owns no stages"


def test_artifact_names_are_distinct():
    """The handoff artifact names do not collide."""
    names = {ACTIVATED_HALF, PULL_RESULTS, MEASURE_VECTOR}
    assert len(names) == 3


def test_registry_lookup_finds_a_job():
    """Looking up a valid job name returns its JobKind."""
    bond = registry_lookup("bond")
    assert bond.name == "bond"
    assert bond.writes == PULL_RESULTS


def test_registry_lookup_rejects_an_unknown_name():
    """An unknown job flag is a loud stop listing the valid names."""
    with pytest.raises(KeyError, match="prep_surf1"):
        registry_lookup("activate")


def test_jobs_depending_on_reads_the_successors_off_the_table():
    """The "submit next" hint follows the dependency lists (§10.3)."""
    assert [job.name for job in jobs_depending_on("prep_surf1")] == ["bond"]
    assert [job.name for job in jobs_depending_on("bond")] == ["analysis"]
    assert jobs_depending_on("analysis") == ()
