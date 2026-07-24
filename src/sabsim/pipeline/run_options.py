"""Run-time options that are operational, not physical (ARCHITECTURE §4).

A study specification describes the PHYSICS of a run: which materials,
which beam energy, which pull speeds. It deliberately says nothing about
how the run is operated — how many processors, where scratch lives,
whether this particular invocation should keep visual output. Those are
properties of the invocation, not of the science, and two runs that
differ only in them must still be the same study.

This module holds that second kind of setting. It exists because the
pipeline stages are invoked through a generic contract runner with fixed
signatures (`sequencer.run_to_contract`), so an operational choice made
at the command line cannot simply be threaded through as an argument
without distorting every stage's interface. Instead the front door sets
it once, before any stage runs, and the stages read it.

The one option so far is trajectory recording. It is OFF by default
because it is expensive in both directions: writing a frame costs wall
clock in the middle of a hot MD loop, and the files are large — a
single pull rung produced 1.3 GB before this was made optional. A run
that nobody intends to watch should not pay for frames nobody will open.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TrajectoryOptions:
    """Whether this invocation records trajectories, and how densely.

    ``enabled`` gates every dynamic stage's dump. ``stride`` is how many
    MD steps pass between recorded frames; ``None`` means defer to the
    specification's ``frame_stride``, so the spec stays the default and
    the command line is an override rather than a replacement.
    """

    enabled: bool = False
    stride: int | None = None

    def stride_or(self, spec_stride: int) -> int:
        """The stride to use, preferring an explicit override."""
        return self.stride if self.stride is not None else spec_stride


# The current invocation's options. Module state is the honest shape for
# this: it is set exactly once, by the front door, before any stage runs,
# and it describes the process rather than any object inside it.
_CURRENT = TrajectoryOptions()


def set_trajectory_options(options: TrajectoryOptions) -> None:
    """Fix this invocation's trajectory policy (called by the CLI)."""
    global _CURRENT
    _CURRENT = options


def trajectory_options() -> TrajectoryOptions:
    """The trajectory policy in force for this invocation."""
    return _CURRENT


def reset_trajectory_options() -> None:
    """Restore the default (off). Used by tests to stay isolated."""
    global _CURRENT
    _CURRENT = TrajectoryOptions()
