"""Unit tests for the location-root resolver (sabsim.deploy.roots).

These pin the §14.4 login-node gate: the two REQUIRED roots
(SABSIM_SCRATCH, SABSIM_SHARE) must be set or the writer stops by name,
while SABSIM_LOCAL is an optional override whose absence is normal
(ARCHITECTURE.md §4.1). No defaults are ever guessed (VISION principle 1).
"""

import pytest

from sabsim.deploy import (
    DeploymentError,
    LocationRoots,
    resolve_location_roots,
)


def test_all_three_roots_resolve(monkeypatch):
    """With all three set, each lands on the record."""
    monkeypatch.setenv("SABSIM_SCRATCH", "/scratch/me")
    monkeypatch.setenv("SABSIM_SHARE", "/share/cpg")
    monkeypatch.setenv("SABSIM_LOCAL", "/local/me")

    roots = resolve_location_roots()
    assert isinstance(roots, LocationRoots)
    assert roots.scratch == "/scratch/me"
    assert roots.share == "/share/cpg"
    assert roots.local == "/local/me"


def test_local_is_optional(monkeypatch):
    """An unset SABSIM_LOCAL means 'no override', not an error."""
    monkeypatch.setenv("SABSIM_SCRATCH", "/scratch/me")
    monkeypatch.setenv("SABSIM_SHARE", "/share/cpg")
    monkeypatch.delenv("SABSIM_LOCAL", raising=False)

    assert resolve_location_roots().local is None


def test_missing_scratch_is_a_loud_stop(monkeypatch):
    """An unset required scratch root stops, naming the variable."""
    monkeypatch.delenv("SABSIM_SCRATCH", raising=False)
    monkeypatch.setenv("SABSIM_SHARE", "/share/cpg")
    with pytest.raises(DeploymentError, match="SABSIM_SCRATCH"):
        resolve_location_roots()


def test_missing_share_is_a_loud_stop(monkeypatch):
    """An unset required share root stops, naming the variable."""
    monkeypatch.setenv("SABSIM_SCRATCH", "/scratch/me")
    monkeypatch.delenv("SABSIM_SHARE", raising=False)
    with pytest.raises(DeploymentError, match="SABSIM_SHARE"):
        resolve_location_roots()


def test_tilde_is_expanded(monkeypatch):
    """A ~ in a root is expanded to a real home, ready to bake in."""
    monkeypatch.setenv("SABSIM_SCRATCH", "~/data/scratch")
    monkeypatch.setenv("SABSIM_SHARE", "/share/cpg")
    roots = resolve_location_roots()
    assert not roots.scratch.startswith("~")
    assert roots.scratch.endswith("/data/scratch")
