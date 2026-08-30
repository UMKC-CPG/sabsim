"""Project-file loading and validation (PSEUDOCODE.md §2).

This subpackage owns the contract between the human-authored TOML
project file (``sabsim.toml``, one wafer pair per project) and the
pipeline: the typed records that mirror the §2 schema and the loader
that reads, completeness-checks, and executability-checks a file
before any pipeline step runs.
"""

from sabsim.spec.loader import (
    SpecificationError,
    load_and_validate_project,
)
from sabsim.spec.records import (
    AnnealSchedule,
    EnsembleKnobs,
    MaterialKnobs,
    NumericalKnobs,
    PairSpecification,
    Project,
    ProtocolKnobs,
    Quantity,
    StageFolders,
    WaferPair,
    folder_label,
    stage_folders,
)

__all__ = [
    "SpecificationError",
    "load_and_validate_project",
    "AnnealSchedule",
    "EnsembleKnobs",
    "MaterialKnobs",
    "NumericalKnobs",
    "PairSpecification",
    "Project",
    "ProtocolKnobs",
    "Quantity",
    "StageFolders",
    "WaferPair",
    "folder_label",
    "stage_folders",
]
