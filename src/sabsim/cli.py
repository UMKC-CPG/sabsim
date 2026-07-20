"""The ``sabsim`` command — the project's front door (ARCHITECTURE.md §4).

One entry point to run a surface-activated-bonding study end to end, so a
run is a single supported command instead of a hand-written driver. It runs
INSIDE an allocation you provide (wrap it in ``srun``); it does not submit
its own job. Two ways to invoke it:

    srun --jobid=<ID> -n 1 python -m sabsim run [spec]     # a real run
    python -m sabsim run [spec] --dry-run                  # a login check

(and simply ``sabsim run ...`` once the package is installed, e.g. ``pip
install -e . --no-deps``, which registers the console command.)

The study specification is POSITIONAL and OPTIONAL, defaulting to
``sabsim.toml`` in the current directory; the run's home IS the current
directory. To run somewhere else you make that directory, ``cd`` into it,
and put a ``sabsim.toml`` there — the run's location is where you launch it,
never a guessed path (VISION.md principle 1). Outputs land under that
directory's scratch mirror (§4.2).

The run/restart/refresh/test operations are FLAGS on ``run``, not separate
verbs. v1 ships ``--dry-run`` (the login-node stub run) and ``--only`` (a
member subset); ``--resume`` (reuse finished intermediates) and
``--refresh`` (recompute clean) land next, with reuse-by-default the
intended policy once the stages learn to skip finished work.
"""

from __future__ import annotations

import argparse
import os
import sys

from sabsim.pipeline.skeleton_stages import W0_STAGES


def _build_parser() -> argparse.ArgumentParser:
    """Assemble the ``sabsim`` argument parser (one verb so far: run)."""
    parser = argparse.ArgumentParser(
        prog="sabsim",
        description="Run a surface-activated-bonding study end to end.")
    subcommands = parser.add_subparsers(dest="command")

    run = subcommands.add_parser(
        "run",
        help="run a study: build -> amorphize -> assemble -> press -> "
             "pull -> measure")
    run.add_argument(
        "spec", nargs="?", default="sabsim.toml",
        help="the study specification (default: sabsim.toml here)")
    run.add_argument(
        "--dry-run", action="store_true",
        help="run the placeholder stages on the login node — validate the "
             "spec and exercise the whole control flow with no "
             "supercomputer and no real physics")
    run.add_argument(
        "--only", action="append", metavar="MEMBER",
        help="run only this member (repeatable); default is every member")
    return parser


def _run(args: argparse.Namespace) -> int:
    """Execute ``sabsim run``: pick the stage set, run the study, report."""
    from sabsim.pipeline.sequencer import exec_full_study

    if not os.path.isfile(args.spec):
        print(f"sabsim: no study spec at '{args.spec}' — give a path, or "
              f"put a sabsim.toml in this directory", file=sys.stderr)
        return 2

    # The run's home is where it was launched (decision: CWD, not a flag).
    job_directory = os.getcwd()

    if args.dry_run:
        stage_set, comm = W0_STAGES, None
    else:
        guard = _refuse_live_off_allocation()
        if guard is not None:
            return guard
        from mpi4py import MPI
        from sabsim.pipeline.live_stages import LIVE_STAGES
        comm = MPI.COMM_WORLD
        if comm.Get_size() > 1:
            print("sabsim: multi-rank runs are not supported yet (the "
                  "stages do not coordinate file writes across ranks); "
                  "launch with 'srun -n 1'.", file=sys.stderr)
            return 2
        stage_set = LIVE_STAGES

    try:
        report = exec_full_study(
            args.spec, job_directory, stage_set, comm, only=args.only)
    except Exception as failure:                       # noqa: BLE001
        # A run that halts (a broken contract, an unresolved spec) reports
        # WHY and exits non-zero, rather than a raw traceback the user must
        # decode (DESIGN.md §5.7, gate-don't-warn made user-facing).
        print(f"sabsim: run halted — {failure}", file=sys.stderr)
        return 1

    _print_summary(report, dry_run=args.dry_run)
    return 0


def _refuse_live_off_allocation() -> int | None:
    """Refuse a real run that is not inside an ``srun`` step.

    A real run opens LAMMPS, which MUST NOT be spawned from the login node.
    ``srun`` sets ``SLURM_PROCID`` for each task, so its absence means we
    are not inside a job step; refuse and point at ``--dry-run``. Returns
    an exit code to stop on, or None to proceed.
    """
    if os.environ.get("SLURM_PROCID") is None:
        print("sabsim: a real run must be launched inside an allocation "
              "via srun (LAMMPS must not run on the login node). Use "
              "'srun --jobid=<ID> -n 1 ... run', or '--dry-run' for a "
              "login-node control-flow check.", file=sys.stderr)
        return 2
    return None


def _print_summary(report, dry_run: bool) -> None:
    """Print a concise per-member summary of the finished study."""
    mode = ("DRY RUN — placeholder stages, no physics"
            if dry_run else "run")
    print(f"\nsabsim {mode}: study '{report.study_name}'")
    for result in report.member_results:
        trust = "trusted" if result.trusted else "UNTRUSTED"
        print(f"  member '{result.specification.name}' [{trust}]")
        for measure in result.measures.measures:
            value = ("unresolved" if measure.value is None
                     else f"{measure.value:.4g} {measure.unit_native}")
            print(f"      {measure.name}: {value} ({measure.status.value})")
    for outcome in report.relation_outcomes:
        value = ("unresolved" if outcome.value is None
                 else f"{outcome.value:.4g}")
        print(f"  relation {outcome.kind} {list(outcome.members)}: {value}")


def main(argv=None) -> int:
    """The ``sabsim`` console entry point; returns a process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command != "run":
        parser.print_help()
        return 2
    return _run(args)
