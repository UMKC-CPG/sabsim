"""The ``sabsim`` command — the project's front door (ARCHITECTURE.md §4).

One entry point to run a surface-activated-bonding project end to end, so a
run is a single supported command instead of a hand-written driver. It runs
INSIDE an allocation you provide (wrap it in ``srun``); it does not submit
its own job. Two ways to invoke it:

    srun --jobid=<ID> -n 1 python -m sabsim run [spec]     # a real run
    python -m sabsim run [spec] --dry-run                  # a login check

(and simply ``sabsim run ...`` once the package is installed, e.g. ``pip
install -e . --no-deps``, which registers the console command.)

The project file is POSITIONAL and OPTIONAL, defaulting to
``sabsim.toml`` in the current directory; the run's home IS the current
directory. To run somewhere else you make that directory, ``cd`` into it,
and put a ``sabsim.toml`` there — the run's location is where you launch it,
never a guessed path (VISION.md principle 1). Outputs land under that
directory's scratch mirror (§4.2).

``sabsim setup`` and ``sabsim init [folder]`` come before all of that:
the first checks the install and writes the shell rc (DESIGN.md §10.10),
the second writes a project folder from the tracked templates (§10.9).
Neither overwrites anything.

The run/restart/refresh/test operations are FLAGS on ``run``, not separate
verbs. v1 ships ``--dry-run`` (the login-node stub run) and the four
job flags; ``--dump-visuals`` (record every dynamic stage for viewing) and
``--dump-stride``; ``--resume`` (reuse finished intermediates) and
``--refresh`` (recompute clean) land next, with reuse-by-default the
intended policy once the stages learn to skip finished work.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

from sabsim.pipeline.run_options import (
    TrajectoryOptions,
    set_trajectory_options,
)
from sabsim.pipeline.skeleton_stages import W0_STAGES


def _build_parser() -> argparse.ArgumentParser:
    """Assemble the ``sabsim`` argument parser (one verb so far: run)."""
    parser = argparse.ArgumentParser(
        prog="sabsim",
        description="Run a surface-activated-bonding project — one wafer "
                    "pair — end to end, or one of its four jobs.")
    subcommands = parser.add_subparsers(dest="command")

    run = subcommands.add_parser(
        "run",
        help="run a project: prepare each surface -> assemble -> press "
             "-> pull -> measure")
    run.add_argument(
        "spec", nargs="?", default="sabsim.toml",
        help="the project file (default: sabsim.toml here); its folder "
             "is the project folder the stage folders live in")
    run.add_argument(
        "--dry-run", action="store_true",
        help="run the placeholder stages on the login node — validate the "
             "spec and exercise the whole control flow with no "
             "supercomputer and no real physics")

    # The four pair jobs (DESIGN.md §10.2, §14.3), mutually exclusive: a
    # run does ONE job's stage of the chain, or — no flag — the whole
    # chain. store_const on one shared dest gives both the exclusivity
    # and a single job_flag value. The flags are spelled from the job
    # registry (ONE source of the job set, §10.3): --prep-surf1,
    # --prep-surf2, --bond, --analysis. These are the lines a generated
    # deployment script carries; the human submits both preps, then
    # bond, then analysis, checking each before the next (§10.5).
    from sabsim.deploy.registry import JOB_REGISTRY
    jobs = run.add_mutually_exclusive_group()
    for job in JOB_REGISTRY:
        jobs.add_argument(
            job.flag, dest="job_flag", action="store_const",
            const=job.name,
            help=f"run only the {job.name} job ({job.resource_class}): "
                 f"{', '.join(job.stages)}; writes {job.writes} into "
                 f"the {job.folder_key} stage folder")
    run.set_defaults(job_flag=None)
    run.add_argument(
        "--dump-visuals", action=argparse.BooleanOptionalAction,
        default=True,
        help="record a trajectory for every dynamic stage — the "
             "bombardment of each half, the press and settle, and each "
             "pull rung — for viewing in Ovito. ON by default (the "
             "movie is how a run is verified); pass --no-dump-visuals "
             "to skip it when the frames' wall clock and size (a pull "
             "rung can reach 1.3 GB) are not wanted")
    run.add_argument(
        "--dump-stride", type=int, metavar="STEPS",
        help="record one frame per STEPS of MD, overriding the spec's "
             "frame_stride. Only meaningful with --dump-visuals; raise it "
             "for smaller files, lower it for smoother playback")

    # `setup` — the install CHECKED and the shell rc WRITTEN (DESIGN.md
    # §10.10, PSEUDOCODE §14.8). Builds nothing; never overwrites.
    setup = subcommands.add_parser(
        "setup",
        help="check each layer of the install (clone, conda, venv, share, "
             "engine, scratch) and write .sabsim/sabsimrc from the "
             "template if it is missing; builds nothing")
    setup.add_argument(
        "--scratch", metavar="PATH",
        help="the per-user scratch root (SABSIM_SCRATCH); default: the "
             "variable if set, else the template's worked example")
    setup.add_argument(
        "--share", metavar="PATH",
        help="the group install root (SABSIM_SHARE); default: the "
             "variable if set, else the template's worked example")
    setup.add_argument(
        "--venv", metavar="PATH",
        help="the venv the rc activates; default: the one running this "
             "command")

    # `init` — the GENERATOR (DESIGN.md §10.9, PSEUDOCODE §14.7): writes
    # a project folder from the tracked templates and never overwrites,
    # so it can be re-run after an edit to add what is still missing.
    init = subcommands.add_parser(
        "init",
        help="write a project folder (sabsim.toml, deployment.toml, the "
             "four stage folders, a recipe per surface) from the "
             "templates; never overwrites")
    init.add_argument(
        "project",
        help="the project folder to fill; made if missing")
    init.add_argument(
        "materials", nargs=2, metavar="LABEL",
        help="the pair to bond: two materials-catalog labels (wafer A "
             "is the bottom surface, wafer B the top), e.g. "
             "si_diamond_100 sio2_quartz_001; `sabsim catalog list` "
             "shows them")

    # `catalog` — the materials catalog (DESIGN.md §10.11, PSEUDOCODE
    # §14.9): one folder per crystal phase and face under share/catalog.
    catalog = subcommands.add_parser(
        "catalog",
        help="the materials catalog: list its entries, or add one from "
             "a crystal file")
    catalog_verbs = catalog.add_subparsers(dest="verb")
    listing = catalog_verbs.add_parser(
        "list", help="print the entries, one per line; a formula "
                     "narrows it to that chemistry")
    listing.add_argument("formula", nargs="?",
                         help="e.g. SiO2 — only this formula's entries")
    adding = catalog_verbs.add_parser(
        "add", help="make an entry from a crystal file (never "
                    "overwrites; names what is left to decide)")
    adding.add_argument(
        "label", nargs="?",
        help="optional CHECK: the label is derived and printed — "
             "<formula>_<phase>_<face>, lower-cased, e.g. "
             "sio2_cristobalite_100 — and one given here is refused "
             "if the values below do not give it")
    adding.add_argument("--cif", required=True, metavar="FILE",
                        help="the crystal file (from cod_fish, say)")
    adding.add_argument("--formula",
                        help="optional CHECK: the formula is read from "
                             "the crystal file, and one given here is "
                             "refused if the crystal is something else")
    adding.add_argument("--phase", required=True, metavar="NAME",
                        help="the phase name, e.g. cristobalite or "
                             "wurtzite — it becomes part of the label")
    adding.add_argument("--face", required=True, nargs=3, type=int,
                        metavar=("H", "K", "L"),
                        help="the bonding face's Miller indices")
    adding.add_argument("--cod-id", type=int, metavar="ID",
                        help="Crystallography Open Database id, if that "
                             "is where the file came from")
    adding.add_argument("--cod-revision", type=int, metavar="REV",
                        help="the COD revision fetched")
    adding.add_argument("--from", dest="source", metavar="LABEL",
                        help="the sibling to clone the recipe from; "
                             "it must be of the same formula (default: "
                             "the first of the same phase, else of the "
                             "same formula; a new chemistry is written "
                             "from the template)")

    # `prepare` — the WRITER (DESIGN.md §10.1, PSEUDOCODE §14.4): reads
    # the project file AND the machine-local deployment rc, and writes
    # one ready-to-submit script per job plus a submission guide. It
    # submits nothing; the human submits the scripts in order.
    prepare = subcommands.add_parser(
        "prepare",
        help="write ready-to-submit scripts for a project (submits "
             "nothing)")
    prepare.add_argument(
        "spec", nargs="?", default="sabsim.toml",
        help="the project file (default: sabsim.toml here)")
    prepare.add_argument(
        "--rc", metavar="PATH", default="deployment.toml",
        help="the machine-local deployment rc (default: deployment.toml "
             "here) — the [hardware]/[usage.*] file this cluster provides")
    prepare.add_argument(
        "--dump-visuals", action=argparse.BooleanOptionalAction,
        default=True,
        help="record a trajectory for every dynamic stage of every "
             "generated job (ON by default — a dynamic run leaves its "
             "movie behind); --no-dump-visuals writes scripts that skip it")
    bootstrap = subcommands.add_parser(
        "bootstrap",
        help="manufacture the production potential from a force-model "
             "recipe (DESIGN §4.8): generate -> label -> harvest")
    phases = bootstrap.add_subparsers(dest="phase")
    generate = phases.add_parser(
        "generate",
        help="build Collection 1 (needs a compute node for its dynamics) "
             "and harvest Collection 2 from the pair run the recipe "
             "names; writes structures.extxyz")
    generate.add_argument("recipe", help="the force-model recipe TOML")
    generate.add_argument(
        "--skip-collection1", action="store_true",
        help="harvest Collection 2 only (no dynamics; login-node safe)")
    generate.add_argument(
        "--skip-collection2", action="store_true",
        help="build Collection 1 only (no pair dumps needed)")
    generate.add_argument(
        "--overwrite-library", action="store_true",
        help="replace an environment library this folder already "
             "holds. Without it generate REFUSES and changes nothing: "
             "a surface prepared here was gated against that library")
    label_parser = phases.add_parser(
        "label",
        help="write one VASP directory per selected structure and ONE "
             "SLURM job array (submits nothing)")
    label_parser.add_argument("recipe", help="the force-model recipe TOML")
    label_parser.add_argument(
        "--rc", metavar="PATH", default="deployment.toml",
        help="the deployment rc whose [usage.label] block routes the array")
    harvest_parser = phases.add_parser(
        "harvest",
        help="read the finished VASP runs, drop the unconverged, write "
             "labels.extxyz")
    harvest_parser.add_argument("recipe", help="the force-model recipe TOML")
    return parser


def _bootstrap(args: argparse.Namespace) -> int:
    """Execute one ``sabsim bootstrap`` phase from the job home (CWD)."""
    from sabsim.bootstrap import command
    job_directory = os.getcwd()
    try:
        if args.phase == "generate":
            summary = command.generate(
                args.recipe, job_directory,
                collection1=not args.skip_collection1,
                collection2=not args.skip_collection2,
                overwrite_library=args.overwrite_library)
            print("sabsim bootstrap generate: structures per family")
            for family, count in sorted(summary.items()):
                print(f"  {family:20s} {count}")
            return 0
        if args.phase == "label":
            tasks, script = command.label(
                args.recipe, args.rc, job_directory)
            print(f"sabsim bootstrap label: {len(tasks)} VASP task(s); "
                  f"submit with: sbatch {script}")
            return 0
        if args.phase == "harvest":
            kept, dropped = command.harvest(args.recipe, job_directory)
            print(f"sabsim bootstrap harvest: {kept} label(s) kept, "
                  f"{len(dropped)} dropped")
            for directory, reason in dropped:
                print(f"  dropped {directory}: {reason}")
            return 0
    except Exception as failure:                       # noqa: BLE001
        print(f"sabsim: bootstrap halted — {failure}", file=sys.stderr)
        return 1
    print("sabsim bootstrap: give a phase — generate, label or harvest",
          file=sys.stderr)
    return 2


def _run(args: argparse.Namespace) -> int:
    """Execute ``sabsim run``: pick the stage set, run the project, report."""
    from sabsim.pipeline.pair_jobs import run as run_project

    if not os.path.isfile(args.spec):
        print(f"sabsim: no project file at '{args.spec}' — give a path, "
              f"or put a sabsim.toml in this directory", file=sys.stderr)
        return 2

    # A job flag selects ONE sub-stage of the chain, for a compute-node
    # submission with real physics (§14.3). The whole-chain --dry-run is
    # the login-node control-flow check (§10.4); the two do not combine —
    # a single job cannot be exercised by the placeholder stages, whose
    # assembled pair has no built geometry to hand across a job boundary.
    if args.job_flag is not None and args.dry_run:
        print("sabsim: --dry-run runs the whole chain on the login node; "
              "it does not combine with --prep-surf1/--prep-surf2/--bond/"
              "--analysis, which are real per-job runs inside an "
              "allocation (§10.4). Drop the flag for a dry run, or drop "
              "--dry-run to run the job.", file=sys.stderr)
        return 2

    # The run's home is the PROJECT FOLDER: the directory the project
    # file sits in, where its stage folders and prep folders live
    # (ARCHITECTURE.md §1, revised 2026-08-30). Not the CWD, so a run
    # launched from elsewhere still lands in the project.
    project_directory = os.path.dirname(os.path.abspath(args.spec))

    # Trajectory recording is an OPERATIONAL choice, not a physical one:
    # two runs differing only in it are the same project, so it is a flag
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
        report = run_project(
            args.spec, project_directory, stage_set, comm,
            job_flag=args.job_flag)
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
    """Print a concise summary of the finished project's one pair."""
    mode = ("DRY RUN — placeholder stages, no physics"
            if dry_run else "run")
    print(f"\nsabsim {mode}: project '{report.description}'")
    result = report.result
    trust = "trusted" if result.trusted else "UNTRUSTED"
    print(f"  pair '{report.pair_label}' [{trust}]")
    for measure in result.measures.measures:
        value = ("unresolved" if measure.value is None
                 else f"{measure.value:.4g} {measure.unit_native}")
        print(f"      {measure.name}: {value} ({measure.status.value})")


def _print_job_summary(result) -> None:
    """Print what ONE pair job produced, and what to submit next.

    A per-job run is one checkpoint in the hand-driven submission
    sequence (DESIGN.md §10.2, §10.5), so the summary names the
    deliverable the job wrote and — reinforcing the guide — which jobs
    wait on it in the registry's dependency graph, or that the chain is
    complete.
    """
    from sabsim.deploy.registry import jobs_depending_on

    print(f"\nsabsim run: job '{result.job_name}' complete")
    print(f"  pair '{result.pair_label}': wrote "
          f"{result.artifact_written} in {result.deliverable_directory}")
    followers = jobs_depending_on(result.job_name)
    if followers:
        names = ", ".join(f"'{job.name}' (sabsim run {job.flag})"
                          for job in followers)
        print(f"  check the result; once every job it waits on has "
              f"finished, submit: {names}.")
    else:
        print("  this was the last job in the chain; the measure vector "
              "is written.")


def _setup(args: argparse.Namespace) -> int:
    """Execute ``sabsim setup``: the checklist, then the rc (§10.10).

    Exit 0 when every layer is present, 1 when something is missing or
    wrong — after printing the whole list either way, so one run shows
    everything there is to fix.
    """
    from sabsim.deploy.setup_install import RC_RELATIVE_PATH, setup_install

    try:
        report = setup_install(scratch=args.scratch, share=args.share,
                               venv=args.venv)
    except RuntimeError as failure:
        print(f"sabsim: setup halted — {failure}", file=sys.stderr)
        return 1

    print(f"sabsim setup: clone {report.clone}")
    for check in report.checks:
        print(f"  {check.state:8s} {check.name:8s} {check.detail}")
    print("\nValues for the rc, and where each came from:")
    for name in ("scratch", "share", "venv"):
        print(f"  {name:8s} {report.values[name]}")
        print(f"           from {report.provenance[name]}")
    if report.rc_written:
        print(f"\n  wrote  {RC_RELATIVE_PATH}")
    else:
        print(f"\n  kept   {RC_RELATIVE_PATH}  (already there, untouched)")
    print("\nNext (DESIGN.md §10.10):")
    print(f"  1. read {RC_RELATIVE_PATH}; fix any value marked EDIT.")
    print(f"  2. `source {RC_RELATIVE_PATH}` in every login shell, then "
          f"`pytest src/tests -q`.")
    print("  3. `sabsim init <project folder> --materials <a> <b>` starts "
          "a project.")
    if not report.all_present:
        print("\n  Some layers are MISSING or WRONG (above); each line "
              "says the fix.")
        return 1
    return 0


def _init(args: argparse.Namespace) -> int:
    """Execute ``sabsim init``: write the missing parts of a project.

    Prints what was written and what was left alone, then the steps
    that come next — because the generated folder is complete in the
    §1.4 sense and unread in the science sense until the person has
    looked at it (DESIGN.md §10.9).
    """
    from sabsim.deploy.init_project import InitError, init_project

    try:
        report = init_project(args.project, materials=tuple(args.materials))
    except InitError as failure:
        print(f"sabsim: init halted — {failure}", file=sys.stderr)
        return 1

    print(f"sabsim init: project folder {report.project_directory}")
    for path in report.written:
        print(f"  wrote  {path}")
    for path in report.kept:
        print(f"  kept   {path}  (already there, untouched)")
    for notice in report.notices:
        print(f"  NOTE   {notice}")
    print("\nNext, in order (DESIGN.md §10.9):")
    print("  1. read and edit sabsim.toml (the science of this pair) and "
          "deployment.toml\n     (this machine); each prep folder's "
          "recipe.toml describes its surface's\n     material.")
    print("  2. in the project folder, `sabsim prepare` writes the job "
          "scripts and a\n     SUBMISSION_GUIDE.md: two environment-"
          "library builds (step 0, once per\n     recipe), the two "
          "surface preps, bond, and analysis.")
    print("  3. submit them in the guide's order, or as its chained form; "
          "nothing runs\n     on the login node.")
    print("  Running `sabsim init` again with the same pair is safe: it "
          "adds only\n  what is missing.")
    return 0


def _catalog(args: argparse.Namespace) -> int:
    """Execute ``sabsim catalog list`` or ``sabsim catalog add``."""
    from sabsim.catalog import (
        CatalogError,
        add_entry,
        describe_entries,
        read_catalog,
    )

    try:
        if args.verb == "list":
            lines = describe_entries(read_catalog(), args.formula)
            if not lines:
                what = (f"of formula {args.formula}" if args.formula
                        else "at all")
                print(f"sabsim catalog: no entries {what}")
                return 0
            for line in lines:
                print(line)
            return 0
        if args.verb == "add":
            provenance = {}
            if args.cod_id is not None:
                provenance["source"] = "Crystallography Open Database"
                provenance["cod_id"] = args.cod_id
                if args.cod_revision is not None:
                    provenance["cod_revision"] = args.cod_revision
            # The formula and the label are optional checks of what
            # the command derives from the crystal, phase and face.
            report = add_entry(
                args.cif, args.phase, args.face, formula=args.formula,
                label=args.label, provenance=provenance,
                source_label=args.source)
            origin = (f"cloned from {report.cloned_from}"
                      if report.cloned_from is not None
                      else "written from the template")
            print(f"sabsim catalog: added {report.entry.label} (recipe "
                  f"{origin})")
            for line in report.derived:
                print(f"  derived {line}")
            for path in report.written:
                print(f"  wrote  share/catalog/{path}")
            for notice in report.notices:
                print(f"  NOTE   {notice}")
            return 0
    except CatalogError as failure:
        print(f"sabsim: catalog halted — {failure}", file=sys.stderr)
        return 1
    print("sabsim catalog: give a verb — list or add", file=sys.stderr)
    return 2


def _prepare(args: argparse.Namespace) -> int:
    """Execute ``sabsim prepare``: write the submission scripts + guide.

    Runs on the login node and submits nothing (DESIGN.md §10.1). The spec
    and the rc must both exist; the writer's own gates (an unset root, a
    walltime over its partition ceiling) stop with a readable message
    rather than a traceback (§10.5, §10.6).
    """
    from sabsim.deploy.prepare import GUIDE_FILENAME, prepare

    if not os.path.isfile(args.spec):
        print(f"sabsim: no project file at '{args.spec}' — give a path, "
              f"or put a sabsim.toml in this directory", file=sys.stderr)
        return 2
    if not os.path.isfile(args.rc):
        print(f"sabsim: no deployment rc at '{args.rc}' — give one with "
              f"--rc, or put a deployment.toml in this directory",
              file=sys.stderr)
        return 2

    # The scripts land in the PROJECT FOLDER — where the project file is
    # — beside the four stage folders they fill (ARCHITECTURE.md §1).
    project_directory = os.path.dirname(os.path.abspath(args.spec))
    try:
        entries = prepare(args.spec, args.rc, project_directory,
                          dump_visuals=args.dump_visuals)
    except Exception as failure:                       # noqa: BLE001
        # A gate failure (unset root, walltime over ceiling, bad rc) reports
        # WHY and exits non-zero, not a raw traceback (DESIGN.md §5.7).
        print(f"sabsim: prepare halted — {failure}", file=sys.stderr)
        return 1

    print(f"\nsabsim prepare: wrote {len(entries)} script(s) to "
          f"{project_directory}")
    for entry in entries:
        print(f"  {entry.script_name}")
    print(f"  submit in the order in {GUIDE_FILENAME}.")
    return 0


COMMAND_RECORD_FILE = "command"


def record_command(arguments=None) -> None:
    """Append the issued command line to ``command`` in this directory.

    Imago's standing convention, adopted unchanged (ARCHITECTURE §4.2): one
    dated block per run — a ``Date:`` line and a ``Cmnd:`` line carrying the
    exact argument vector — so the file grows into the history of what was
    done in this folder and the exact invocation can be recovered later.
    ``arguments`` defaults to ``sys.argv``; a caller may hand in the vector
    it actually ran.
    """
    arguments = sys.argv if arguments is None else list(arguments)
    stamp = datetime.now().strftime("%b. %d, %Y: %H:%M:%S")
    with open(COMMAND_RECORD_FILE, "a", encoding="utf-8") as record:
        record.write(f"Date: {stamp}\n")
        record.write("Cmnd:" + "".join(f" {arg}" for arg in arguments))
        record.write("\n\n")


def _is_help_request(arguments) -> bool:
    """True when the vector asks for help (``-h``/``--help``) anywhere.

    argparse honours the flag at any position, including after a
    subcommand (``sabsim init -h``), and exits before anything runs.
    """
    return any(arg in ("-h", "--help") for arg in arguments)


def main(argv=None) -> int:
    """The ``sabsim`` console entry point; returns a process exit code.

    The invocation is recorded in the ``command`` file ONLY when this
    is the real entry — ``argv`` is None, so the vector is the process's
    own — never when a test or another module hands one in, so the
    suite leaves no stray ``command`` files (CLAUDE.md). A help
    request is not recorded either: it changes nothing.
    """
    # A help request does something only to the screen, so it is not part of
    # the folder's history (ARCHITECTURE §4.2).
    if argv is None and not _is_help_request(sys.argv[1:]):
        record_command()
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return _run(args)
    if args.command == "setup":
        return _setup(args)
    if args.command == "init":
        return _init(args)
    if args.command == "catalog":
        return _catalog(args)
    if args.command == "prepare":
        return _prepare(args)
    if args.command == "bootstrap":
        return _bootstrap(args)
    parser.print_help()
    return 2
