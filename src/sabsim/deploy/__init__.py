"""Deployment separation — the "where to run" half (ARCHITECTURE §2.3).

`VISION.md` principle 1 splits "what to run" (materials, precision,
snapshot counts — the project file) from "where to run" (which cluster,
which filesystem, node counts, walltime). This package is the second
half: the machine-local facts a project must never carry, so the SAME
project runs on another cluster by changing the deployment and nothing
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
    Memory,
    Partition,
    UsageBlock,
    load_deployment,
)
from sabsim.deploy.registry import (
    ACTIVATED_HALF,
    ASSEMBLED_PAIR,
    JOB_NAMES,
    JOB_REGISTRY,
    MEASURE_VECTOR,
    PULL_RESULTS,
    JobKind,
    jobs_depending_on,
    registry_lookup,
)
from sabsim.deploy.roots import (
    LocationRoots,
    resolve_location_roots,
)
from sabsim.deploy.init_project import InitError, InitReport, init_project
from sabsim.deploy.prepare import (
    SubmissionEntry,
    prepare,
    render_job_script,
)

__all__ = [
    "DeploymentConfig",
    "DeploymentError",
    "Duration",
    "Memory",
    "Partition",
    "UsageBlock",
    "load_deployment",
    "ACTIVATED_HALF",
    "ASSEMBLED_PAIR",
    "JOB_NAMES",
    "JOB_REGISTRY",
    "MEASURE_VECTOR",
    "PULL_RESULTS",
    "JobKind",
    "jobs_depending_on",
    "registry_lookup",
    "LocationRoots",
    "resolve_location_roots",
    "InitError",
    "InitReport",
    "init_project",
    "SubmissionEntry",
    "prepare",
    "render_job_script",
]
