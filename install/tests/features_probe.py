"""Feature-coverage probe for a source-built LAMMPS engine (Stack C).

The build recipe (`install/build_lammps.sh`) REQUESTS a package set, but
a requested flag is not proof of a compiled-in package.  This driver asks
the installed binary itself what it actually contains, so the ledger can
cite a runtime fact instead of trusting the CMake line.

It constructs the engine's own ctypes wrapper (selected by the calling
slurm script via PYTHONPATH / LD_LIBRARY_PATH), reads
``lammps.installed_packages``, and compares that live list against two
reference sets:

  * REQUIRED_BY_SABSIM -- the packages every LAMMPS style the pipeline
    actually emits depends on, derived by grepping the source for
    ``pair_style`` / ``fix`` / ``compute`` literals.  A missing entry
    here is a REAL blocker: some run would fail with "unknown style".
  * PRESENT_IN_SITE_ENGINE -- Imago's 26-package cpg_lammps set, so the
    log shows exactly what this conda build trades away relative to the
    adopt-the-site alternative (expected: ML-HDNNP, VORONOI).

A single serial rank is enough: package registration is a compile-time
property, identical on every rank, so no multi-node launch is needed.
"""
import os
import socket

from lammps import lammps
import lammps as lammps_module

# --- The styles SABSIM's code emits, mapped to their owning package ----
# Every non-core LAMMPS style the pipeline issues (see the grep of
# src/ for pair_style / fix / compute literals).  Core styles -- nve,
# nvt, langevin, setforce, aveforce, move, box/relax, minimize, dump
# custom, compute temp/com, compute reduce, region block -- need no
# package and so are not listed.
#   * MANYBODY  : pair_style sw, zbl, tersoff, vashishta
#   * EXTRA-FIX : fix halt (cascade run-limit guard)
#   * PLUGIN    : runtime `plugin load` of the deepmd pair_style
# ML-SNAP / ML-IAP are included because the MLIP backend decision keeps
# SNAP as a live alternative to the deepmd plugin; if that path is taken
# the trained potential registers through ML-SNAP.
REQUIRED_BY_SABSIM = {
    "MANYBODY",
    "EXTRA-FIX",
    "PLUGIN",
    "ML-SNAP",
    "ML-IAP",
}

# Imago's site cpg_lammps/2024.08.29-deepmd enabled-package list, quoted
# verbatim from the module's help() block -- the "adopt, don't rebuild"
# reference set this conda build is measured against.
PRESENT_IN_SITE_ENGINE = {
    "COMPRESS", "DIFFRACTION", "EXTRA-COMMAND", "EXTRA-COMPUTE",
    "EXTRA-DUMP", "EXTRA-FIX", "EXTRA-MOLECULE", "EXTRA-PAIR",
    "KSPACE", "MANYBODY", "MC", "MEAM", "MISC", "ML-HDNNP",
    "ML-IAP", "ML-SNAP", "MOLECULE", "OPENMP", "OPT", "PHONON",
    "PLUGIN", "QEQ", "REACTION", "REAXFF", "REPLICA", "RIGID",
    "VORONOI",
}

# Build a serial engine purely to interrogate its capabilities.  Logs
# off so the only output is our own report; the wrapper still MPI_Inits,
# hence this must run under the scheduler on a compute node.
engine = lammps(cmdargs=["-log", "none", "-screen", "none"])

installed = set(engine.installed_packages)
missing_required = sorted(REQUIRED_BY_SABSIM - installed)
dropped_vs_site = sorted(PRESENT_IN_SITE_ENGINE - installed)
extra_vs_site = sorted(installed - PRESENT_IN_SITE_ENGINE)

# --- Self-logging block (ledger rule #2) ------------------------------
print("host           :", socket.gethostname())
print("wrapper file   :", lammps_module.__file__)
print("LAMMPS version :", engine.version())
print("package count  :", len(installed))
print("installed pkgs :", " ".join(sorted(installed)))
print("required-set   :", " ".join(sorted(REQUIRED_BY_SABSIM)))
print("MISSING_REQUIRED  :", " ".join(missing_required) or "(none)")
print("dropped_vs_site   :", " ".join(dropped_vs_site) or "(none)")
print("extra_vs_site     :", " ".join(extra_vs_site) or "(none)")

# A concrete style-registration cross-check: the four pair_styles the
# pipeline names outright must each report as available.  This catches
# the case where a package is nominally present but a specific style was
# excluded -- registration, not just package membership.
for style_name in ("sw", "zbl", "tersoff", "vashishta"):
    print(f"has_pair_style {style_name:10s}:", engine.has_style("pair", style_name))

# fix halt is the one non-core FIX the cascade path depends on.
print("has_fix halt       :", engine.has_style("fix", "halt"))

verdict_ok = not missing_required
print("FEATURES OK" if verdict_ok else "FEATURES MISSING")

engine.close()
