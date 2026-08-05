"""Tests for the real build-halves stage (ARCHITECTURE.md §4.3, §7.1).

The activation and assembly stages open a real ``LammpsEngine`` and need a
compute node, so they are validated by a driver on the node, not here.
``build_halves`` is login-node work — it cuts real slabs and writes their
data files with no LAMMPS — so it is unit-tested here, together with the
``read_standalone_half`` round-trip the amorphization stage relies on.
"""

from __future__ import annotations

import os

from dataclasses import replace

import pytest
from ase.io import read as ase_read

from types import SimpleNamespace

from sabsim.pipeline.live_stages import (
    _bonded_force_model,
    _publish_file,
    _pull_note,
    _pull_rung_paths,
    _resolve_cif,
    build_halves,
)
from sabsim.spec.loader import load_and_validate_study
from sabsim.spec.records import Quantity
from sabsim.structure.slab_builder import (
    WAFER_A_TAG,
    WAFER_B_TAG,
    read_standalone_half,
)

_TEMPLATE = "dev/templates/study_spec.toml"


def _si_si_member():
    """The Si/Si reference member — both wafers silicon (identity case)."""
    study = load_and_validate_study(_TEMPLATE)
    for member in study.members:
        if member.name == "si-si-reference":
            return member
    raise AssertionError("si-si-reference member not found in template")


def test_bonded_force_model_is_classical_without_override(monkeypatch):
    """With no deepmd override, the pair bonds under the classical stand-in."""
    monkeypatch.delenv("SABSIM_DEEPMD_MODEL", raising=False)
    model = _bonded_force_model(
        {"Si": 1}, {"Si"}, "diamond-cubic", allow_unvalidated=True)
    assert model.pair_style == "sw"        # Stillinger-Weber, no plugin
    assert model.preload == ()


def test_bonded_force_model_uses_deepmd_override(monkeypatch, tmp_path):
    """An explicit SABSIM_DEEPMD_MODEL bonds under THAT deepmd model.

    The trained-MLIP force path drops in behind the same seam: the pair
    style becomes ``deepmd <path>`` and the model carries its plugin load.
    """
    model_file = tmp_path / "graph.pb"
    model_file.write_bytes(b"\x00")        # a stand-in file; only its path
    monkeypatch.setenv("SABSIM_DEEPMD_MODEL", str(model_file))
    model = _bonded_force_model(
        {"Si": 1}, {"Si"}, "diamond-cubic", allow_unvalidated=True)
    assert model.pair_style == f"deepmd {model_file}"
    assert model.pair_coeff == ("* *",)
    assert "plugin load ${dp}" in model.preload


def test_bonded_force_model_override_missing_file_is_a_loud_stop(
        monkeypatch):
    """A named-but-absent deepmd model stops, never silently falls back."""
    monkeypatch.setenv("SABSIM_DEEPMD_MODEL", "/no/such/model.pb")
    with pytest.raises(FileNotFoundError, match="does not exist"):
        _bonded_force_model(
            {"Si": 1}, {"Si"}, "diamond-cubic", allow_unvalidated=True)


def test_pull_rung_paths_are_self_contained(tmp_path):
    """Each rung gets its own directory, log, and checkpoints seam (§11.3).

    The self-contained layout is what lets a rung resume from its own
    checkpoints without reaching into another rung's state.
    """
    scratch = str(tmp_path)
    rung = _pull_rung_paths(scratch, _si_si_member(), Quantity(3.2, "m/s"))

    assert rung.directory == os.path.join(scratch, "pull_3p2mps")
    assert os.path.isdir(rung.directory)            # created for the log
    assert rung.log_file == os.path.join(rung.directory, "log.pull")
    assert rung.checkpoint_directory == os.path.join(
        rung.directory, "checkpoints")
    # The checkpoints subdir is created lazily by the first write, so a
    # rung that never checkpoints leaves none behind.
    assert not os.path.exists(rung.checkpoint_directory)


def test_pull_rungs_get_distinct_directories(tmp_path):
    """Two rates never share a directory, so their resumes stay apart."""
    fast = _pull_rung_paths(
        str(tmp_path), _si_si_member(), Quantity(3.2, "m/s"))
    slow = _pull_rung_paths(
        str(tmp_path), _si_si_member(), Quantity(1.0, "m/s"))

    assert fast.directory != slow.directory
    assert fast.checkpoint_directory != slow.checkpoint_directory


def _pull_result(**overrides) -> SimpleNamespace:
    """A stand-in pull result carrying just the fields _pull_note reads."""
    fields = dict(
        complete=True, atoms_conserved=True,
        resumed=False, override_used=False)
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_pull_note_declares_a_resumed_rung():
    """A resumed rung says so in its note, and flags any override (§13.6)."""
    # A fresh, clean separation carries no resume marker.
    assert _pull_note(_pull_result()) == "separated"
    # Resumed without an override.
    assert _pull_note(_pull_result(resumed=True)) == "separated [resumed]"
    # Resumed with the trust guard overridden — both facts surface.
    assert _pull_note(_pull_result(
        resumed=True, override_used=True)) == (
            "separated [resumed; trust override]")
    # The marker rides on the base verdict, whatever it is.
    assert _pull_note(_pull_result(
        complete=False, resumed=True)) == (
            "did not fully separate within the pull budget [resumed]")


def test_build_halves_writes_two_handles(tmp_path):
    """Both wafers become standalone data files with real handles."""
    member = _si_si_member()
    handle_a, handle_b, shared = build_halves(
        member, potential=None, scratch_directory=str(tmp_path))

    # Two handles, tagged bottom A / top B, each naming a written file.
    assert handle_a.wafer_tag == WAFER_A_TAG
    assert handle_b.wafer_tag == WAFER_B_TAG
    assert handle_a.identity == "Si" and handle_b.identity == "Si"
    for handle in (handle_a, handle_b):
        assert (tmp_path / handle.data_file.split("/")[-1]).exists()
        # The beam species (Ar) is declared in the type map, though the
        # pristine slab contains none of it.
        assert "Ar" in handle.type_map and "Si" in handle.type_map
    assert shared is not None


def test_built_half_declares_the_beam_and_is_orthogonal(tmp_path):
    """The written half declares the Ar type and has a tilt-free cell."""
    member = _si_si_member()
    handle_a, _, _ = build_halves(
        member, potential=None, scratch_directory=str(tmp_path))

    text = (tmp_path / handle_a.data_file.split("/")[-1]).read_text()
    assert "2 atom types" in text          # Si + the declared beam Ar
    assert "# Ar" in text

    # Re-read the geometry the way the amorphization stage will, and check
    # the in-plane cell has no xy tilt (orthogonalize_in_plane did its job).
    half = read_standalone_half(
        handle_a.data_file, handle_a.type_map, handle_a.identity)
    cell = half.atoms.get_cell()
    assert abs(cell[1][0]) < 1.0e-6        # b_x driven to zero
    # The read-back is substrate-only (no Ar atom exists in a pristine
    # half) but carries the full beam-declaring type map for the cascade.
    assert set(half.atoms.get_chemical_symbols()) == {"Si"}
    assert "Ar" in half.type_map


def test_read_standalone_half_round_trips_species(tmp_path):
    """read_standalone_half recovers positions and species from disk."""
    member = _si_si_member()
    handle_a, _, _ = build_halves(
        member, potential=None, scratch_directory=str(tmp_path))

    half = read_standalone_half(
        handle_a.data_file, handle_a.type_map, handle_a.identity)
    reference = ase_read(
        handle_a.data_file, format="lammps-data", atom_style="atomic",
        Z_of_type={2: 14})            # type 2 -> Si (Ar=1, Si=2 by symbol)
    assert len(half.atoms) == len(reference)
    assert len(half.atoms) > 0
    assert half.identity == "Si"


# ---------------------------------------------------------------------
# The live analyzer (§8.4): reduce the pull curves to the mechanical work
# of separation. Pure math on a synthetic bond-debond result.
# ---------------------------------------------------------------------

import numpy as np
from types import SimpleNamespace

import pytest

from sabsim.pipeline.exec_artifacts import (
    BondDebondResult,
    PressOutcome,
    PullOutcome,
    Structure,
)
from sabsim.pipeline.measures import MeasureStatus
from sabsim.pipeline.live_stages import run_analyzer_live


def _structure_with_area():
    """A Structure whose assembled pair has a 100 Å² lateral cell."""
    built = SimpleNamespace(
        atoms=SimpleNamespace(get_cell=lambda: np.diag([10.0, 10.0, 40.0])))
    return Structure(note="test", labeled_groups=(), built=built)


def test_analyzer_reports_the_slowest_separated_rung():
    """M1 is the slowest rate's work per area; the bond verdict rides along."""
    member = _si_si_member()
    # Two rungs; the SLOW one (rate 1) is the quasi-static estimate.
    fast = PullOutcome(
        rate_value=10.0, rate_unit="m/s", note="", complete=True,
        separation_index=2, grip_displacement=(0.0, 1.0, 2.0),
        force_vs_grip=(0.0, 2.0, 0.0))
    slow = PullOutcome(
        rate_value=1.0, rate_unit="m/s", note="", complete=True,
        separation_index=2, grip_displacement=(0.0, 1.0, 2.0),
        force_vs_grip=(0.0, 1.0, 0.0))
    bond = BondDebondResult(
        press=PressOutcome(bonded=True, note=""), reference_ok=True,
        pulls=(fast, slow))

    measures = run_analyzer_live(_structure_with_area(), bond, member)
    mechanical = measures.by_name("mechanical_work_of_separation")
    # Slow rung: trapezoid([0,1,0] over [0,1,2]) = 1.0 eV; /area 100 = 0.01.
    assert mechanical.status is MeasureStatus.OK
    assert mechanical.value == pytest.approx(0.01)
    assert measures.verdicts.bonded is True


def test_analyzer_unresolved_when_no_rung_separates():
    """No complete separation -> the mechanical measure is unresolved."""
    member = _si_si_member()
    incomplete = PullOutcome(
        rate_value=1.0, rate_unit="m/s", note="", complete=False)
    bond = BondDebondResult(
        press=PressOutcome(bonded=False, note="no contact"),
        reference_ok=False, pulls=(incomplete,))

    measures = run_analyzer_live(_structure_with_area(), bond, member)
    mechanical = measures.by_name("mechanical_work_of_separation")
    assert mechanical.status is MeasureStatus.UNRESOLVED
    assert mechanical.value is None
    assert measures.verdicts.bonded is False


# ---------------------------------------------------------------------
# The multi-rank file-handoff discipline (ARCHITECTURE.md §4.1).
# ---------------------------------------------------------------------

class _FakeCommunicator:
    """A stand-in MPI communicator that records what was asked of it.

    Real multi-rank behaviour cannot be exercised in a unit test — there
    is one process — so this fakes the two calls the discipline uses and
    records them, which is enough to prove that exactly one rank writes
    and that everyone waits afterwards.
    """

    def __init__(self, rank: int):
        self._rank = rank
        self.barriers = 0

    def Get_rank(self) -> int:
        return self._rank

    def Barrier(self) -> None:
        self.barriers += 1


def test_only_rank_zero_writes_a_handoff_file():
    """Rank 0 performs the write; every other rank must not."""
    writes = []

    writer = _FakeCommunicator(rank=0)
    _publish_file(writer, lambda: writes.append("wrote"))
    assert writes == ["wrote"]
    assert writer.barriers == 1, "the write must be published to peers"

    # A non-zero rank must NOT touch the file: several ranks writing the
    # same path at once is exactly the corruption this prevents.
    bystander = _FakeCommunicator(rank=3)
    _publish_file(bystander, lambda: writes.append("should not happen"))
    assert writes == ["wrote"]
    assert bystander.barriers == 1, (
        "a non-writing rank must still reach the barrier, or the ranks "
        "deadlock waiting for each other")


def test_serial_run_writes_without_a_communicator():
    """With no MPI at all the write still happens, and nothing blocks."""
    writes = []
    _publish_file(None, lambda: writes.append("wrote"))
    assert writes == ["wrote"]


# ---------------------------------------------------------------------
# Locating a member's crystal file (the CLI runs from the JOB dir).
# ---------------------------------------------------------------------

def test_shipped_cif_resolves_from_an_unrelated_directory(
        monkeypatch, tmp_path):
    """A repo-root-relative CIF is found from any working directory.

    The regression this guards actually happened: `sabsim run` makes the
    run's home the JOB directory, so the shipped example path
    'src/sabsim/structure/data/si_diamond.cif' was resolved against a
    directory nowhere near the repo and the run halted on a missing file
    before any physics started.
    """
    monkeypatch.chdir(tmp_path)
    resolved = _resolve_cif("src/sabsim/structure/data/si_diamond.cif")
    assert os.path.isfile(resolved)


def test_cif_beside_the_run_wins_over_the_shipped_copy(
        monkeypatch, tmp_path):
    """A CIF in the working directory is preferred (a user's own file)."""
    own = tmp_path / "src" / "sabsim" / "structure" / "data"
    own.mkdir(parents=True)
    (own / "si_diamond.cif").write_text("# the user's own crystal\n")
    monkeypatch.chdir(tmp_path)

    resolved = _resolve_cif("src/sabsim/structure/data/si_diamond.cif")
    assert resolved == str(own / "si_diamond.cif")


def test_missing_cif_names_every_place_it_looked(monkeypatch, tmp_path):
    """A file that is nowhere fails with the search path, not ENOENT."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError) as caught:
        _resolve_cif("no/such/crystal.cif")
    message = str(caught.value)
    assert "Looked in" in message
    assert str(tmp_path) in message, "the working directory must be listed"


def _dissimilar_member():
    """A Si/silica member built from CIFs that actually ship.

    The template's si-sio2 member names a beta-cristobalite CIF that is
    not created until the compound build lands, so this swaps the second
    wafer for the alpha-quartz file already in the tree. What it exists
    to exercise is the type map, not the lattice match: two wafers whose
    crystals contribute DIFFERENT elements.
    """
    silicon = _si_si_member()
    silica_wafer = replace(
        silicon.material.wafer_b,
        identity="SiO2",
        cif_source="src/sabsim/structure/data/sio2_alpha_quartz.cif",
        crystal_structure="alpha-quartz",
        surface_face=(0, 0, 1))
    return replace(
        silicon,
        material=replace(silicon.material, wafer_b=silica_wafer),
        material_domain="silicon-and-silica")


def test_both_halves_declare_the_member_species_union(tmp_path):
    """A silicon half in a Si/silica member still declares oxygen (§4.3).

    STRUCTURAL 1a puts one potential over the union of the pair's
    species, and §4.3 makes that a single global type map so a type id
    means the same element everywhere. Without it the silicon half would
    declare no oxygen type, and the (species, domain) force-model lookup
    of §4.8 could not resolve the member's declared domain for that half.
    """
    member = _dissimilar_member()
    handle_a, handle_b, _ = build_halves(
        member, potential=None, scratch_directory=str(tmp_path))

    # Identical maps on both sides — same elements, same id for each.
    assert handle_a.type_map == handle_b.type_map
    assert set(handle_a.type_map) == {"Ar", "O", "Si"}

    # Half A is the SILICON wafer: it declares oxygen but contains none.
    half_a = read_standalone_half(
        handle_a.data_file, handle_a.type_map, handle_a.identity)
    assert set(half_a.atoms.get_chemical_symbols()) == {"Si"}

    # Half B is the silica wafer and does contain both.
    half_b = read_standalone_half(
        handle_b.data_file, handle_b.type_map, handle_b.identity)
    assert set(half_b.atoms.get_chemical_symbols()) == {"O", "Si"}


def test_same_material_member_declares_only_its_own_species(tmp_path):
    """The union changes nothing for a same-material pair (no bloat)."""
    handle_a, _, _ = build_halves(
        _si_si_member(), potential=None, scratch_directory=str(tmp_path))
    assert set(handle_a.type_map) == {"Ar", "Si"}
