"""Mid-chain handoff artifacts on disk (PSEUDOCODE.md §14.6).

A pair's four deployment jobs (prep_surf1 and prep_surf2 → bond →
analysis, DESIGN.md §10.2, revised 2026-08-30) are submitted separately,
so each starts in a FRESH process that did not inherit the warm
in-memory object the whole-chain run passes stage to stage. This module
is the ``write_artifact`` / ``read_artifact`` seam §14.3 delegated: it
turns the mid-chain records — the :class:`~sabsim.pipeline.
exec_artifacts.ActivatedHalf` each prep job hands bond, the assembled
:class:`~sabsim.pipeline.exec_artifacts.Structure` bond keeps for
analysis, and the :class:`~sabsim.pipeline.exec_artifacts.
BondDebondResult` the bond job hands analysis — into COMPLETE on-disk
artifacts a later job reconstructs from files alone. Each lands in the
DELIVERABLES folder of the stage that made it (``<project>/<stage
folder>/``, ARCHITECTURE.md §1), never on scratch.

Each artifact takes the §14.6 shape — small things INLINE, large things
BY REFERENCE, the same split §3's trajectory uses:

* a **readable manifest** (TOML) carrying the scalars, geometry, and
  per-rate fields, plus the NAMES of any bulky payloads. TOML keeps the
  manifest consistent with the project and rc files a human reads and
  edits (§14.6). The standard library reads it with ``tomllib``; since
  ``tomllib`` cannot WRITE, this module emits the few value types a
  manifest uses through a small hand-rolled writer (:func:`_dump_toml`).
  It stays human-inspectable, and it is NOT an opaque pickle of the record;
* the **payloads**, each its own file: the assembled pair's atoms (an
  extended-XYZ file that faithfully round-trips positions, species, cell,
  AND the per-wafer tags the press/pull driver carves grips from) and the
  LAMMPS data file the engine loads.

The atoms cannot be recovered from the LAMMPS data file alone — it stores
type ids, not species, and no ASE tags — which is exactly why the
extended-XYZ payload exists (DESIGN.md §2.6: the measured labeled groups
must TRAVEL, they cannot be re-derived).

**MPI note.** These functions do plain, serial file I/O
(``parallel=False`` on every ASE call, the §4.1 serial-IO discipline). A
caller running under MPI must guard each WRITE to one rank and publish it
with a barrier before the other ranks read (the same rank-0-writes /
all-ranks-read pattern the live stages use); the READ side is per-rank by
construction.
"""

from __future__ import annotations

import json
import os
import tomllib

import numpy as np
from dataclasses import asdict
from pathlib import Path

from ase.io import read as ase_read
from ase.io import write as ase_write

from sabsim.deploy.registry import (
    ACTIVATED_HALF,
    ASSEMBLED_PAIR,
    MEASURE_VECTOR,
    PULL_RESULTS,
)
from sabsim.pipeline.exec_artifacts import (
    ActivatedHalf,
    BondDebondResult,
    PressOutcome,
    PullOutcome,
    SharedCell,
    Slab,
    Structure,
    StageLedger,
)
from sabsim.structure.slab_builder import (
    BuiltPair,
    SurfaceMatch,
    write_lammps_data,
)


class HandoffError(Exception):
    """A handoff artifact is missing, incomplete, or unreadable.

    Raised when a job is asked to start from an artifact that was never
    written or has lost a part it needs — a loud stop that names the
    artifact and the folder, so a broken hand-off between two submissions
    fails readably rather than deep inside a stage.
    """


# The on-disk names each artifact owns inside its stage folder. The
# artifact's LOGICAL name (from the registry) maps to one manifest plus
# any payloads; keeping the filenames here, in one place, is what lets a
# reader open a stage folder and recognise each hand-off by sight.
_ACTIVATED_HALF_MANIFEST = "activated_half.manifest.toml"
_ACTIVATED_HALF_ATOMS = "activated_half.extxyz"
_ASSEMBLED_PAIR_MANIFEST = "assembled_pair.manifest.toml"
_ASSEMBLED_PAIR_ATOMS = "assembled_pair.atoms.extxyz"
_ASSEMBLED_PAIR_DATA = "assembled_pair.data"
_PULL_RESULTS_MANIFEST = "pull_results.manifest.toml"
_MEASURE_VECTOR_FILE = "measure_vector.toml"


# ---------------------------------------------------------------------
# ACTIVATED_HALF — each prep job writes ONE into its own prep folder; the
# bond job reads BOTH (§14.2, §14.6, revised 2026-08-30). The healed
# atoms travel as an extended-XYZ payload (species, cell, and the wafer
# tag round-trip); the verdict, the heal step, and the shared cell the
# half was cut on travel in the manifest, because the bond job cannot
# re-derive any of them from the atoms.
# ---------------------------------------------------------------------

def write_activated_half(directory, half: ActivatedHalf) -> None:
    """Write one healed, gated half as a complete artifact (§14.6).

    Copies the healed half's atoms file into ``directory`` under the
    artifact's own payload name (the live activation writes it into the
    run's working folder on scratch; the deliverable must not point
    there) and writes the manifest beside it. A W0 placeholder half has
    no atoms file (``slab.data_file`` is None): then only the manifest
    is written, and the read side returns a slab with no file, which is
    exactly what the placeholder assembly expects.
    """
    import shutil
    home = Path(directory)
    manifest = {
        "identity": half.slab.identity,
        "note": half.slab.note,
        "wafer_tag": int(half.wafer_tag),
        "species": sorted(half.slab.species),
        "heal_start_step": half.slab.heal_start_step,
        "run_id": half.run_id,
        "shared": {
            "note": half.shared.note,
            "residual_strain": float(half.shared.residual_strain),
            "match_area": float(half.shared.match_area),
            "is_identity": bool(half.shared.is_identity),
        },
    }
    if half.slab.data_file is not None:
        source = Path(half.slab.data_file)
        target = home / _ACTIVATED_HALF_ATOMS
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        manifest["atoms_file"] = _ACTIVATED_HALF_ATOMS
    if half.verdict is not None:
        manifest["verdict"] = _activation_to_dict(half.verdict)
    _write_toml(home / _ACTIVATED_HALF_MANIFEST, manifest)


def read_activated_half(directory) -> ActivatedHalf:
    """Reconstruct one prep job's deliverable from its folder (§14.6).

    The inverse of :func:`write_activated_half`. A manifest that names
    an atoms payload which is not there is an incomplete artifact and a
    loud stop; a manifest with no payload at all is the W0 placeholder.
    """
    home = Path(directory)
    manifest = _read_manifest(home / _ACTIVATED_HALF_MANIFEST,
                              ACTIVATED_HALF, home)
    data_file = None
    if "atoms_file" in manifest:
        atoms_path = home / manifest["atoms_file"]
        if not atoms_path.is_file():
            raise HandoffError(
                f"{ACTIVATED_HALF} in {home} is missing its payload "
                f"'{atoms_path.name}' — the artifact is incomplete")
        data_file = str(atoms_path)
    shared = manifest["shared"]
    heal_step = manifest.get("heal_start_step")
    slab = Slab(
        identity=manifest["identity"], note=manifest["note"],
        data_file=data_file,
        species=frozenset(manifest.get("species", [])),
        heal_start_step=(int(heal_step) if heal_step is not None
                         else None))
    return ActivatedHalf(
        slab=slab,
        verdict=_activation_from_dict(manifest.get("verdict")),
        wafer_tag=int(manifest["wafer_tag"]),
        shared=SharedCell(
            note=shared["note"],
            residual_strain=float(shared["residual_strain"]),
            match_area=float(shared["match_area"]),
            is_identity=bool(shared["is_identity"])),
        run_id=str(manifest.get("run_id", "")))


# How closely two halves' lateral cells must agree, in Å, to count as
# having been built for each other. The build is deterministic, so two
# preps of the same project agree to round-off; anything larger means a
# different cell (a different project, a re-tuned knob, another seed of
# the matcher) and the assembly must refuse.
_CELL_AGREEMENT_TOLERANCE = 1.0e-6


def check_shared_cells_agree(half_a: ActivatedHalf,
                             half_b: ActivatedHalf) -> None:
    """Refuse two halves that were not built in the same shared cell.

    The bond job's first duty (DESIGN.md §10.2, revised 2026-08-30):
    the two prep jobs each solved the coincidence cell for themselves,
    so before stacking the halves the bond job checks that they agree —
    the match provenance on both manifests, and, when both carry atoms,
    the in-plane cell vectors of the two healed halves. A disagreement is
    a loud :class:`HandoffError` naming what differs, never a silently
    incommensurate interface.
    """
    if half_a.wafer_tag == half_b.wafer_tag:
        raise HandoffError(
            f"both activated halves carry wafer tag "
            f"{half_a.wafer_tag}; bond needs one bottom (A) and one "
            f"top (B) half")
    cell_a, cell_b = half_a.shared, half_b.shared
    for field_name in ("residual_strain", "match_area", "is_identity"):
        value_a = getattr(cell_a, field_name)
        value_b = getattr(cell_b, field_name)
        if isinstance(value_a, float):
            same = abs(value_a - value_b) <= _CELL_AGREEMENT_TOLERANCE
        else:
            same = value_a == value_b
        if not same:
            raise HandoffError(
                f"the two activated halves were not built in the same "
                f"shared cell: {field_name} is {value_a!r} for half A "
                f"and {value_b!r} for half B. Prepare both surfaces "
                f"from the same project file before bonding.")
    if half_a.slab.data_file is None or half_b.slab.data_file is None:
        return                           # placeholders carry no atoms
    atoms_a = ase_read(half_a.slab.data_file, format="extxyz",
                       parallel=False)
    atoms_b = ase_read(half_b.slab.data_file, format="extxyz",
                       parallel=False)
    lateral_a = np.asarray(atoms_a.get_cell())[:2, :2]
    lateral_b = np.asarray(atoms_b.get_cell())[:2, :2]
    if not np.allclose(lateral_a, lateral_b,
                       atol=_CELL_AGREEMENT_TOLERANCE):
        raise HandoffError(
            f"the two activated halves have different in-plane cells:\n"
            f"  half A: {lateral_a.tolist()}\n"
            f"  half B: {lateral_b.tolist()}\n"
            f"Prepare both surfaces from the same project file before "
            f"bonding.")


# ---------------------------------------------------------------------
# ASSEMBLED_PAIR — the bond job writes it after assembling the two
# halves, and analysis reads it back (§14.2, §14.6). The atoms travel
# as an extended-XYZ payload (tags preserved); the geometry the driver
# needs travels in the manifest.
# ---------------------------------------------------------------------

def write_assembled_pair(scratch_directory, structure: Structure) -> None:
    """Write the assembled pair as a complete on-disk artifact (§14.6).

    Writes three files under ``scratch_directory``: the atoms as an
    extended-XYZ payload (species, cell, and the per-wafer tags all
    round-trip), the LAMMPS data file the bond engine will load, and a
    JSON manifest of the labeled-group geometry the bond job cannot
    re-derive from the atoms — the interface plane, the two per-wafer
    z-ranges, the clash adjustment, the type map, and the coincidence
    match provenance (DESIGN.md §2.6, §2.1).

    ``structure.built`` must be the live :class:`BuiltPair` the real
    assembly produced (not the W0 placeholder's ``None``); a structure
    with no ``built`` cannot be handed across a job boundary, so that is a
    loud stop rather than a half-written artifact.
    """
    scratch = Path(scratch_directory)
    built = structure.built
    if built is None:
        raise HandoffError(
            f"cannot write {ASSEMBLED_PAIR} for a structure with no built "
            f"pair (the W0 placeholder carries built=None); a cross-job "
            f"hand-off needs the assembled geometry (scratch {scratch})")

    # The atoms payload: extended-XYZ faithfully round-trips positions,
    # species, cell, pbc, and the WAFER_A/WAFER_B tags the driver reads.
    ase_write(
        str(scratch / _ASSEMBLED_PAIR_ATOMS), built.atoms,
        format="extxyz", parallel=False)

    # The engine payload: the LAMMPS data file the bond job's press loads.
    write_lammps_data(built, str(scratch / _ASSEMBLED_PAIR_DATA))

    manifest = {
        "note": structure.note,
        "labeled_groups": list(structure.labeled_groups),
        "atoms_file": _ASSEMBLED_PAIR_ATOMS,
        "data_file": _ASSEMBLED_PAIR_DATA,
        "built": {
            "interface_z": float(built.interface_z),
            "wafer_a_z_range": list(built.wafer_a_z_range),
            "wafer_b_z_range": list(built.wafer_b_z_range),
            "initial_gap_adjustment": float(built.initial_gap_adjustment),
            "type_map": {str(k): int(v) for k, v in built.type_map.items()},
            "match": {
                "residual_strain": float(built.match.residual_strain),
                "match_area": float(built.match.match_area),
                "is_identity": bool(built.match.is_identity),
            },
        },
    }
    # The §3.5 verdict each half arrived with, and the step its heal began
    # at (§10.1, 2026-08-28), ride the manifest so the bond and analyze
    # jobs — which read only this artifact — can report the activation
    # that produced the surfaces, and the bootstrap harvest can tell the
    # healed frames of the activate movie from the cascade-hot ones.
    activation = {
        role: _activation_to_dict(verdict)
        for role, verdict in (("a", structure.activation_a),
                              ("b", structure.activation_b))
        if verdict is not None}
    if activation:
        manifest["activation"] = activation
    heal_steps = {
        role: int(step)
        for role, step in (("a", structure.heal_start_step_a),
                           ("b", structure.heal_start_step_b))
        if step is not None}
    if heal_steps:
        manifest["heal_start_step"] = heal_steps
    _write_toml(scratch / _ASSEMBLED_PAIR_MANIFEST, manifest)


def read_assembled_pair(scratch_directory) -> Structure:
    """Reconstruct the assembled-pair Structure from its artifact (§14.6).

    The inverse of :func:`write_assembled_pair`: reads the atoms back from
    the extended-XYZ payload (tags and species intact), rebuilds the
    :class:`BuiltPair` from the manifest's geometry, and returns the
    :class:`Structure` the bond and analysis jobs run on — identical in
    shape to the one the whole-chain run passes in memory, so the stages
    consume it without knowing it crossed a job boundary. This is the
    Approach-C re-read the ``Structure.built`` comment forecast
    (ARCHITECTURE.md §4.3).
    """
    scratch = Path(scratch_directory)
    manifest = _read_manifest(scratch / _ASSEMBLED_PAIR_MANIFEST,
                              ASSEMBLED_PAIR, scratch)

    atoms_path = scratch / manifest["atoms_file"]
    data_path = scratch / manifest["data_file"]
    for required in (atoms_path, data_path):
        if not required.is_file():
            raise HandoffError(
                f"{ASSEMBLED_PAIR} in {scratch} is missing its payload "
                f"'{required.name}' — the artifact is incomplete")

    atoms = ase_read(str(atoms_path), format="extxyz", parallel=False)
    built_fields = manifest["built"]
    match = built_fields["match"]
    built = BuiltPair(
        atoms=atoms,
        interface_z=float(built_fields["interface_z"]),
        wafer_a_z_range=tuple(built_fields["wafer_a_z_range"]),
        wafer_b_z_range=tuple(built_fields["wafer_b_z_range"]),
        type_map={str(k): int(v)
                  for k, v in built_fields["type_map"].items()},
        match=SurfaceMatch(
            residual_strain=float(match["residual_strain"]),
            match_area=float(match["match_area"]),
            is_identity=bool(match["is_identity"])),
        initial_gap_adjustment=float(
            built_fields["initial_gap_adjustment"]),
    )
    activation = manifest.get("activation", {})
    heal_steps = manifest.get("heal_start_step", {})
    return Structure(
        note=manifest["note"],
        labeled_groups=tuple(manifest["labeled_groups"]),
        data_file=str(data_path),
        built=built,
        activation_a=_activation_from_dict(activation.get("a")),
        activation_b=_activation_from_dict(activation.get("b")),
        heal_start_step_a=(int(heal_steps["a"]) if "a" in heal_steps
                           else None),
        heal_start_step_b=(int(heal_steps["b"]) if "b" in heal_steps
                           else None))


# ---------------------------------------------------------------------
# PULL_RESULTS — the bond job writes it, the analysis job reads it (§14.2,
# §14.6). All fields are primitives and float sequences, so the whole
# result rides in the readable manifest; the per-atom trajectories are a
# SEPARATE §3 FrameSetRef payload on scratch and are not duplicated here.
# ---------------------------------------------------------------------

def write_pull_results(
        scratch_directory, bond_debond: BondDebondResult) -> None:
    """Write the press/pull result as a readable manifest (§14.6).

    The press verdict, the reference flag, and each rung's reduced fields
    and curves (grip displacement and resisting force per recorded frame)
    are all small numeric data, so they sit INLINE in one JSON manifest —
    the small-inline case of the §14.6 rule. A curve that ever grew large
    would move to its own payload file without changing this contract; in
    v1 they are tens of kilobytes, so they stay inline.
    """
    scratch = Path(scratch_directory)
    press_table = {
        "bonded": bool(bond_debond.press.bonded),
        "note": bond_debond.press.note,
    }
    # The stage ledger (§9.3, DESIGN §5.5/§5.7): the step each press and
    # settle phase began or ended at, so a reader of the press movie keys
    # every frame to its phase. Markers of phases that never ran are
    # simply absent (TOML has no null).
    ledger = bond_debond.press.stage_steps
    if ledger is not None:
        stage_steps = {
            name: int(step)
            for name, step in asdict(ledger).items() if step is not None}
        if stage_steps:
            press_table["stage_steps"] = stage_steps
    manifest = {
        "run_id": bond_debond.run_id,
        "press": press_table,
        "reference_ok": bool(bond_debond.reference_ok),
        "pulls": [_pull_to_dict(pull) for pull in bond_debond.pulls],
    }
    _write_toml(scratch / _PULL_RESULTS_MANIFEST, manifest)


def read_pull_results(scratch_directory) -> BondDebondResult:
    """Reconstruct the BondDebondResult from its manifest (§14.6).

    The inverse of :func:`write_pull_results`: rebuilds the press outcome,
    the reference flag, and every pull rung — including the reduced curves
    the analyzer integrates — so the analysis job reads exactly the result
    the bond job produced.
    """
    scratch = Path(scratch_directory)
    manifest = _read_manifest(scratch / _PULL_RESULTS_MANIFEST,
                              PULL_RESULTS, scratch)
    press = manifest["press"]
    stage_steps = press.get("stage_steps")
    ledger = (StageLedger(**{name: int(step)
                            for name, step in stage_steps.items()})
              if stage_steps else None)
    return BondDebondResult(
        press=PressOutcome(
            bonded=bool(press["bonded"]), note=press["note"],
            stage_steps=ledger),
        reference_ok=bool(manifest["reference_ok"]),
        pulls=tuple(_pull_from_dict(pull) for pull in manifest["pulls"]),
        run_id=str(manifest.get("run_id", "")),
    )


def _activation_to_dict(verdict) -> dict:
    """One surface's §3.5 verdict as a small table (curves left out)."""
    metrics = {}
    for name, metric in verdict.per_metric.items():
        threshold = metric.threshold
        if isinstance(threshold, (tuple, list)):
            threshold = [float(t) for t in threshold]
        metrics[name] = {
            "measured": metric.measured,
            "threshold": threshold,
            "reference": metric.reference,
            "passed": bool(metric.passed),
        }
    return {
        "passed": bool(verdict.passed),
        "activated_depth": float(verdict.activated_depth),
        "reason": verdict.reason,
        "metrics": metrics,
    }


def _activation_from_dict(data):
    """Rebuild an ActivationVerdict from its table, or None if absent."""
    if data is None:
        return None
    from sabsim.driver.activation_gate import (
        ActivationVerdict,
        MetricVerdict,
    )
    per_metric = {}
    for name, metric in data.get("metrics", {}).items():
        threshold = metric.get("threshold")
        if isinstance(threshold, list):
            threshold = tuple(threshold)
        per_metric[name] = MetricVerdict(
            name=name, measured=metric.get("measured"),
            reference=metric.get("reference", ""), threshold=threshold,
            passed=bool(metric["passed"]))
    return ActivationVerdict(
        passed=bool(data["passed"]),
        activated_depth=float(data["activated_depth"]),
        per_metric=per_metric, reason=data.get("reason", ""))


def _pull_to_dict(pull: PullOutcome) -> dict:
    """Serialize one pull rung to a plain dict (all fields explicit)."""
    return {
        "rate_value": float(pull.rate_value),
        "rate_unit": pull.rate_unit,
        "note": pull.note,
        "complete": bool(pull.complete),
        "separation_index": pull.separation_index,
        "grip_displacement": [float(x) for x in pull.grip_displacement],
        "force_vs_grip": [float(x) for x in pull.force_vs_grip],
        "atoms_conserved": bool(pull.atoms_conserved),
        "bridges_at_separation": pull.bridges_at_separation,
        "resumed": bool(pull.resumed),
        "override_used": bool(pull.override_used),
    }


def _pull_from_dict(data: dict) -> PullOutcome:
    """Rebuild one pull rung from its serialized dict."""
    # separation_index and bridges_at_separation are None for a pull that
    # never separated; TOML omits a null key, so a MISSING key reads back
    # as None (``.get``), which is exactly the un-separated case.
    return PullOutcome(
        rate_value=float(data["rate_value"]),
        rate_unit=data["rate_unit"],
        note=data["note"],
        complete=bool(data["complete"]),
        separation_index=data.get("separation_index"),
        grip_displacement=tuple(data["grip_displacement"]),
        force_vs_grip=tuple(data["force_vs_grip"]),
        atoms_conserved=bool(data["atoms_conserved"]),
        bridges_at_separation=data.get("bridges_at_separation"),
        resumed=bool(data["resumed"]),
        override_used=bool(data["override_used"]),
    )


# ---------------------------------------------------------------------
# MEASURE_VECTOR — the analysis job writes it (§14.2). It is the LAST
# artifact in the chain, so no later job reads it back; only a write side
# is needed. The shape is the §6.6 machine-readable record.
# ---------------------------------------------------------------------

def write_measure_vector(directory, pair_result) -> None:
    """Write the analysis job's measure vector as the §4 record (§6.6).

    Serializes the pair's measures, press verdicts, provenance, and gate
    verdict to a TOML document in the analysis folder — the terminal
    artifact of the pair chain (DESIGN.md §6.6). Reuses the sequencer's
    own record builder so the on-disk shape matches the one the project
    report emits.
    """
    from sabsim.pipeline.sequencer import _pair_to_record

    _write_toml(Path(directory) / _MEASURE_VECTOR_FILE,
                _pair_to_record(pair_result))


# ---------------------------------------------------------------------
# The name-keyed façade §14.6 names: write_artifact / read_artifact. The
# run selector calls these with a registry artifact name, so it never
# hard-codes which serializer belongs to which hand-off.
# ---------------------------------------------------------------------

def write_artifact(scratch_directory, name: str, record) -> None:
    """Write ``record`` as the artifact called ``name`` (§14.6, §14.3).

    Dispatches on the registry artifact name so the caller states WHICH
    hand-off it is writing, not HOW. An unknown name is a loud stop.
    """
    if name == ACTIVATED_HALF:
        write_activated_half(scratch_directory, record)
    elif name == ASSEMBLED_PAIR:
        write_assembled_pair(scratch_directory, record)
    elif name == PULL_RESULTS:
        write_pull_results(scratch_directory, record)
    elif name == MEASURE_VECTOR:
        write_measure_vector(scratch_directory, record)
    else:
        writable = [ACTIVATED_HALF, ASSEMBLED_PAIR, PULL_RESULTS,
                    MEASURE_VECTOR]
        raise HandoffError(
            f"no writer for artifact '{name}'; the mid-chain artifacts "
            f"are {writable}")


def read_artifact(scratch_directory, name: str):
    """Reconstruct the artifact called ``name`` from disk (§14.6, §14.3).

    Dispatches on the registry artifact name. Only the three mid-chain
    hand-offs are readable; the terminal MEASURE_VECTOR is write-only in
    v1 (no later job reads it), so asking to read it is a loud stop.
    """
    if name == ACTIVATED_HALF:
        return read_activated_half(scratch_directory)
    if name == ASSEMBLED_PAIR:
        return read_assembled_pair(scratch_directory)
    if name == PULL_RESULTS:
        return read_pull_results(scratch_directory)
    raise HandoffError(
        f"no reader for artifact '{name}'; the readable mid-chain "
        f"artifacts are {[ACTIVATED_HALF, ASSEMBLED_PAIR, PULL_RESULTS]}")


# ---------------------------------------------------------------------
# The readable manifest — read with tomllib, written with a small TOML
# emitter. tomllib reads TOML but cannot write it, so this module emits
# by hand the few value types a manifest uses (scalars, scalar arrays,
# nested tables, and arrays of tables). Staying with TOML keeps a manifest
# consistent with the project and rc files a human reads (§14.6).
# ---------------------------------------------------------------------

def _write_toml(path: Path, document: dict) -> None:
    """Write ``document`` as a readable TOML manifest."""
    with path.open("w", encoding="utf-8") as handle:
        handle.write(_dump_toml(document))


def _read_manifest(path: Path, artifact_name: str, scratch) -> dict:
    """Read a manifest, turning a missing file into a clear HandoffError.

    A job asked to start from an artifact whose manifest is absent never
    ran its predecessor (or ran it against a different scratch); saying so
    by name is far clearer than a bare ``FileNotFoundError`` surfacing
    later inside a stage.
    """
    if not path.is_file():
        raise HandoffError(
            f"no {artifact_name} artifact in {scratch}: its manifest "
            f"'{path.name}' is missing. Run the job that writes it before "
            f"the job that reads it (§10.2 submission order).")
    with path.open("rb") as handle:
        return tomllib.load(handle)


# The characters a TOML BARE key may use; any other key is quoted. Every
# manifest key here is bare-safe (field names, element symbols), but the
# guard keeps the emitter honest if a stranger key ever appears.
_BARE_KEY_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")


def _dump_toml(document: dict) -> str:
    """Emit ``document`` as TOML text (the hand-rolled write side).

    Handles exactly what a manifest holds: scalars (string, int, float,
    bool), arrays of scalars, nested tables (a dict), and arrays of tables
    (a list of dicts). A ``None`` value is OMITTED — TOML has no null, so
    an absent key is how "no value" is written, and the read side maps a
    missing key back to ``None`` (e.g. a pull that never separated has no
    separation index). Table headers follow their parent's scalars, as
    TOML requires.
    """
    lines: list = []
    _emit_body(document, (), lines)
    text = "\n".join(lines).strip()
    return f"{text}\n" if text else ""


def _emit_body(table: dict, prefix: tuple, lines: list) -> None:
    """Emit one table's keys: scalars first, then nested/array tables.

    ``prefix`` is the dotted path to this table (empty at the root). The
    scalars-before-subtables order is not cosmetic: once a ``[header]`` is
    written every following key belongs to it, so a scalar emitted after a
    subtable would silently land in the wrong table.
    """
    scalars, subtables, table_arrays = [], [], []
    for key, value in table.items():
        if value is None:
            continue                       # TOML has no null; omit the key
        if isinstance(value, dict):
            subtables.append((key, value))
        elif _is_table_array(value):
            table_arrays.append((key, value))
        else:
            scalars.append((key, value))

    for key, value in scalars:
        lines.append(f"{_fmt_key(key)} = {_fmt_value(value)}")
    for key, value in subtables:
        lines.append("")
        lines.append(f"[{_dotted(prefix + (key,))}]")
        _emit_body(value, prefix + (key,), lines)
    for key, value in table_arrays:
        for item in value:
            lines.append("")
            lines.append(f"[[{_dotted(prefix + (key,))}]]")
            _emit_body(item, prefix + (key,), lines)


def _is_table_array(value) -> bool:
    """True for a NON-EMPTY list of dicts — an array of tables.

    An empty list is not a table array; it is an empty scalar array and is
    emitted inline as ``[]``.
    """
    return (isinstance(value, list) and len(value) > 0
            and all(isinstance(item, dict) for item in value))


def _dotted(prefix: tuple) -> str:
    """Join a table path into a dotted TOML header name."""
    return ".".join(_fmt_key(part) for part in prefix)


def _fmt_key(key: str) -> str:
    """A bare TOML key where possible, else a quoted one."""
    if key and all(character in _BARE_KEY_CHARS for character in key):
        return key
    return json.dumps(key)             # a quoted key, JSON escaping serves


def _fmt_value(value) -> str:
    """Render one scalar or scalar array as a TOML value.

    ``bool`` is checked before ``int`` because it is an int subclass in
    Python, and a boolean must read as ``true``/``false``, not ``1``/``0``.
    Strings reuse JSON escaping, which produces a valid TOML basic string.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)             # round-trip-faithful float text
    if isinstance(value, str):
        return json.dumps(value)       # JSON escaping is valid TOML basic
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_fmt_value(item) for item in value) + "]"
    raise HandoffError(
        f"cannot serialize {value!r} to a TOML manifest value")
