"""Unit tests for the `sabsim submit` hand (sabsim.deploy.submit).

These pin DESIGN §10.12 / PSEUDOCODE §14.10 against scripts that the
real `prepare` writer has written into a fresh project folder: the
three selection rules (only what is named; a library build only when
the library is missing; a missing script is a stop before anything is
submitted), the `afterok` chain among the named jobs, the `--gpu`
override that keeps each script's card count and leaves a CPU job
alone, the `--node` pin, the GPU partition both overrides request, and
the dry run that calls no scheduler. The scheduler is a double that
records every sbatch line it is handed, and the cluster is a fixed
node table in `sinfo`'s own layout, so no test asks a real scheduler.
"""

import os
import sys

import pytest

from sabsim.cli import main
from sabsim.deploy import prepare
from sabsim.deploy.submit import (
    SubmitError,
    gpu_count_in_script,
    parse_node_table,
    requested_job_names,
    submit,
)
from sabsim.driver.environment_library import LIBRARY_MANIFEST_FILE
from tests.unit.support import project_in

_RC_TEMPLATE = os.path.abspath(os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "share", "templates", "deployment_rc.toml"))

# The six script names the fixture pair yields, in the guide's order.
_LIB_1 = "prep_surf1_si.library.slurm"
_LIB_2 = "prep_surf2_sio2.library.slurm"
_PREP_1 = "prep_surf1_si.slurm"
_PREP_2 = "prep_surf2_sio2.slurm"
_BOND = "bond_si_sio2.slurm"
_ANALYSIS = "analysis_si_sio2.slurm"

# A small cluster in the layout of `sinfo -h -N -O NodeList,Partition,
# Gres,StateCompact`, copied in shape from the machine the rule was
# written on: `requeue` (the default, hence the `*`) mixes CPU and GPU
# nodes, `gpu` and `gpu_requeue` hold GPU nodes only, the V100 node
# g022 is reachable through `gpu_requeue` alone, and `gpu_requeue`
# also lists one drained node that carries no card.
_NODE_TABLE = """\
c018     general      (null)              idle
c018     requeue*     (null)              idle
g018     gpu_requeue  gpu:H100:4(S:0-1)   mix
g018     requeue*     gpu:H100:4(S:0-1)   mix
g022     gpu_requeue  gpu:V100:1(S:0-71)  idle
g022     requeue*     gpu:V100:1(S:0-71)  idle
g027     gpu          gpu:V100:1(S:0-71)  idle
g027     gpu_requeue  gpu:V100:1(S:0-71)  idle
g027     requeue*     gpu:V100:1(S:0-71)  idle
g003     gpu_requeue  gpu:1g.10gb:28      mix
g003     requeue*     gpu:1g.10gb:28      mix
gpu-1-2  gpu_requeue  (null)              drain
"""


def _cluster():
    """The fixed cluster above, as `submit`'s survey would return it."""
    return parse_node_table(_NODE_TABLE)


@pytest.fixture
def prepared_project(tmp_path, monkeypatch):
    """A project folder with the six scripts `prepare` writes, CWD there."""
    monkeypatch.setenv("SABSIM_SCRATCH", str(tmp_path / "scratch"))
    monkeypatch.setenv("SABSIM_SHARE", "/cluster/VAST/rulisp-lab/cpg")
    monkeypatch.delenv("SABSIM_LOCAL", raising=False)
    home = tmp_path / "si_sio2"
    home.mkdir()
    monkeypatch.chdir(home)
    spec = project_in(home)
    rc = home / "deployment.toml"
    rc.write_text(open(_RC_TEMPLATE, encoding="utf-8").read())
    prepare(spec, str(rc), home)
    return home


class RecordingScheduler:
    """A stand-in for sbatch: hands out ids and keeps every line."""

    def __init__(self):
        self.lines = []
        self.next_id = 100

    def __call__(self, options, script):
        self.next_id += 1
        self.lines.append((list(options), script.name))
        return str(self.next_id)


def _options_for(scheduler, script_name):
    for options, name in scheduler.lines:
        if name == script_name:
            return options
    raise AssertionError(f"{script_name} was not submitted")


def test_all_submits_the_whole_chain_held_on_afterok(prepared_project):
    """`all` with no libraries: six lines, each held on its upstream ids."""
    scheduler = RecordingScheduler()
    submissions, notices = submit(
        "sabsim.toml", ["all"], prepared_project, scheduler=scheduler)
    assert notices == ()
    assert [name for _, name in scheduler.lines] == [
        _LIB_1, _LIB_2, _PREP_1, _PREP_2, _BOND, _ANALYSIS]
    ids = {sub.job_name: sub.job_id for sub in submissions}
    assert _options_for(scheduler, _LIB_1) == ["--parsable"]
    assert _options_for(scheduler, _PREP_1) == [
        "--parsable", f"--dependency=afterok:{ids['library_surf1']}"]
    assert _options_for(scheduler, _BOND) == [
        "--parsable",
        f"--dependency=afterok:{ids['prep_surf1']}:{ids['prep_surf2']}"]
    assert _options_for(scheduler, _ANALYSIS) == [
        "--parsable", f"--dependency=afterok:{ids['bond']}"]


def test_an_existing_library_skips_its_build(prepared_project):
    """A prep folder holding its library manifest gets no library job."""
    (prepared_project / "prep_surf1_si" / LIBRARY_MANIFEST_FILE).write_text(
        "# a library\n")
    scheduler = RecordingScheduler()
    _, notices = submit("sabsim.toml", ["prep-surf1", "prep-surf2"],
                        prepared_project, scheduler=scheduler)
    assert [name for _, name in scheduler.lines] == [_LIB_2, _PREP_1,
                                                     _PREP_2]
    assert _options_for(scheduler, _PREP_1) == ["--parsable"]
    assert len(notices) == 1 and "skipped" in notices[0]


def test_a_job_alone_is_not_held_on_absent_upstream(prepared_project):
    """`bond` by itself: its preps were run and checked, so no afterok."""
    scheduler = RecordingScheduler()
    submit("sabsim.toml", ["bond"], prepared_project, scheduler=scheduler)
    assert scheduler.lines == [(["--parsable"], _BOND)]


def test_the_node_table_names_the_gpu_partitions():
    """Only partitions whose in-service nodes all carry a GPU count."""
    cluster = _cluster()
    # `requeue` mixes in the CPU node c018; the drained card-less
    # gpu-1-2 does NOT disqualify `gpu_requeue`; the `*` is dropped.
    assert cluster.gpu_partitions() == ("gpu", "gpu_requeue")
    assert cluster.partitions_of("g022") == ("gpu_requeue", "requeue")
    assert cluster.gpu_partitions_of("g022") == ("gpu_requeue",)
    assert cluster.gpu_partitions_for_model("V100") == (
        "gpu", "gpu_requeue")
    assert cluster.gpu_partitions_for_model("H100") == ("gpu_requeue",)
    assert cluster.card_model("g022") == "V100"
    # A MIG slice is not a card a script can name; a CPU node has none.
    assert cluster.card_model("g003") is None
    assert cluster.card_model("c018") is None
    assert parse_node_table("").gpu_partitions() == ()


def test_gpu_override_keeps_count_and_spares_cpu_jobs(prepared_project):
    """--gpu swaps model and partition on GPU jobs only, keeping counts."""
    scheduler = RecordingScheduler()
    _, notices = submit(
        "sabsim.toml", ["all"], prepared_project, gpu_type="V100",
        scheduler=scheduler, cluster_survey=_cluster)
    prep_count = gpu_count_in_script(prepared_project / _PREP_1)
    assert prep_count is not None
    assert _options_for(scheduler, _PREP_1)[-2:] == [
        f"--gres=gpu:V100:{prep_count}", "--partition=gpu,gpu_requeue"]
    assert gpu_count_in_script(prepared_project / _ANALYSIS) is None
    analysis_options = _options_for(scheduler, _ANALYSIS)
    assert not any(option.startswith(("--gres", "--partition"))
                   for option in analysis_options)
    assert any("gpu,gpu_requeue" in notice for notice in notices)


def test_an_unlisted_card_keeps_the_scripts_partition(prepared_project):
    """A model the node table does not hold: --gres only, and a notice."""
    scheduler = RecordingScheduler()
    _, notices = submit(
        "sabsim.toml", ["prep-surf1"], prepared_project, gpu_type="K80",
        scheduler=scheduler, cluster_survey=_cluster)
    assert _options_for(scheduler, _PREP_1)[-1] == "--gres=gpu:K80:1"
    assert any("no GPU partition" in notice for notice in notices)


def test_a_pinned_node_decides_the_card_and_partition(prepared_project):
    """--node alone requests the node's card in the node's GPU partition.

    The 2026-11-08 failure: the script lists `gpu,requeue`, g022 is in
    `requeue` and `gpu_requeue` only, and the pinned job fell into
    `requeue`, the mixed pool the site keeps for CPU work.
    """
    scheduler = RecordingScheduler()
    _, notices = submit(
        "sabsim.toml", ["prep-surf1"], prepared_project, node="g022",
        scheduler=scheduler, cluster_survey=_cluster)
    assert _options_for(scheduler, _PREP_1)[-3:] == [
        "--gres=gpu:V100:1", "--partition=gpu_requeue", "--nodelist=g022"]
    assert any("carries V100" in notice and "gpu_requeue" in notice
               for notice in notices)


def test_a_named_card_on_a_pinned_node_uses_the_nodes_partition(
        prepared_project):
    """--gpu with --node: the card as named, the partition from the node."""
    scheduler = RecordingScheduler()
    submit("sabsim.toml", ["prep-surf1"], prepared_project,
           gpu_type="V100", node="g027", scheduler=scheduler,
           cluster_survey=_cluster)
    assert _options_for(scheduler, _PREP_1)[-3:] == [
        "--gres=gpu:V100:1", "--partition=gpu,gpu_requeue",
        "--nodelist=g027"]


def test_a_pinned_cpu_node_keeps_the_scripts_request(prepared_project):
    """A node reporting no GPU leaves the script's lines as the rc wrote."""
    scheduler = RecordingScheduler()
    _, notices = submit(
        "sabsim.toml", ["analysis"], prepared_project, node="c018",
        scheduler=scheduler, cluster_survey=_cluster)
    assert _options_for(scheduler, _ANALYSIS) == ["--parsable",
                                                  "--nodelist=c018"]
    assert any("reports no GPU" in notice for notice in notices)


def test_no_override_asks_the_scheduler_nothing(prepared_project):
    """Without --gpu or --node the node table is never read."""
    def forbidden_survey():
        raise AssertionError("the node table was read with no override")

    scheduler = RecordingScheduler()
    submit("sabsim.toml", ["bond"], prepared_project, scheduler=scheduler,
           cluster_survey=forbidden_survey)
    assert scheduler.lines == [(["--parsable"], _BOND)]


def test_a_missing_script_stops_before_any_submission(prepared_project):
    """Delete bond's script: `all` halts naming prepare, nothing issued."""
    (prepared_project / _BOND).unlink()
    scheduler = RecordingScheduler()
    with pytest.raises(SubmitError, match="sabsim prepare"):
        submit("sabsim.toml", ["all"], prepared_project,
               scheduler=scheduler)
    assert scheduler.lines == []


def test_dry_run_plans_without_calling_the_scheduler(prepared_project):
    """--dry-run returns placeholder ids and never touches sbatch."""
    scheduler = RecordingScheduler()
    submissions, _ = submit("sabsim.toml", ["all"], prepared_project,
                            dry_run=True, scheduler=scheduler)
    assert scheduler.lines == []
    assert [sub.job_id for sub in submissions][:3] == [
        "<library_surf1_id>", "<library_surf2_id>", "<prep_surf1_id>"]
    assert submissions[4].options == (
        "--parsable", "--dependency=afterok:<prep_surf1_id>:<prep_surf2_id>")


def test_job_words_map_to_registry_order():
    """Dashed words become registry names in registry order; typos stop."""
    assert requested_job_names(["bond", "prep-surf2"]) == (
        "prep_surf2", "bond")
    assert requested_job_names(["all"]) == (
        "prep_surf1", "prep_surf2", "bond", "analysis")
    with pytest.raises(SubmitError, match="no such job"):
        requested_job_names(["press"])


def test_cli_dry_run_prints_the_lines(prepared_project, capsys,
                                      monkeypatch):
    """`sabsim submit all --dry-run` prints six sbatch lines, exit 0."""
    # The package exports the `submit` FUNCTION under the module's own
    # name, so the module is fetched from the import table by its path.
    submit_module = sys.modules["sabsim.deploy.submit"]
    monkeypatch.setattr(submit_module, "survey_cluster", _cluster)
    assert main(["submit", "all", "--gpu", "H100", "--dry-run"]) == 0
    output = capsys.readouterr().out
    assert output.count("sbatch --parsable") == 6
    assert "--gres=gpu:H100:1 --partition=gpu_requeue" in output
    assert "would issue" in output


def test_cli_without_scripts_halts_readably(tmp_path, monkeypatch, capsys):
    """A project folder `prepare` has not visited: exit 1, names prepare."""
    monkeypatch.setenv("SABSIM_SCRATCH", str(tmp_path / "scratch"))
    home = tmp_path / "si_sio2"
    home.mkdir()
    monkeypatch.chdir(home)
    project_in(home)
    assert main(["submit", "prep-surf1", "--dry-run"]) == 1
    assert "sabsim prepare" in capsys.readouterr().err
