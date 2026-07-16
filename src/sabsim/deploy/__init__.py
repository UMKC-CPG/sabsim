"""Deployment separation — the "where to run" half (ARCHITECTURE §2.3).

`VISION.md` principle 1 splits "what to run" (materials, precision,
snapshot counts — the study spec) from "where to run" (which cluster,
which filesystem, node counts, walltime). This package is the second
half: the machine-local facts a study must never carry, so the SAME
study runs on another cluster by changing the deployment and nothing
else.

Today it holds the scratch mirror (:mod:`sabsim.deploy.scratch`). The
resource-class routing and the rc-file loader (§4.1) land here too.
"""
