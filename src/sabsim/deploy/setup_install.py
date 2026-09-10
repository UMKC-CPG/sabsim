"""``sabsim setup`` — the install checked, and the shell rc written.

DESIGN.md §10.10. The one file the install could not generate was the
shell rc, ``.sabsim/sabsimrc``: it has to be live before Python starts
because it names the install itself (ARCHITECTURE.md §4.1), so it was
"copy an existing one and edit the paths" — the same hand-copying that
``sabsim init`` removed from the project side. This module is the
generator for it, wrapped in a checklist.

It runs from the Python environment the person has just built and
reads its OWN situation rather than asking questions: which clone this
package is installed from (the editable install's pointer), which
interpreter prefix it runs under (the venv), which conda environment
sits beneath it, and what the three location roots currently are. It
reports each layer as PRESENT, MISSING (with the command that fixes
it), or WRONG — the last being the student's classic mistake of
sourcing a lab-mate's rc and silently running that lab-mate's clone.

Then it writes the rc from the template, never overwriting, with each
value taken in order from a flag, from the variable already set in the
environment, or from the template's worked example — and it says which
per value, so an unedited example path is reported as such rather than
trusted. It builds nothing: the conda environment and the venv are
hour-long steps a person launches knowingly (§10.1).
"""

from __future__ import annotations

import importlib.metadata
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from sabsim.deploy.init_project import REPOSITORY_ROOT, TEMPLATE_ROOT

RC_TEMPLATE = TEMPLATE_ROOT / "sabsimrc"
RC_RELATIVE_PATH = Path(".sabsim") / "sabsimrc"

# What the share root must hold to be the install (ARCHITECTURE §4.1),
# and the engine bundle the universal-cascade jobs run out of process.
SHARE_LANDMARK = Path("share") / "models"
ENGINE_BUNDLE = Path("programs") / "deepmd-kit-3.2.0b0-cuda129"

# The three lines of the template `setup` fills, matched at line start.
_RC_LINE = {
    "scratch": re.compile(r'^(export SABSIM_SCRATCH=)"[^"]*"$', re.MULTILINE),
    "share": re.compile(r'^(export SABSIM_SHARE=)"[^"]*"$', re.MULTILINE),
    "venv": re.compile(r"^(source )\S+/bin/activate$", re.MULTILINE),
}


@dataclass(frozen=True)
class Check:
    """One layer of the install and what `setup` found of it."""

    name: str
    state: str          # "PRESENT", "MISSING" or "WRONG"
    detail: str         # what was found, or how to fix it


@dataclass
class SetupReport:
    """Everything one `setup` run learned and did (PSEUDOCODE §14.8)."""

    clone: Path
    checks: list[Check] = field(default_factory=list)
    values: dict = field(default_factory=dict)      # name -> value
    provenance: dict = field(default_factory=dict)  # name -> where from
    rc_path: Path | None = None
    rc_written: bool = False

    @property
    def all_present(self) -> bool:
        return all(check.state == "PRESENT" for check in self.checks)


def setup_install(scratch: str | None = None, share: str | None = None,
                  venv: str | None = None,
                  environment: dict | None = None) -> SetupReport:
    """Check the install layers and write the rc if it is missing.

    ``environment`` defaults to the process environment; a test passes
    its own. Nothing is built and nothing existing is overwritten.
    """
    environment = os.environ if environment is None else environment
    clone = REPOSITORY_ROOT
    report = SetupReport(clone=clone)

    # --- Where each value comes from, said aloud (DESIGN §10.10). ---
    example_scratch, example_share, _ = _template_examples()
    report.values["scratch"], report.provenance["scratch"] = _choose(
        scratch, "--scratch", environment.get("SABSIM_SCRATCH"),
        "$SABSIM_SCRATCH", example_scratch)
    report.values["share"], report.provenance["share"] = _choose(
        share, "--share", environment.get("SABSIM_SHARE"),
        "$SABSIM_SHARE", example_share)
    if venv is not None:
        report.values["venv"], report.provenance["venv"] = venv, "--venv"
    else:
        report.values["venv"] = sys.prefix
        report.provenance["venv"] = "the interpreter running setup"

    # --- The checks, in install order. ---
    report.checks.append(_check_clone(clone))
    report.checks.append(_check_conda(environment))
    report.checks.append(_check_venv(clone, report.values["venv"]))
    share_root = Path(os.path.expandvars(report.values["share"]))
    report.checks.append(_check_share(share_root))
    report.checks.append(_check_engine(share_root))
    report.checks.append(_check_scratch(
        Path(os.path.expandvars(os.path.expanduser(
            report.values["scratch"])))))

    # --- The rc, written only if missing. ---
    report.rc_path = clone / RC_RELATIVE_PATH
    if not report.rc_path.exists():
        report.rc_path.parent.mkdir(parents=True, exist_ok=True)
        report.rc_path.write_text(render_rc(report.values))
        report.rc_written = True
    return report


def render_rc(values: dict) -> str:
    """The template with its three machine-specific lines replaced."""
    if not RC_TEMPLATE.is_file():
        raise RuntimeError(f"rc template {RC_TEMPLATE} is missing — the "
                           f"clone's share/templates/ is incomplete")
    text = RC_TEMPLATE.read_text()
    replacements = {
        "scratch": f'"{values["scratch"]}"',
        "share": f'"{values["share"]}"',
        "venv": f'{values["venv"]}/bin/activate',
    }
    for key, pattern in _RC_LINE.items():
        text, count = pattern.subn(
            lambda match, value=replacements[key]: f"{match.group(1)}{value}",
            text, count=1)
        if count != 1:
            raise RuntimeError(f"rc template has no '{key}' line to set")
    return text


def _template_examples() -> tuple[str, str, str]:
    """The worked-example values the template ships, in its own words."""
    text = RC_TEMPLATE.read_text() if RC_TEMPLATE.is_file() else ""
    def value_of(key):
        match = _RC_LINE[key].search(text)
        if match is None:
            return ""
        return match.group(0).split("=", 1)[1].strip('"') if (
            key != "venv") else match.group(0).split(" ", 1)[1]
    return value_of("scratch"), value_of("share"), value_of("venv")


def _choose(flag, flag_name, from_environment, variable_name, example):
    """Flag, then environment, then the template example — with source."""
    if flag:
        return flag, flag_name
    if from_environment:
        return from_environment, variable_name
    return example, "the template's worked example — EDIT for this machine"


def _check_clone(clone: Path) -> Check:
    if (clone / "share" / "templates").is_dir():
        return Check("clone", "PRESENT", str(clone))
    return Check("clone", "WRONG",
                 f"{clone} does not hold share/templates/; this package "
                 f"is not installed from a full clone")


def _check_conda(environment) -> Check:
    prefix = environment.get("CONDA_PREFIX")
    if prefix:
        name = environment.get("CONDA_DEFAULT_ENV", "?")
        return Check("conda", "PRESENT", f"{name} at {prefix}")
    return Check("conda", "MISSING",
                 "no conda environment is active; build layer 1 with "
                 "`CONDA_OVERRIDE_CUDA=12.9 mamba env create -f "
                 "install/environment.yml` then `conda activate sabsim`")


def _check_venv(clone: Path, venv: str) -> Check:
    """The venv must be a venv, and its editable sabsim must be THIS clone.

    The editable pointer is read from the distribution's own record
    (``direct_url.json``), the same fact ``pip`` wrote at install time.
    """
    venv_path = Path(venv)
    if not (venv_path / "bin" / "activate").is_file():
        return Check("venv", "MISSING",
                     f"{venv} is not a virtual environment; build layer 2 "
                     f"with `bash install/build_venv.sh` after editing "
                     f"its paths")
    try:
        record = importlib.metadata.distribution("sabsim").read_text(
            "direct_url.json") or ""
        url = json.loads(record).get("url", "")
    except (importlib.metadata.PackageNotFoundError, ValueError):
        url = ""
    installed_from = Path(url.replace("file://", "")) if url else None
    if installed_from is None:
        return Check("venv", "MISSING",
                     "the running Python has no editable sabsim; "
                     "`bash install/build_venv.sh` installs this clone")
    if installed_from.resolve() != clone.resolve():
        return Check("venv", "WRONG",
                     f"the venv's editable sabsim points at "
                     f"{installed_from}, not this clone {clone}: you are "
                     f"running someone else's tree. Build your own venv "
                     f"with `bash install/build_venv.sh` (edit its paths "
                     f"first) and source your own rc")
    return Check("venv", "PRESENT", f"{venv} (editable sabsim from {clone})")


def _check_share(share_root: Path) -> Check:
    if (share_root / SHARE_LANDMARK).is_dir():
        return Check("share", "PRESENT", str(share_root))
    return Check("share", "MISSING",
                 f"{share_root} holds no {SHARE_LANDMARK}/; SABSIM_SHARE "
                 f"must be the group install root (ARCHITECTURE §4.1) — "
                 f"give it with --share")


def _check_engine(share_root: Path) -> Check:
    bundle = share_root / ENGINE_BUNDLE
    if (bundle / "bin" / "lmp").is_file():
        return Check("engine", "PRESENT", str(bundle))
    return Check("engine", "MISSING",
                 f"no deepmd bundle at {bundle} (bin/lmp); the "
                 f"universal-cascade prep jobs need it — see "
                 f"install/cascade-engine-deepmd-official.md")


def _check_scratch(scratch_root: Path) -> Check:
    if scratch_root.is_dir():
        if os.access(scratch_root, os.W_OK):
            return Check("scratch", "PRESENT", str(scratch_root))
        return Check("scratch", "WRONG", f"{scratch_root} is not writable")
    parent = scratch_root.parent
    if parent.is_dir() and os.access(parent, os.W_OK):
        return Check("scratch", "PRESENT",
                     f"{scratch_root} (not there yet; the first run makes "
                     f"it)")
    return Check("scratch", "MISSING",
                 f"neither {scratch_root} nor its parent exists or is "
                 f"writable; give a per-user scratch root with --scratch")
