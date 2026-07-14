"""The measure vector and its records (DESIGN.md §6).

A measurement is never a bare number. Every value the analyzer emits is
a :class:`Measure` carrying its uncertainty, its provenance, and its
status, so a gate (DESIGN.md §7) can read results BY NAME AND STATUS and
never trust a lone float (DESIGN.md §6.6). The :class:`MeasureVector` is
the whole set of measures one member produced.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MeasureStatus(str, Enum):
    """Whether a measure resolved to a value a gate may read (§6.6).

    ``UNRESOLVED`` is not a failure of the run — it says "this quantity
    could not be computed here" — but it NEVER passes a gate: a gate
    that cannot see a number withholds its verdict (DESIGN.md §1.1).
    """

    OK = "ok"                  # resolved to a value that may be read
    UNRESOLVED = "unresolved"  # could not be computed; never passes
    REJECTED = "rejected"      # computed, then failed a validity check


@dataclass(frozen=True)
class Measure:
    """One named result plus everything needed to trust or reject it.

    The fields follow DESIGN.md §6.6: a value means nothing without its
    units, its uncertainty, how many realizations it averaged, and how
    it was produced. Both the native unit and its SI form are carried so
    a reader never has to convert in their head (e.g. eV/Å² and J/m²).
    """

    name: str
    value: float | None            # None only when status is not OK
    uncertainty: float | None      # spread over the ensemble, if known
    realization_count: int         # how many seeds this averaged over
    unit_native: str               # the unit it was computed in
    unit_si: str                   # the same quantity in SI, for reading
    fidelity: str                  # e.g. "classical-stand-in", "mlip"
    method: str                    # a short note on how it was produced
    status: MeasureStatus          # ok / unresolved / rejected
    inputs: tuple[str, ...] = ()   # fingerprints of what fed this measure


@dataclass(frozen=True)
class Verdicts:
    """The press/pull OUTCOME the analyzer reads once (PSEUDOCODE §4).

    A bond decision is a FACT about the run, not an averaged quantity:
    DESIGN.md §5.2 settles it mid-press from a running-average normal
    stress, so it rides the measure vector as its own field rather than
    being dressed up as a :class:`Measure`. PSEUDOCODE.md §4 states it
    directly — "the press outcome IS the Verdicts, read once, not
    through a measure." ``contact_quality`` is the §5.2 dual-contact
    fraction; it is None in wave 0, where the press is stubbed and only
    the ``bonded`` flag is carried through the seam.
    """

    bonded: bool | None            # did the pair bond under the press?
    contact_quality: float | None  # §5.2 contact fraction; None if unknown


@dataclass(frozen=True)
class MeasureVector:
    """The complete set of measures a single member produced (§6).

    Beyond the measures themselves the vector carries the run's
    :class:`Verdicts` — the press outcome the §4 analyzer reads ONCE
    from the trajectory, never re-derived through a measure. It is None
    on a vector that reports no verdict, such as the step-8
    characterization vector or a merge intermediate (DESIGN.md §4, §8).
    """

    measures: tuple[Measure, ...]
    verdicts: Verdicts | None = None

    def by_name(self, name: str) -> Measure | None:
        """Return the measure called ``name``, or None if it is absent.

        The gate reads results by name and status, never by position
        (DESIGN.md §6.6), and a missing measure is a real answer — the
        member simply did not produce it.
        """
        for measure in self.measures:
            if measure.name == name:
                return measure
        return None


def merge_measures(
        first: MeasureVector, second: MeasureVector) -> MeasureVector:
    """Combine two measure vectors, refusing to hide a name collision.

    The analyzer (DESIGN.md §6) and the characterization step (§8) both
    emit measures; the sequencer merges them. Two stages producing the
    same measure name is a programming error, not a value to silently
    pick between, so it is raised rather than resolved by position.
    """
    seen = {measure.name for measure in first.measures}
    for measure in second.measures:
        if measure.name in seen:
            raise ValueError(
                f"measure '{measure.name}' produced by two stages")
    # Only the analyzer produces Verdicts (from the press); the step-8
    # characterization vector carries none. Carry whichever side set
    # them, and refuse the ambiguous case of two live verdict sets,
    # mirroring the name-collision rule above.
    if first.verdicts is not None and second.verdicts is not None:
        raise ValueError("two measure vectors both carry verdicts")
    merged_verdicts = (
        first.verdicts if first.verdicts is not None
        else second.verdicts)
    return MeasureVector(
        measures=first.measures + second.measures,
        verdicts=merged_verdicts)
