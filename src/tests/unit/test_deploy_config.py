"""Unit tests for the deployment rc loader (sabsim.deploy.config).

These pin the two disciplines the loader enforces (PSEUDOCODE.md §14.1,
DESIGN.md §1.4/§1.5): the real ``deployment_rc.toml`` template loads and
parses to the §14.1 records with the values landing where the schema
says, and every way the rc can be incomplete or un-executable is REJECTED
with a clear error. The negative cases start from the real template and
break exactly one thing, so they stay honest as the template evolves.
"""

import os

import pytest

from sabsim.deploy import (
    DeploymentConfig,
    DeploymentError,
    Duration,
    Memory,
    load_deployment,
)

# The real rc the deployment template ships — the happy-path fixture and
# the starting point every negative case mutates.
_TEMPLATE_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__),
    "..", "..", "..", "share", "templates", "deployment_rc.toml"))


def _template_text() -> str:
    """Return the known-good rc template as text to be mutated."""
    with open(_TEMPLATE_PATH, encoding="utf-8") as rc_file:
        return rc_file.read()


def _write_rc(tmp_path, text: str) -> str:
    """Write ``text`` as an rc file under ``tmp_path`` and return it."""
    rc_path = os.path.join(tmp_path, "deployment.toml")
    with open(rc_path, "w", encoding="utf-8") as rc_file:
        rc_file.write(text)
    return rc_path


def _drop_lines_containing(text: str, needle: str) -> str:
    """Remove every line containing ``needle`` (to omit a required key)."""
    return "\n".join(
        line for line in text.splitlines() if needle not in line)


# ---------------------------------------------------------------------
# The per-kind environment map (ARCHITECTURE §4.4): optional, and parsed
# to a deterministic sorted tuple so the emitted job script is stable.
# ---------------------------------------------------------------------

def test_usage_environment_is_optional_and_sorted(tmp_path):
    """An environment table parses to sorted pairs; absent gives ()."""
    text = _template_text() + (
        '\n[usage.analyze.environment]\n'
        'ZED = "z"\nALPHA = "a"\n')
    config = load_deployment(_write_rc(tmp_path, text))

    # Present: sorted (name, value) pairs, whatever order they were written.
    assert config.usage["analyze"].environment == (("ALPHA", "a"), ("ZED", "z"))
    # The template's activate block carries the cascade engine env, sorted.
    activate_env = config.usage["activate"].environment
    assert activate_env == tuple(sorted(activate_env))
    assert dict(activate_env)["SABSIM_CASCADE_ENGINE_PREFIX"]
    # Absent on a block with no environment table: the empty map, not a guess.
    assert config.usage["bond"].environment == ()


def test_usage_environment_rejects_a_non_table(tmp_path):
    """A non-table environment is a loud stop, not a silent skip."""
    # Replace the [usage.label] block's environment TABLE with a STRING
    # environment — which the parser must reject as not a name -> value
    # table.
    text = _template_text().replace(
        '[usage.label.environment]\nVASP_GAMMA    = "vasp_gam"\n'
        'VASP_STANDARD = "vasp_std"\n', 'environment = "oops"\n')
    assert 'environment = "oops"' in text
    with pytest.raises(DeploymentError):
        load_deployment(_write_rc(tmp_path, text))


# ---------------------------------------------------------------------
# Happy path: the real template loads and the values land where §14.1
# says, keyed by member job (activate / bond / analyze).
# ---------------------------------------------------------------------

def test_template_loads_into_a_config():
    """The rc template validates and parses to a DeploymentConfig."""
    config = load_deployment(_TEMPLATE_PATH)

    assert isinstance(config, DeploymentConfig)
    assert config.cluster_name == "pixstor"
    assert config.scheduler == "slurm"
    assert config.default_account == "general"
    assert config.module_paths == (
        "/cluster/VAST/rulisp-lab/cpg/modulefiles",)


def test_partitions_carry_name_capacity_and_ceiling():
    """Each partition resolves to a real name, per-node counts, ceiling."""
    config = load_deployment(_TEMPLATE_PATH)

    assert set(config.partitions) == {"cpu", "gpu"}
    cpu = config.partitions["cpu"]
    assert cpu.name == "general"
    assert cpu.capacity == {"cores_per_node": 64.0}
    assert cpu.max_walltime.in_hours() == 48.0

    gpu = config.partitions["gpu"]
    assert gpu.name == "gpu,requeue"
    assert gpu.capacity == {"gpus_per_node": 4.0}
    assert gpu.max_walltime.in_hours() == 24.0


def test_usage_is_keyed_by_member_job():
    """The usage map keys are the member jobs (plus the bootstrap's
    labelling array, routed by the same rc), not tool kinds."""
    config = load_deployment(_TEMPLATE_PATH)

    assert set(config.usage) == {"activate", "bond", "analyze", "label"}

    activate = config.usage["activate"]
    assert activate.resource_class == "gpu"  # universal cascade -> GPU (§4.1)
    assert activate.nodes == 1
    assert activate.tasks_per_node == 1      # one rank, one GPU
    assert activate.gpus_per_node == 1       # out-of-process deepmd cascade
    assert activate.walltime.in_hours() == 12.0
    assert activate.memory.in_megabytes() == 48 * 1024.0   # 48 GB ceiling
    assert activate.modules == ()            # engine is the bundle, no module
    # The per-kind environment points at the deepmd bundle + model; NO
    # LAMMPS_POTENTIALS (activate is cascade-only, §3.4).
    activate_env = dict(activate.environment)
    assert activate_env["SABSIM_CASCADE_ENGINE_PREFIX"]
    assert "LAMMPS_POTENTIALS" not in activate_env

    bond = config.usage["bond"]
    assert bond.resource_class == "gpu"
    assert bond.nodes == 1
    assert bond.tasks_per_node == 1          # one rank (committee of one)
    assert bond.gpus_per_node == 1           # one GPU for that rank
    assert bond.walltime.in_hours() == 18.0
    assert bond.memory.in_megabytes() == 32 * 1024.0       # deepmd + TF/torch
    assert bond.modules == ("cpg_lammps_conda/deepmd-kit-3.2.0b0",)
    assert bond.venv.endswith("virtual_envs/sabsim-dp3")

    analyze = config.usage["analyze"]
    assert analyze.resource_class == "cpu"
    assert analyze.tasks_per_node == 1       # serial Python measure
    assert analyze.gpus_per_node == 0        # pure-Python CPU measure
    assert analyze.memory.in_megabytes() == 8 * 1024.0     # smallest job
    # The v1 analyze job loads NO science module — the mechanical measure
    # is pure Python and the §8 characterization is Tier-B (DESIGN §10.5).
    # An empty list is allowed and MEANINGFUL, but the key is required.
    assert analyze.modules == ()


def test_partition_for_joins_usage_to_hardware():
    """A member job resolves to its real partition through the class seam."""
    config = load_deployment(_TEMPLATE_PATH)

    assert config.partition_for("activate").name == "gpu,requeue"
    assert config.partition_for("bond").name == "gpu,requeue"
    assert config.partition_for("analyze").name == "general"


# ---------------------------------------------------------------------
# Rejection rule 1 — no silent default: an incomplete rc fails loudly.
# ---------------------------------------------------------------------

def test_missing_hardware_field_is_rejected(tmp_path):
    """Dropping a required [hardware] key stops the load, naming it."""
    broken = _drop_lines_containing(_template_text(), "cluster_name")
    rc_path = _write_rc(tmp_path, broken)
    with pytest.raises(DeploymentError, match="cluster_name"):
        load_deployment(rc_path)


def test_missing_usage_field_is_rejected(tmp_path):
    """Dropping a usage block's nodes key stops the load, naming it."""
    broken = _drop_lines_containing(_template_text(), "nodes")
    rc_path = _write_rc(tmp_path, broken)
    with pytest.raises(DeploymentError, match="nodes"):
        load_deployment(rc_path)


def test_bare_walltime_without_unit_is_rejected(tmp_path):
    """A walltime written as a bare number (no unit) is refused (§1.5)."""
    broken = _template_text().replace(
        "{ value = 12.0, unit = \"h\" }", "12.0")
    rc_path = _write_rc(tmp_path, broken)
    with pytest.raises(DeploymentError, match="value, unit"):
        load_deployment(rc_path)


def test_missing_memory_field_is_rejected(tmp_path):
    """Dropping a usage block's memory key stops the load, naming it."""
    broken = _drop_lines_containing(_template_text(), "memory")
    rc_path = _write_rc(tmp_path, broken)
    with pytest.raises(DeploymentError, match="memory"):
        load_deployment(rc_path)


def test_bare_memory_without_unit_is_rejected(tmp_path):
    """A memory request written as a bare number (no unit) is refused."""
    broken = _template_text().replace(
        "{ value = 48.0, unit = \"GB\" }", "48.0")
    rc_path = _write_rc(tmp_path, broken)
    with pytest.raises(DeploymentError, match="value, unit"):
        load_deployment(rc_path)


def test_missing_gpus_per_node_field_is_rejected(tmp_path):
    """Dropping a usage block's gpus_per_node key stops the load."""
    broken = _drop_lines_containing(_template_text(), "gpus_per_node")
    rc_path = _write_rc(tmp_path, broken)
    with pytest.raises(DeploymentError, match="gpus_per_node"):
        load_deployment(rc_path)


# ---------------------------------------------------------------------
# Rejection rule 2 — reject the un-executable: a usage block routing to a
# resource class no partition defines cannot run, so it is refused.
# ---------------------------------------------------------------------

def test_usage_routing_to_undefined_class_is_rejected(tmp_path):
    """A usage block naming a class no partition defines is refused."""
    broken = _template_text().replace(
        "partition = \"gpu\"", "partition = \"nonesuch\"")
    rc_path = _write_rc(tmp_path, broken)
    with pytest.raises(DeploymentError, match="nonesuch"):
        load_deployment(rc_path)


def test_partition_for_unknown_job_is_a_loud_stop():
    """Asking for a job kind with no usage block is a clear error."""
    config = load_deployment(_TEMPLATE_PATH)
    with pytest.raises(DeploymentError, match="relax"):
        config.partition_for("relax")


# ---------------------------------------------------------------------
# Duration: the walltime figure carries its unit and reduces to hours.
# ---------------------------------------------------------------------

def test_duration_reduces_mixed_units_to_hours():
    """Minutes, seconds, and days all reduce to the common hour measure."""
    assert Duration(90.0, "min").in_hours() == pytest.approx(1.5)
    assert Duration(3600.0, "s").in_hours() == pytest.approx(1.0)
    assert Duration(2.0, "d").in_hours() == pytest.approx(48.0)


def test_duration_rejects_an_unknown_unit():
    """A walltime unit the consumer does not know is a loud stop."""
    with pytest.raises(DeploymentError, match="fortnight"):
        Duration(1.0, "fortnight").in_hours()


# ---------------------------------------------------------------------
# Memory: the request carries its unit and reduces to megabytes (SLURM's
# own --mem unit), the same units-travel-with-values rule as Duration.
# ---------------------------------------------------------------------

def test_memory_reduces_mixed_units_to_megabytes():
    """Megabytes, gigabytes, and terabytes reduce to the common measure."""
    assert Memory(512.0, "MB").in_megabytes() == pytest.approx(512.0)
    assert Memory(16.0, "GB").in_megabytes() == pytest.approx(16 * 1024.0)
    assert Memory(1.0, "TB").in_megabytes() == pytest.approx(1024.0 * 1024.0)


def test_memory_rejects_an_unknown_unit():
    """A memory unit the consumer does not know is a loud stop."""
    with pytest.raises(DeploymentError, match="furlong"):
        Memory(1.0, "furlong").in_megabytes()
