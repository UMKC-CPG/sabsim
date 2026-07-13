"""The Tier-A pipeline: sequencer, contracts, and the run's artifacts.

This subpackage runs a validated study through the eight-step pipeline
(PSEUDOCODE.md §1). ``exec_full_study`` is the entry point; every stage
is routed through the ``run_to_contract`` guard, and the records the run
produces live in :mod:`sabsim.pipeline.exec_artifacts`.
"""

from sabsim.pipeline.contracts import (
    PipelineHalt,
    run_to_contract,
)
from sabsim.pipeline.exec_artifacts import (
    MemberResult,
    StudyReport,
)
from sabsim.pipeline.sequencer import (
    exec_full_study,
    exec_one_member,
    to_record,
)

__all__ = [
    "PipelineHalt",
    "run_to_contract",
    "MemberResult",
    "StudyReport",
    "exec_full_study",
    "exec_one_member",
    "to_record",
]
