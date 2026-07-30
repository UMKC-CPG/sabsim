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
member subset); ``--dump-visuals`` (record every dynamic stage for viewing) and
``--dump-stride``; ``--resume`` (reuse finished intermediates) and
``--refresh`` (recompute clean) land next, with reuse-by-default the
intended policy once the stages learn to skip finished work.
"""

from __future__ import annotations

import argparse
import os
import sys

from sabsim.pipeline.run_options import (
    TrajectoryOptions,
    set_trajectory_options,
)
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

    # The three per-kind member jobs (DESIGN.md §10.2, §14.3), mutually
    # exclusive: a run does ONE job's sub-stage of the chain, or — no
    # flag — the whole chain. store_const on one shared dest gives both
    # the exclusivity and a single job_flag value. These are the lines a
    # generated deployment script carries; the human submits activate,
    # then bond, then analyze, checking each before the next (§10.5).
    jobs = run.add_mutually_exclusive_group()
    jobs.add_argument(
        "--activate", dest="job_flag", action="store_const",
        const="activate",
        help="run only the activate job: build both wafers, roughen the "
             "surfaces, assemble the pair (CPU); writes the assembled pair")
    jobs.add_argument(
        "--bond", dest="job_flag", action="store_const", const="bond",
        help="run only the bond job: press, settle, and pull on the MLIP "
             "(GPU); reads the assembled pair, writes the pull results")
    jobs.add_argument(
        "--analyze", dest="job_flag", action="store_const",
        const="analyze",
        help="run only the analyze job: reduce the pull to the measure "
             "vector (CPU); reads the pull results, writes the measures")
    run.set_defaults(job_flag=None)
    run.add_argument(
        "--dump-visuals", action="store_true",
        help="record a trajectory for every dynamic stage — the "
             "bombardment and re-anneal of each half, the press and "
             "settle, and each pull rung — for viewing in Ovito. OFF by "
             "default: the frames cost wall clock inside the MD loop and "
             "the files are large (one pull rung ran to 1.3 GB)")
    run.add_argument(
        "--dump-stride", type=int, metavar="STEPS",
        help="record one frame per STEPS of MD, overriding the spec's "
             "frame_stride. Only meaningful with --dump-visuals; raise it "
             "for smaller files, lower it for smoother playback")

    # `prepare` — the WRITER (DESIGN.md §10.1, PSEUDOCODE §14.4): reads the
    # study spec AND the machine-local deployment rc, and writes one
    # ready-to-submit script per (member, job) plus a submission guide. It
    # submits nothing; the human submits the scripts in order.
    prepare = subcommands.add_parser(
        "prepare",
        help="write ready-to-submit scripts for a study (submits nothing)")
    prepare.add_argument(
        "spec", nargs="?", default="sabsim.toml",
        help="the study specification (default: sabsim.toml here)")
    prepare.add_argument(
        "--rc", metavar="PATH", default="deployment.toml",
        help="the machine-local deployment rc (default: deployment.toml "
             "here) — the [hardware]/[usage.*] file this cluster provides")
    return parser


def _run(args: argparse.Namespace) -> int:
    """Execute ``sabsim run``: pick the stage set, run the study, report."""
    from sabsim.pipeline.member_jobs import run as run_study

    if not os.path.isfile(args.spec):
        print(f"sabsim: no study spec at '{args.spec}' — give a path, or "
              f"put a sabsim.toml in this directory", file=sys.stderr)
        return 2

    # A job flag selects ONE sub-stage of the chain, for a compute-node
    # submission with real physics (§14.3). The whole-chain --dry-run is
    # the login-node control-flow check (§10.4); the two do not combine —
    # a single job cannot be exercised by the placeholder stages, whose
    # assembled pair has no built geometry to hand across a job boundary.
    if args.job_flag is not None and args.dry_run:
        print("sabsim: --dry-run runs the whole chain on the login node; "
              "it does not combine with --activate/--bond/--analyze, which "
              "are real per-job runs inside an allocation (§10.4). Drop "
              "the flag for a dry run, or drop --dry-run to run the job.",
              file=sys.stderr)
        return 2

    # The run's home is where it was launched (decision: CWD, not a flag).
    job_directory = os.getcwd()

    # Trajectory recording is an OPERATIONAL choice, not a physical one:
    # two runs differing only in it are the same study, so it is a flag
    # here rather than a field in the specification. Fixed once, before
    # any stage runs, because the stages are invoked through a generic
    # contract runner whose signatures cannot carry it (§4).
    set_trajectory_options(TrajectoryOptions(
        enabled=args.dump_visuals, stride=args.dump_stride))

    if args.dry_run:
        stage_set, comm = W0_STAGES, None
    else:
        guard = _refuse_live_off_allocation()
        if guard is not None:
            return guard
        from mpi4py import MPI
        from sabsim.pipeline.live_stages import LIVE_STAGES
        comm = MPI.COMM_WORLD
        # Multi-rank IS supported (enabled 2026-07-21). Every stage that
        # hands a file to the next one now writes it on a single rank and
        # publishes it with a barrier, and every library file call is
        # pinned to serial mode so no library turns a read into a hidden
        # collective (ARCHITECTURE.md §4.1, second discipline). LAMMPS
        # itself domain-decomposes across whatever ranks it is given.
        stage_set = LIVE_STAGES

    try:
        report = run_study(
            args.spec, job_directory, stage_set, comm,
            job_flag=args.job_flag, only=args.only)
    except Exception as failure:                       # noqa: BLE001
        # A run that halts (a broken contract, an unresolved spec) reports
        # WHY and exits non-zero, rather than a raw traceback the user must
        # decode (DESIGN.md §5.7, gate-don't-warn made user-facing).
        print(f"sabsim: run halted — {failure}", file=sys.stderr)
        return 1

    # Print the summary on ONE rank only. Under MPI every rank runs this
    # same code, so an unguarded print repeats the whole summary once per
    # rank (16 identical copies in a 16-rank run — as the deploy smoke's
    # log showed); rank 0 speaks for the job. A dry run has no comm and
    # prints normally.
    if comm is None or comm.Get_rank() == 0:
        if args.job_flag is not None:
            _print_job_summary(report)
        else:
            _print_summary(report, dry_run=args.dry_run)
    return 0


# Environment variables that mean "this process was started BY a parallel
# launcher", each set by a different one. Being launched by any of them is
# what distinguishes a compute-node task from a shell on the login node.
# SLURM_PROCID alone is NOT enough: it is set by `srun`, but the supported
# launcher here is `mpirun` (plain srun starts independent single-rank
# copies on this cluster, ARCHITECTURE.md §4.1), and OpenMPI starts ranks
# through its own daemons, which do not hand down SLURM_PROCID.
_LAUNCHER_RANK_VARIABLES = (
    "SLURM_PROCID",           # srun job step
    "OMPI_COMM_WORLD_RANK",   # OpenMPI mpirun — the launcher used here
    "PMI_RANK",               # MPICH / Intel MPI
    "PMIX_RANK",              # PMIx-based launchers
)


def _refuse_live_off_allocation() -> int | None:
    """Refuse a real run that is not inside a job step on a compute node.

    A real run opens LAMMPS, which MUST NOT be spawned on the login node.
    The test is whether a parallel launcher started this process: every
    launcher advertises the rank in its own variable, so any of them
    means we are a task inside an allocation rather than a shell.

    Deliberately NOT keyed on ``SLURM_JOB_ID``: that is set in an
    ``salloc`` shell too, and on this cluster such a shell still sits on
    the login node — so it would wave through exactly the case this
    guard exists to stop. Returns an exit code to stop on, or None.
    """
    launched_by = [name for name in _LAUNCHER_RANK_VARIABLES
                   if os.environ.get(name) is not None]
    if not launched_by:
        print("sabsim: a real run must be launched inside an allocation "
              "by a parallel launcher (LAMMPS must not run on the login "
              "node). Use 'mpirun -np <N> python -m sabsim run ...' from "
              "inside a job, or '--dry-run' for a login-node "
              "control-flow check.", file=sys.stderr)
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


def _print_job_summary(results) -> None:
    """Print what ONE per-kind job produced, and what to submit next.

    A per-job run is one checkpoint in the hand-driven submission sequence
    (DESIGN.md §10.2, §10.5), so the summary names the artifact each member
    wrote and — reinforcing the guided index — which job comes next in the
    registry order, or that the chain is complete.
    """
    from sabsim.deploy.registry import JOB_NAMES

    if not results:
        print("\nsabsim run: no members ran")
        return
    job_name = results[0].job_name
    position = JOB_NAMES.index(job_name)
    next_job = (JOB_NAMES[position + 1]
                if position + 1 < len(JOB_NAMES) else None)

    print(f"\nsabsim run: job '{job_name}' complete")
    for result in results:
        print(f"  member '{result.member_name}': wrote "
              f"{result.artifact_written}")
    if next_job is not None:
        print(f"  check the result, then submit the '{next_job}' job "
              f"(sabsim run --{next_job}).")
    else:
        print("  this was the last job in the chain; the measure vector "
              "is written.")


def _prepare(args: argparse.Namespace) -> int:
    """Execute ``sabsim prepare``: write the submission scripts + guide.

    Runs on the login node and submits nothing (DESIGN.md §10.1). The spec
    and the rc must both exist; the writer's own gates (an unset root, a
    walltime over its partition ceiling) stop with a readable message
    rather than a traceback (§10.5, §10.6).
    """
    from sabsim.deploy.prepare import GUIDE_FILENAME, prepare

    if not os.path.isfile(args.spec):
        print(f"sabsim: no study spec at '{args.spec}' — give a path, or "
              f"put a sabsim.toml in this directory", file=sys.stderr)
        return 2
    if not os.path.isfile(args.rc):
        print(f"sabsim: no deployment rc at '{args.rc}' — give one with "
              f"--rc, or put a deployment.toml in this directory",
              file=sys.stderr)
        return 2

    job_directory = os.getcwd()
    try:
        entries = prepare(args.spec, args.rc, job_directory)
    except Exception as failure:                       # noqa: BLE001
        # A gate failure (unset root, walltime over ceiling, bad rc) reports
        # WHY and exits non-zero, not a raw traceback (DESIGN.md §5.7).
        print(f"sabsim: prepare halted — {failure}", file=sys.stderr)
        return 1

    print(f"\nsabsim prepare: wrote {len(entries)} script(s) to "
          f"{job_directory}")
    for entry in entries:
        print(f"  {entry.script_name}")
    print(f"  submit in the order in {GUIDE_FILENAME}.")
    return 0


def main(argv=None) -> int:
    """The ``sabsim`` console entry point; returns a process exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return _run(args)
    if args.command == "prepare":
        return _prepare(args)
    parser.print_help()
    return 2
