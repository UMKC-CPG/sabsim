"""Trajectory recording is optional, and OFF unless asked for.

The point of these tests is that recording is a run-time choice which
must not leak into the measurement. Two things have to stay true no
matter what the switch says: the thermo line the analyzer reads is
always emitted, and nothing downstream depends on frames existing.
"""

from __future__ import annotations

import pytest

from sabsim.driver.commands import (
    recording_commands,
    stage_dump_file,
    trajectory_dump_commands,
)
from sabsim.pipeline.run_options import (
    TrajectoryOptions,
    reset_trajectory_options,
    set_trajectory_options,
    trajectory_options,
)
from sabsim.spec.loader import load_and_validate_study

_TEMPLATE = "dev/templates/study_spec.toml"


@pytest.fixture(autouse=True)
def _isolate_options():
    """Never let one test's choice leak into the next."""
    reset_trajectory_options()
    yield
    reset_trajectory_options()


@pytest.fixture
def member():
    """A real member, so the spec's frame_stride is the real one."""
    return load_and_validate_study(_TEMPLATE).members[0]


def test_recording_without_a_dump_file_still_logs_the_forces(member):
    """The MEASUREMENT survives with recording off — that is the point.

    The analyzer reads the grip reactions out of the thermo line. If
    making frames optional had also made the thermo optional, a run
    without visuals would silently stop being measurable.
    """
    commands = recording_commands(member)

    assert any(line.startswith("thermo_style custom") for line in commands)
    assert any("f_hold_bottom[3]" in line and "c_top_reaction" in line
               for line in commands)
    assert not any(line.startswith("dump ") for line in commands)


def test_recording_with_a_dump_file_adds_frames_and_keeps_the_forces(
        member):
    """Asking for frames ADDS to the measurement, never replaces it."""
    commands = recording_commands(member, "/scratch/run/pull.dump")

    assert any(line.startswith("dump traj all custom") for line in commands)
    assert any("/scratch/run/pull.dump" in line for line in commands)
    # The thermo line is still there, unchanged.
    assert any(line.startswith("thermo_style custom") for line in commands)


def test_dump_commands_sort_by_identity(member):
    """A viewer needs a stable atom order across frames.

    The cascade creates and deletes projectile atoms, so without an
    explicit sort the per-frame ordering can shift and a viewer will
    happily draw one atom's trajectory onto another's.
    """
    commands = trajectory_dump_commands("/scratch/run/act.dump", 250)

    assert "dump_modify traj sort id" in commands
    assert any("custom 250 /scratch/run/act.dump" in line
               for line in commands)


def test_stage_dump_files_are_named_for_member_and_stage():
    """A directory of trajectories should read as an account of the run."""
    path = stage_dump_file("/scratch/run", "si-si-reference", "press")

    assert path == "/scratch/run/si-si-reference_press.dump"


def test_recording_is_off_by_default():
    """The expensive thing is not the default (frames cost GB and time)."""
    assert trajectory_options().enabled is False


def test_an_explicit_stride_overrides_the_specification():
    """The command line overrides the spec; absent, the spec wins."""
    set_trajectory_options(TrajectoryOptions(enabled=True, stride=500))
    assert trajectory_options().stride_or(100) == 500

    set_trajectory_options(TrajectoryOptions(enabled=True, stride=None))
    assert trajectory_options().stride_or(100) == 100


def test_stage_trajectory_returns_no_path_when_recording_is_off(member):
    """Stages ask one helper, and get None when nobody wants frames."""
    from sabsim.pipeline.live_stages import _stage_trajectory

    path, stride = _stage_trajectory("/scratch/run", member, "press")
    assert path is None
    assert stride == member.numerical.frame_stride

    set_trajectory_options(TrajectoryOptions(enabled=True, stride=42))
    path, stride = _stage_trajectory("/scratch/run", member, "press")
    assert path == f"/scratch/run/{member.name}_press.dump"
    assert stride == 42


def test_the_cli_records_by_default_and_has_an_explicit_opt_out():
    """Recording is ON unless a run says --no-dump-visuals (2026-08-26)."""
    from sabsim.cli import _build_parser

    parser = _build_parser()
    plain = parser.parse_args(["run", "spec.toml"])
    assert plain.dump_visuals is True
    assert plain.dump_stride is None

    declined = parser.parse_args(["run", "spec.toml", "--no-dump-visuals"])
    assert declined.dump_visuals is False

    asked = parser.parse_args(
        ["run", "spec.toml", "--dump-visuals", "--dump-stride", "250"])
    assert asked.dump_visuals is True
    assert asked.dump_stride == 250


# ---------------------------------------------------------------------
# Wiring tests. The unit tests above check each PIECE in isolation, and
# that is exactly how a real bug got through: press_and_bond accepted a
# trajectory_file, forwarded it nowhere, and silently recorded nothing.
# These drive the actual phase functions against a recording engine and
# assert on the command stream LAMMPS would really have received.
# ---------------------------------------------------------------------

class _RecordingEngine:
    """An Engine stand-in that remembers every command issued to it."""

    def __init__(self, atoms=8, box_height=100.0):
        self.issued = []
        self._atoms = atoms
        self._height = box_height

    def commands(self, lines):
        self.issued.extend(lines)

    def run(self, steps):
        pass

    def positions(self):
        import numpy as np
        return np.zeros((self._atoms, 3))

    def atom_ids(self):
        # Dense ids over whatever positions frame this stub serves, so the
        # press/pull tag realignment sees a loss-free 1..N (identity). Keyed
        # off positions() so a subclass overriding it stays consistent.
        import numpy as np
        return np.arange(1, self.positions().shape[0] + 1)

    def box(self):
        import numpy as np
        return np.diag([10.0, 10.0, self._height])

    def energy(self):
        return -1.0

    def atom_count(self):
        return self._atoms

    def scalar(self, _name):
        return 0.0

    def normal_stress(self):
        # Positive == compressive contact, so the press reaches its
        # criterion promptly and the test stays fast.
        return 1.0

    def grip_reaction(self, *_args):
        return 0.0

    def close(self):
        pass


def _press_commands(member, trajectory_file, stride=None):
    """Run the real press setup and return the commands it issued."""
    from types import SimpleNamespace

    import numpy as np

    from sabsim.driver.commands import ForceModel, RegionGeometry
    from sabsim.driver.press_pull import _press_setup
    from sabsim.structure.slab_builder import WAFER_A_TAG, WAFER_B_TAG

    tags = np.array([WAFER_A_TAG] * 100 + [WAFER_B_TAG] * 100)
    cell = np.array([[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 60.0]])
    atoms = SimpleNamespace(get_tags=lambda: tags, get_cell=lambda: cell)
    built = SimpleNamespace(
        atoms=atoms, wafer_a_z_range=(0.0, 10.0),
        wafer_b_z_range=(15.0, 25.0), type_map={"Si": 1})
    force_model = ForceModel(
        pair_style="sw", pair_coeff=("* * Si.sw Si",))
    return _press_setup(
        built, member, force_model, "ref.data", 1, RegionGeometry(),
        trajectory_file, stride)


def _press_and_bond_commands(member, trajectory_file, stride=None):
    """Drive the REAL press phase and return what it issued to LAMMPS.

    Deliberately goes through ``press_and_bond`` rather than the setup
    helper it calls. The bug this guards against lived in the forwarding
    BETWEEN those two — the helper was always correct — so a test that
    calls the helper directly passes while the pipeline records nothing.
    """
    from types import SimpleNamespace

    import numpy as np

    from sabsim.driver.commands import ForceModel
    from sabsim.driver.press_pull import RunControl, press_and_bond
    from sabsim.structure.slab_builder import WAFER_A_TAG, WAFER_B_TAG

    tags = np.array([WAFER_A_TAG] * 100 + [WAFER_B_TAG] * 100)
    cell = np.array([[4.0, 0.0, 0.0], [0.0, 4.0, 0.0], [0.0, 0.0, 60.0]])
    atoms = SimpleNamespace(get_tags=lambda: tags, get_cell=lambda: cell)
    built = SimpleNamespace(
        atoms=atoms, wafer_a_z_range=(0.0, 10.0),
        wafer_b_z_range=(15.0, 25.0), type_map={"Si": 1})

    positions = np.zeros((200, 3))
    positions[:100, 2] = 5.0
    positions[100:, 2] = 20.0

    class Engine(_RecordingEngine):
        def positions(self):
            return positions

    engine = Engine()
    press_and_bond(
        engine, built, member,
        ForceModel(pair_style="sw", pair_coeff=("* * Si.sw Si",)),
        "pair.data", 1, control=RunControl(max_chunks=1),
        trajectory_file=trajectory_file, trajectory_stride=stride)
    return engine.issued


def test_press_emits_a_dump_only_when_given_a_file(member):
    """The press must actually RECORD when asked to — the bug was here.

    press_and_bond took a trajectory_file and forwarded it nowhere, so a
    run requested with visuals produced no press movie and said nothing
    about it. This drives press_and_bond itself; an earlier version of
    this test called the setup helper directly and passed even with the
    bug reinstated, which is exactly how the defect survived once.
    """
    silent = _press_and_bond_commands(member, None)
    assert not any(line.startswith("dump ") for line in silent)

    recorded = _press_and_bond_commands(member, "/scratch/run/press.dump")
    assert any(line.startswith("dump traj all custom") and
               "/scratch/run/press.dump" in line for line in recorded)


def test_press_honours_an_explicit_stride(member):
    """An override must reach LAMMPS, not be quietly replaced by the spec.

    The stride was being discarded at the call site and the spec's
    frame_stride used instead, which is why dumps stayed at 1.3 GB when
    a coarser stride had been asked for.
    """
    recorded = _press_and_bond_commands(
        member, "/scratch/run/press.dump", 2000)
    dump = next(line for line in recorded if line.startswith("dump traj"))
    assert " 2000 " in dump

    default = _press_and_bond_commands(member, "/scratch/run/press.dump")
    dump = next(line for line in default if line.startswith("dump traj"))
    assert f" {member.numerical.frame_stride} " in dump
