"""Study-specification loading and validation (PSEUDOCODE.md §2).

This subpackage owns the contract between the human-authored TOML study
spec and the pipeline: the typed records that mirror the §2 schema and
the loader that reads, completes-checks, and executability-checks a
spec before any pipeline step runs.
"""

from sabsim.spec.loader import (
    SpecificationError,
    load_and_validate_study,
)
from sabsim.spec.records import (
    AnnealSchedule,
    EnsembleKnobs,
    MaterialKnobs,
    MemberSpecification,
    NumericalKnobs,
    ProtocolKnobs,
    Quantity,
    Relation,
    Study,
    WaferPair,
)

__all__ = [
    "SpecificationError",
    "load_and_validate_study",
    "AnnealSchedule",
    "EnsembleKnobs",
    "MaterialKnobs",
    "MemberSpecification",
    "NumericalKnobs",
    "ProtocolKnobs",
    "Quantity",
    "Relation",
    "Study",
    "WaferPair",
]
