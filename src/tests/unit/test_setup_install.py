"""``sabsim setup`` — the install checked and the rc written (§10.10).

The checks read the process's own situation, so the tests hand the
module a fake clone, a fake share root, and a fake environment, and
watch it classify each layer as PRESENT, MISSING or WRONG. The rc is
written once from the template with its three lines filled, each value
labelled with where it came from, and is never overwritten.
"""

import json
from pathlib import Path

import pytest

from sabsim.cli import main
from sabsim.deploy import setup_install as module
from sabsim.deploy.setup_install import (
    ENGINE_BUNDLE,
    RC_RELATIVE_PATH,
    SHARE_LANDMARK,
    render_rc,
    setup_install,
)


@pytest.fixture
def fake_clone(tmp_path, monkeypatch):
    """A clone root with the templates present, used as the rc's home."""
    clone = tmp_path / "clone"
    (clone / "share" / "templates").mkdir(parents=True)
    monkeypatch.setattr(module, "REPOSITORY_ROOT", clone)
    return clone


@pytest.fixture
def fake_share(tmp_path):
    """A share root holding the landmark and the engine bundle."""
    share = tmp_path / "share_root"
    (share / SHARE_LANDMARK).mkdir(parents=True)
    (share / ENGINE_BUNDLE / "bin").mkdir(parents=True)
    (share / ENGINE_BUNDLE / "bin" / "lmp").write_text("#!/bin/sh\n")
    return share


@pytest.fixture
def fake_venv(tmp_path, monkeypatch, fake_clone):
    """A venv whose editable sabsim points at the fake clone."""
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "activate").write_text("# activate\n")

    class Distribution:
        def read_text(self, name):
            assert name == "direct_url.json"
            return json.dumps({"url": f"file://{fake_clone}",
                               "dir_info": {"editable": True}})

    monkeypatch.setattr(module.importlib.metadata, "distribution",
                        lambda name: Distribution())
    return venv


def _environment(share, scratch):
    return {"CONDA_PREFIX": "/conda/envs/sabsim", "CONDA_DEFAULT_ENV":
            "sabsim", "SABSIM_SHARE": str(share), "SABSIM_SCRATCH":
            str(scratch)}


def test_everything_present_writes_the_rc_once(
        fake_clone, fake_share, fake_venv, tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    report = setup_install(venv=str(fake_venv),
                           environment=_environment(fake_share, scratch))

    assert report.all_present, [c for c in report.checks
                                if c.state != "PRESENT"]
    assert report.rc_written
    rc = (fake_clone / RC_RELATIVE_PATH).read_text()
    assert f'export SABSIM_SCRATCH="{scratch}"' in rc
    assert f'export SABSIM_SHARE="{fake_share}"' in rc
    assert f"source {fake_venv}/bin/activate" in rc
    assert "conda activate sabsim" in rc
    assert report.provenance["scratch"] == "$SABSIM_SCRATCH"
    assert report.provenance["venv"] == "--venv"

    # A second run keeps the file even if the values changed.
    again = setup_install(scratch="/elsewhere", venv=str(fake_venv),
                          environment=_environment(fake_share, scratch))
    assert not again.rc_written
    assert (fake_clone / RC_RELATIVE_PATH).read_text() == rc
    assert again.provenance["scratch"] == "--scratch"


def test_template_examples_are_used_last_and_labelled(
        fake_clone, fake_share, fake_venv):
    report = setup_install(venv=str(fake_venv),
                           environment={"CONDA_PREFIX": "/c"})
    assert report.values["share"] == "/cluster/VAST/rulisp-lab/cpg"
    assert "worked example" in report.provenance["share"]
    assert "EDIT" in report.provenance["scratch"]


def test_a_venv_from_another_clone_is_wrong_not_missing(
        fake_clone, fake_share, fake_venv, tmp_path, monkeypatch):
    """Sourcing a lab-mate's rc runs THEIR tree; setup says so."""
    other = tmp_path / "someone_elses_clone"

    class Distribution:
        def read_text(self, name):
            return json.dumps({"url": f"file://{other}"})

    monkeypatch.setattr(module.importlib.metadata, "distribution",
                        lambda name: Distribution())
    report = setup_install(venv=str(fake_venv),
                           environment=_environment(fake_share, tmp_path))
    venv_check = next(c for c in report.checks if c.name == "venv")
    assert venv_check.state == "WRONG"
    assert str(other) in venv_check.detail
    assert "build_venv.sh" in venv_check.detail
    assert not report.all_present


def test_missing_layers_name_their_fix(fake_clone, fake_venv, tmp_path):
    empty_share = tmp_path / "nothing"
    report = setup_install(
        venv=str(fake_venv),
        environment={"SABSIM_SHARE": str(empty_share),
                     "SABSIM_SCRATCH": str(tmp_path / "no" / "such" / "x")})
    states = {c.name: c for c in report.checks}
    assert states["conda"].state == "MISSING"
    assert "mamba env create" in states["conda"].detail
    assert states["share"].state == "MISSING"
    assert states["engine"].state == "MISSING"
    assert states["scratch"].state == "MISSING"
    assert not report.all_present


def test_render_rc_replaces_only_the_three_lines():
    text = render_rc({"scratch": "/s", "share": "/sh", "venv": "/v"})
    assert 'export SABSIM_SCRATCH="/s"' in text
    assert 'export SABSIM_SHARE="/sh"' in text
    assert "source /v/bin/activate" in text
    assert "SABSIM_LOCAL" in text          # the rest of the template kept


def test_cli_setup_prints_the_checklist_and_exits_by_it(
        fake_clone, fake_share, fake_venv, tmp_path, monkeypatch, capsys):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    for name, value in _environment(fake_share, scratch).items():
        monkeypatch.setenv(name, value)
    assert main(["setup", "--venv", str(fake_venv)]) == 0
    out = capsys.readouterr().out
    assert "PRESENT  engine" in out
    assert "wrote  .sabsim/sabsimrc" in out
    monkeypatch.setenv("SABSIM_SHARE", str(tmp_path / "nowhere"))
    assert main(["setup", "--venv", str(fake_venv)]) == 1
    out = capsys.readouterr().out
    assert "MISSING  share" in out
    assert "kept   .sabsim/sabsimrc" in out
