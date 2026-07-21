"""The serial-file-I/O invariant (`ARCHITECTURE.md` §4.1, discipline 2).

SABSIM owns its MPI communicator: only its own code may post a collective
on it. ASE breaks that rule by default. The moment it detects that more
than one process is running under MPI, ASE promotes `read` and `write`
into COLLECTIVE operations — process zero alone touches the disk and then
broadcasts the result to every other process, and all of them must take
part or none may continue.

That is incompatible with how SABSIM hands structures between stages
(`DESIGN.md` §2.6): one process writes a file, a barrier publishes it,
and every process then reads it back for itself. A read issued inside a
"only process zero does this" guard becomes a broadcast waiting on peers
that never call it, and posting two DIFFERENT collectives on one
communicator is undefined behavior rather than a reported error. It
surfaces either as a deadlock or — worse — as peers handed an empty
result they cannot tell apart from an empty file.

That failure is invisible on a login node, because ASE behaves perfectly
serially whenever only one process is running: no ordinary unit test can
reach it, and it cost one eight-hour cluster job to find. So these tests
check the invariant STRUCTURALLY instead of behaviorally. The first walks
the shipped source and insists every ASE file call names the escape hatch
explicitly, which protects call sites nobody has written yet — the real
risk, since a new call site inherits the dangerous default silently. The
second confirms the flag genuinely reaches ASE on the main read path.
"""

from __future__ import annotations

import ast
import os

import sabsim
from sabsim.structure.slab_builder import read_standalone_half

# The names the project imports ASE's file functions under, plus ASE's
# own spelling, so a call written either way is still caught.
_ASE_IO_NAMES = {"ase_read", "ase_write"}


def _python_sources() -> list:
    """Every shipped source file under the sabsim package."""
    package_root = os.path.dirname(sabsim.__file__)
    sources = []
    for directory, _subdirs, file_names in os.walk(package_root):
        for file_name in file_names:
            if file_name.endswith(".py"):
                sources.append(os.path.join(directory, file_name))
    return sorted(sources)


def _ase_io_calls(source_path: str) -> list:
    """Find ASE read/write calls in one file, with their line numbers.

    Returns one entry per call site as (line number, function name, the
    call's keyword arguments), so the caller can check what was passed.
    """
    with open(source_path, encoding="utf-8") as source_file:
        tree = ast.parse(source_file.read(), filename=source_path)

    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        # Either a bare name (`ase_read(...)`, the project's import
        # style) or an attribute access (`ase.io.read(...)`).
        if isinstance(function, ast.Name) and function.id in _ASE_IO_NAMES:
            name = function.id
        elif (isinstance(function, ast.Attribute)
              and function.attr in ("read", "write")
              and isinstance(function.value, ast.Attribute)
              and function.value.attr == "io"):
            name = f"ase.io.{function.attr}"
        else:
            continue
        found.append((node.lineno, name, node.keywords))
    return found


def test_every_ase_file_call_in_the_package_is_explicitly_serial():
    """No shipped ASE read/write may inherit the collective default.

    A new call site written without `parallel=False` is exactly the
    regression this guards: it passes every login-node test and then
    deadlocks the first time it runs on more than one process.
    """
    offenders = []
    for source_path in _python_sources():
        for line_number, name, keywords in _ase_io_calls(source_path):
            serial = [keyword for keyword in keywords
                      if keyword.arg == "parallel"]
            is_serial = (
                len(serial) == 1
                and isinstance(serial[0].value, ast.Constant)
                and serial[0].value.value is False)
            if not is_serial:
                offenders.append(
                    f"{os.path.basename(source_path)}:{line_number} "
                    f"calls {name} without parallel=False")

    assert not offenders, (
        "ASE file calls must be explicitly serial (ARCHITECTURE.md §4.1, "
        "second discipline); these would become MPI collectives:\n  "
        + "\n  ".join(offenders))


def test_the_package_actually_has_ase_calls_to_check():
    """Guard the guard: the walk above must not be silently finding none.

    Without this, deleting or renaming the ASE imports would turn the
    invariant test into one that passes by examining nothing at all.
    """
    total = sum(len(_ase_io_calls(path)) for path in _python_sources())
    assert total >= 4, (
        f"expected the package to contain several ASE file calls to "
        f"check, found {total} — has the search gone stale?")


def test_read_standalone_half_passes_serial_flag_to_ase(monkeypatch,
                                                        tmp_path):
    """The flag must reach ASE itself, not just appear in the source.

    Complements the source walk: that one proves the argument is
    written, this one proves it is actually handed to ASE on the read
    path the activation stage depends on.
    """
    from sabsim.structure import slab_builder

    recorded = {}

    def fake_read(data_file, **keyword_arguments):
        recorded.update(keyword_arguments)
        # Any object will do; the caller only wraps it up.
        return "atoms-stand-in"

    monkeypatch.setattr(slab_builder, "ase_read", fake_read)
    half = read_standalone_half(
        str(tmp_path / "unused.data"), {"Si": 1}, "Si")

    assert recorded.get("parallel") is False, (
        "read_standalone_half must ask ASE for a serial read; it passed "
        f"{recorded.get('parallel')!r}")
    assert half.atoms == "atoms-stand-in"
