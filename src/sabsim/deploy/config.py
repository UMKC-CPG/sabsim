"""Read and validate the deployment rc file (PSEUDOCODE.md §14.1).

This module is ``load_deployment`` made real. It turns the machine-local
deployment TOML — the ``dev/templates/deployment_rc.toml`` an admin edits
— into the typed records PSEUDOCODE.md §14.1 defines, and it holds the
consumer to the SAME two disciplines the study-spec loader
(:mod:`sabsim.spec.loader`) does, because the rc is the study spec's only
sibling input (DESIGN.md §1.2):

* **No silent default (DESIGN.md §1.4, §14.1).** Every field the records
  need is pulled explicitly; a missing key is a loud stop that names what
  is absent, never a fallback the machinery invents. The deployment rc
  must never fill in "where to run" the way it must never fill in a
  physics knob — convenience lives in WRITING a complete file, not in a
  load-time guess.
* **Reject what cannot be executed (DESIGN.md §1.5, mirrored here).** A
  usage block that routes to a resource class the hardware section never
  defines cannot be run, so it is rejected at load with a message that
  says which block and which class — the same dangling-reference refusal
  the spec loader applies to a relation over a missing member.

The rc carries TWO concerns in one file (ARCHITECTURE.md §4.1): a
``[hardware]`` inventory (the per-cluster swap unit) and a ``[usage.*]``
map keyed by KIND OF MEMBER JOB — ``activate`` / ``bond`` / ``analyze``
(DESIGN.md §10.2). The seam between them is the word CLASS: a usage block
names an abstract resource class (``"cpu"`` / ``"gpu"``) and the hardware
section binds that class to this machine's real partition, so moving to a
new cluster rewrites ``[hardware]`` and leaves the usage map untouched.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


# How many hours one unit of a walltime figure is worth. The rc writes
# durations as ``{ value, unit }`` inline tables (e.g. 48 hours), and the
# §14.4 ceiling check compares two of them, so every accepted unit must
# reduce to one common measure. Hours is that measure because the rc's
# ceilings are written in hours; the rest are here so a site may state a
# short job in minutes or a long one in days without surprise.
_HOURS_PER_UNIT = {
    "h": 1.0, "hr": 1.0, "hour": 1.0, "hours": 1.0,
    "m": 1.0 / 60.0, "min": 1.0 / 60.0, "minute": 1.0 / 60.0,
    "minutes": 1.0 / 60.0,
    "s": 1.0 / 3600.0, "sec": 1.0 / 3600.0, "second": 1.0 / 3600.0,
    "seconds": 1.0 / 3600.0,
    "d": 24.0, "day": 24.0, "days": 24.0,
}


class DeploymentError(Exception):
    """The deployment rc is incomplete or cannot be executed.

    Raised with a message that names WHAT is wrong and WHERE, so the
    person editing the rc can fix it without reading this loader. It is
    the single failure type both disciplines above raise, matching the
    study-spec loader's one :class:`~sabsim.spec.loader.SpecificationError`.
    """


@dataclass(frozen=True)
class Duration:
    """A span of wall-clock time paired with the unit it is written in.

    The rc writes a walltime or a ceiling as a TOML inline table —
    ``{ value = 48.0, unit = "h" }`` — the same units-travel-with-values
    idiom the study spec uses for physical knobs (DESIGN.md §1.5). Frozen
    and defaulted-free so it cannot be built with a hole in it.
    """

    value: float
    unit: str

    def in_hours(self) -> float:
        """This duration expressed in hours, for the §14.4 ceiling check.

        Reduces to the one common measure so two durations written in
        different units still compare. An unrecognised unit is a loud
        stop, never a guess — the same no-silent-default rule the loader
        holds everywhere else.
        """
        factor = _HOURS_PER_UNIT.get(self.unit.lower())
        if factor is None:
            raise DeploymentError(
                f"walltime unit '{self.unit}' is not one this consumer "
                f"knows {sorted(set(_HOURS_PER_UNIT))}; state it in "
                f"hours, minutes, seconds, or days")
        return self.value * factor


@dataclass(frozen=True)
class Partition:
    """One ``[hardware.partitions.*]`` block — a real machine resource.

    A partition is what an abstract resource class binds to on THIS
    cluster (PSEUDOCODE.md §14.1). ``name`` is the scheduler's own
    partition name (e.g. ``"general"``); ``capacity`` carries whatever
    per-node counts the block stated (``cores_per_node``, ``gpus_per_node``,
    …) as plain numbers; ``max_walltime`` is the longest job the pool will
    accept — the ceiling the §14.4 walltime check compares against.
    """

    name: str
    capacity: dict[str, float]
    max_walltime: Duration


@dataclass(frozen=True)
class UsageBlock:
    """One ``[usage.*]`` block — how ONE kind of member job runs.

    Keyed in the rc by member job (``activate`` / ``bond`` / ``analyze``,
    DESIGN.md §10.2), a usage block names the abstract resource
    ``resource_class`` the hardware section resolves to a
    :class:`Partition`, the human-provided ``nodes``, ``tasks_per_node``
    (MPI ranks per node), and ``walltime`` for the job (PSEUDOCODE.md
    §14.1 — all chosen, never predicted, DESIGN.md §10.6), and the
    ``modules`` that job switches on (the
    per-kind tool list, DESIGN.md §10.5; the bond job's one deepmd engine,
    ARCHITECTURE.md §4.4).
    """

    resource_class: str
    nodes: int
    tasks_per_node: int
    walltime: Duration
    modules: tuple[str, ...]


@dataclass(frozen=True)
class DeploymentConfig:
    """The whole parsed rc (PSEUDOCODE.md §14.1, ARCHITECTURE.md §4.1).

    ``partitions`` is keyed by resource class (``"cpu"`` / ``"gpu"``) and
    ``usage`` by member-job kind (``activate`` / ``bond`` / ``analyze``);
    the two meet at :attr:`UsageBlock.resource_class`, which every usage
    block resolves against one of the partitions. ``module_paths`` are the
    extra ``module use`` roots the CPG modulefile tree needs before any
    ``module load`` (ARCHITECTURE.md §4.4).
    """

    cluster_name: str
    scheduler: str
    default_account: str
    module_paths: tuple[str, ...]
    partitions: dict[str, Partition]
    usage: dict[str, UsageBlock]

    def partition_for(self, job_kind: str) -> Partition:
        """The real partition ONE member job's usage block resolves to.

        Joins the two halves of the rc for a caller (the §14.4 writer, the
        §14.3 runner): look up the job's usage block, then resolve its
        resource class against the hardware partitions. A job kind with no
        usage block, or a usage block whose class names no partition, is a
        loud stop — the same executability refusal :func:`load_deployment`
        makes at load time, repeated here for a caller that reaches past
        the parsed map by job name.
        """
        block = self.usage.get(job_kind)
        if block is None:
            raise DeploymentError(
                f"no [usage.{job_kind}] block in the deployment rc; the "
                f"jobs it must define are {sorted(self.usage)}")
        partition = self.partitions.get(block.resource_class)
        if partition is None:
            raise DeploymentError(
                f"[usage.{job_kind}] routes to resource class "
                f"'{block.resource_class}', which no "
                f"[hardware.partitions.*] defines "
                f"{sorted(self.partitions)}")
        return partition


# ---------------------------------------------------------------------
# Small helpers that pull required values and enforce completeness, one
# per shape the records need. Every field is pulled through one of these,
# so an omission surfaces as a clear DeploymentError, not a raw KeyError
# — the same mechanism the study-spec loader uses (spec/loader.py).
# ---------------------------------------------------------------------

def _require(table: dict, key: str, context: str) -> object:
    """Return ``table[key]`` or reject the rc if the key is absent.

    ``context`` names the location (e.g. ``"[usage.bond]"``) so the error
    points the editor straight at the missing field. The concrete face of
    "no silent default" (DESIGN.md §1.4, §14.1).
    """
    if not isinstance(table, dict):
        raise DeploymentError(
            f"{context}: expected a table of settings, got {table!r}")
    if key not in table:
        raise DeploymentError(
            f"{context}: missing required key '{key}'")
    return table[key]


def _require_duration(table: dict, key: str, context: str) -> Duration:
    """Pull a required ``{ value, unit }`` inline table as a Duration.

    A walltime carries its unit (DESIGN.md §1.5), so a bare number, or a
    table missing ``value`` or ``unit``, is rejected rather than silently
    read as some assumed unit.
    """
    raw = _require(table, key, context)
    where = f"{context} -> {key}"
    if not isinstance(raw, dict):
        raise DeploymentError(
            f"{where}: expected a {{ value, unit }} table, got a bare "
            f"value — a walltime carries its unit (§1.5)")
    value = _require(raw, "value", where)
    unit = _require(raw, "unit", where)
    return Duration(value=float(value), unit=str(unit))


def _require_str_list(table: dict, key: str, context: str) -> tuple:
    """Pull a required list of strings as a tuple (module lists, roots).

    An empty list is allowed and meaningful — the analyze job loads no
    science module in v1 (DESIGN.md §10.5) — but the KEY must be present,
    so "no modules" is stated as ``[]`` rather than left to a default.
    """
    raw = _require(table, key, context)
    if not isinstance(raw, list):
        raise DeploymentError(
            f"{context} -> {key}: expected a list, got {raw!r}")
    return tuple(str(item) for item in raw)


# ---------------------------------------------------------------------
# Deserialize: map the on-disk TOML layout onto the §14.1 records. This
# is where the concrete file shape meets the schema field names, so the
# reader can see exactly how one becomes the other.
# ---------------------------------------------------------------------

def _partition_from_table(
        resource_class: str, table: dict, context: str) -> Partition:
    """Build one Partition from its ``[hardware.partitions.<class>]``.

    ``name`` and ``max_walltime`` are named fields; every OTHER key is
    read as a per-node capacity number (``cores_per_node``,
    ``gpus_per_node``, …), so a site may state whatever counts its
    partition has without this loader enumerating them all.
    """
    name = str(_require(table, "name", context))
    max_walltime = _require_duration(table, "max_walltime", context)
    capacity = {
        key: float(value)
        for key, value in table.items()
        if key not in ("name", "max_walltime")}
    return Partition(
        name=name, capacity=capacity, max_walltime=max_walltime)


def _usage_from_table(
        job_kind: str, table: dict, context: str) -> UsageBlock:
    """Build one UsageBlock from its ``[usage.<job_kind>]``.

    The rc's ``partition`` key names the abstract resource CLASS the usage
    block routes to (resolved to a real partition by the hardware
    section), which is why it is stored as :attr:`UsageBlock.resource_class`
    and not as a partition object here — the join happens later, once both
    halves are parsed (§14.4).
    """
    return UsageBlock(
        resource_class=str(_require(table, "partition", context)),
        nodes=int(_require(table, "nodes", context)),
        tasks_per_node=int(_require(table, "tasks_per_node", context)),
        walltime=_require_duration(table, "walltime", context),
        modules=_require_str_list(table, "modules", context),
    )


def _reject_if_usage_class_undefined(
        config: DeploymentConfig) -> None:
    """Reject a usage block routing to a class no partition defines.

    A usage block whose ``resource_class`` names no partition cannot be
    executed — there is no machine to send it to — so it is refused at
    load, naming the block and the dangling class. This is the deployment
    twin of the study loader's dangling-relation refusal (§1.5): a
    completeness check that needs the WHOLE file, so it runs after both
    halves are parsed rather than field by field.
    """
    defined = set(config.partitions)
    for job_kind, block in config.usage.items():
        if block.resource_class not in defined:
            raise DeploymentError(
                f"[usage.{job_kind}] routes to resource class "
                f"'{block.resource_class}', which no "
                f"[hardware.partitions.*] defines {sorted(defined)}")


# ---------------------------------------------------------------------
# The public entry point.
# ---------------------------------------------------------------------

def load_deployment(rc_path: str | Path) -> DeploymentConfig:
    """Load and validate the deployment rc at ``rc_path`` (§14.1).

    Reads the TOML file, builds the typed :class:`DeploymentConfig`, and
    applies both disciplines: every field is pulled explicitly, so an
    incomplete rc fails while its keys are read; and a usage block routing
    to an undefined resource class fails the executability check. Returns
    the validated config, or raises :class:`DeploymentError` naming the
    first problem.
    """
    path = Path(rc_path)
    with path.open("rb") as rc_file:
        raw = tomllib.load(rc_file)

    hardware = _require(raw, "hardware", "top level")
    partitions_table = _require(
        hardware, "partitions", "[hardware]")
    partitions = {
        resource_class: _partition_from_table(
            resource_class, table,
            f"[hardware.partitions.{resource_class}]")
        for resource_class, table in partitions_table.items()}

    usage_table = _require(raw, "usage", "top level")
    usage = {
        job_kind: _usage_from_table(
            job_kind, table, f"[usage.{job_kind}]")
        for job_kind, table in usage_table.items()}

    config = DeploymentConfig(
        cluster_name=str(_require(hardware, "cluster_name", "[hardware]")),
        scheduler=str(_require(hardware, "scheduler", "[hardware]")),
        default_account=str(_require(
            hardware, "default_account", "[hardware]")),
        module_paths=_require_str_list(
            hardware, "module_paths", "[hardware]"),
        partitions=partitions,
        usage=usage,
    )

    _reject_if_usage_class_undefined(config)
    return config
