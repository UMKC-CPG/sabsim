"""Deployment separation — the "where to run" half (ARCHITECTURE §2.3).

`VISION.md` principle 1 splits "what to run" (materials, precision,
snapshot counts — the study spec) from "where to run" (which cluster,
which filesystem, node counts, walltime). This package is the second
half: the machine-local facts a study must never carry, so the SAME
study runs on another cluster by changing the deployment and nothing
else.

It holds the scratch mirror (:mod:`sabsim.deploy.scratch`), the rc-file
loader (:mod:`sabsim.deploy.config`, PSEUDOCODE.md §14.1), and the one
ordered job registry both deployment commands read
(:mod:`sabsim.deploy.registry`, §14.2).
"""

from sabsim.deploy.config import (
    DeploymentConfig,
    DeploymentError,
    Duration,
    Partition,
    UsageBlock,
    load_deployment,
)
from sabsim.deploy.registry import (
    ASSEMBLED_PAIR,
    JOB_NAMES,
    JOB_REGISTRY,
    MEASURE_VECTOR,
    PULL_RESULTS,
    JobKind,
    registry_lookup,
)

__all__ = [
    "DeploymentConfig",
    "DeploymentError",
    "Duration",
    "Partition",
    "UsageBlock",
    "load_deployment",
    "ASSEMBLED_PAIR",
    "JOB_NAMES",
    "JOB_REGISTRY",
    "MEASURE_VECTOR",
    "PULL_RESULTS",
    "JobKind",
    "registry_lookup",
]
