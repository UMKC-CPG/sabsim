"""Unit tests for the ordered job registry (sabsim.deploy.registry).

These pin the registry's job as the SINGLE source of truth for what the
member jobs are and in what order they run (PSEUDOCODE.md §14.2,
DESIGN.md §10.3): three jobs in submission order, each owning a
contiguous slice of the §1 chain, and — the property that makes a
mid-chain start possible — a file handoff where each job READS exactly
what the previous job WROTE (ARCHITECTURE.md §4.3).
"""

import pytest

from sabsim.deploy import (
    ASSEMBLED_PAIR,
    JOB_NAMES,
    JOB_REGISTRY,
    MEASURE_VECTOR,
    PULL_RESULTS,
    JobKind,
    registry_lookup,
)
from sabsim.deploy.registry import FROM_SPEC


def test_three_jobs_in_submission_order():
    """The registry is activate → bond → analyze, in that order (§10.2)."""
    assert JOB_NAMES == ("activate", "bond", "analyze")
    assert all(isinstance(job, JobKind) for job in JOB_REGISTRY)


def test_resource_classes_match_the_design():
    """activate and analyze are CPU, bond is GPU (DESIGN.md §10.2)."""
    by_name = {job.name: job for job in JOB_REGISTRY}
    assert by_name["activate"].resource_class == "cpu"
    assert by_name["bond"].resource_class == "gpu"
    assert by_name["analyze"].resource_class == "cpu"


def test_the_handoff_chain_is_contiguous():
    """Each job reads exactly what the previous job wrote (§4.3, §14.2).

    This is the property the whole mid-chain-start design rests on: the
    activate job starts from the spec, and from there each job's entry
    artifact is the prior job's exit artifact, with no gap.
    """
    activate, bond, analyze = JOB_REGISTRY

    assert activate.reads is FROM_SPEC          # starts from the spec
    assert activate.writes == ASSEMBLED_PAIR

    assert bond.reads == ASSEMBLED_PAIR         # == activate.writes
    assert bond.writes == PULL_RESULTS

    assert analyze.reads == PULL_RESULTS        # == bond.writes
    assert analyze.writes == MEASURE_VECTOR     # last in the chain

    # State the contiguity as one invariant, so a future inserted job
    # (a relax between activate and bond, §10.3) cannot silently break it.
    for earlier, later in zip(JOB_REGISTRY, JOB_REGISTRY[1:]):
        assert later.reads == earlier.writes


def test_every_job_owns_a_nonempty_slice():
    """Each job runs at least one stage of the §1 chain."""
    for job in JOB_REGISTRY:
        assert job.stages, f"job '{job.name}' owns no stages"


def test_artifact_names_are_distinct():
    """The three handoff artifact names do not collide."""
    names = {ASSEMBLED_PAIR, PULL_RESULTS, MEASURE_VECTOR}
    assert len(names) == 3


def test_registry_lookup_finds_a_job():
    """Looking up a valid job name returns its JobKind."""
    bond = registry_lookup("bond")
    assert bond.name == "bond"
    assert bond.writes == PULL_RESULTS


def test_registry_lookup_rejects_an_unknown_name():
    """An unknown job flag is a loud stop listing the valid names."""
    with pytest.raises(KeyError, match="activate"):
        registry_lookup("nonesuch")
