"""The three location roots, resolved from the environment (§10.5, §4.1).

`VISION.md` principle 1 keeps "where to run" out of both the code and the
study spec; the three roots that anchor every path a run reads or writes
are set by a sourced shell rc (``.sabsim/sabsimrc``) UPSTREAM of Python,
because ``SABSIM_SHARE`` names the install itself and so cannot be found
through a config file the install would contain (`ARCHITECTURE.md` §4.1).

This module reads them back for ``sabsim prepare`` (`PSEUDOCODE.md` §14.4),
which BAKES them into each generated script as a FROZEN snapshot (§10.5):
the script records the exact locations it used, so it reproduces months
later without depending on the rc still existing or being unchanged.

The three, split by access pattern (`ARCHITECTURE.md` §4.1):

* ``SABSIM_SCRATCH`` — per-user, write-heavy, regenerable run output.
  REQUIRED.
* ``SABSIM_SHARE`` — group, read-mostly, authoritative: the install,
  source potentials, reference datasets. REQUIRED.
* ``SABSIM_LOCAL`` — a per-user OVERRIDE, a personal copy of anything
  otherwise found in ``SABSIM_SHARE``. OPTIONAL — its absence is normal
  ("no override"), not an error.

None is defaulted (`DESIGN.md` §1.4, principle 1): an unset REQUIRED root
is a loud stop the caller sees on the login node, never a guessed
fallback into somewhere plausible.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from sabsim.deploy.config import DeploymentError
from sabsim.deploy.scratch import SCRATCH_ROOT_VARIABLE

# The env-var names of the other two roots (SABSIM_SCRATCH's is reused
# from deploy.scratch, so the one variable is named in exactly one place).
SHARE_ROOT_VARIABLE = "SABSIM_SHARE"
LOCAL_ROOT_VARIABLE = "SABSIM_LOCAL"


@dataclass(frozen=True)
class LocationRoots:
    """The three resolved roots ``prepare`` bakes into each script (§10.5).

    ``scratch`` and ``share`` are always present (the required roots);
    ``local`` is ``None`` when no personal override is set. Each is stored
    as the CONFIGURED, expanded string (``~`` resolved) — NOT resolved
    through its mounts — the stable, human-readable form that belongs in a
    baked-in export line, the same choice :mod:`sabsim.deploy.scratch`
    makes for its links.
    """

    scratch: str
    share: str
    local: str | None


def resolve_location_roots() -> LocationRoots:
    """Read the three roots from the environment, or STOP (§14.4 gate).

    ``prepare`` runs on the login node, so a missing REQUIRED root is
    reported THERE, by name, rather than emitting a script that dies on a
    compute node an hour in (§10.5). ``SABSIM_LOCAL`` is optional (an
    override), so its absence returns ``None`` rather than raising.
    """
    scratch = _require_root(SCRATCH_ROOT_VARIABLE)
    share = _require_root(SHARE_ROOT_VARIABLE)
    local_raw = os.environ.get(LOCAL_ROOT_VARIABLE)
    local = str(Path(local_raw).expanduser()) if local_raw else None
    return LocationRoots(scratch=scratch, share=share, local=local)


def _require_root(variable: str) -> str:
    """Return the expanded value of a REQUIRED root, or a loud stop.

    An unset or empty required root cannot be guessed (principle 1), so it
    raises with a message that says which variable and how to set it —
    readable on the login node before any node-hours are spent.
    """
    value = os.environ.get(variable)
    if not value:
        raise DeploymentError(
            f"{variable} is not set. The three location roots are set by "
            f"the sourced .sabsim/sabsimrc upstream of Python "
            f"(ARCHITECTURE.md §4.1); there is no default, because 'where "
            f"to run' is stated, not guessed (VISION principle 1). Source "
            f"your sabsimrc before running `sabsim prepare`.")
    return str(Path(value).expanduser())
