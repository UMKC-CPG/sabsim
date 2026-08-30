"""SABSIM — a turn-key pipeline for Surface Activated Bonding studies.

This is the main pipeline package. It grows wave by wave along the
ARCHITECTURE.md §5 development trajectory; the first wave (W0) builds
the walking skeleton — the project-file loader and the pair sequencer
— behind cheap stand-ins, so a single well-formed number can travel
the whole eight-step pipeline before any module is deepened.

The DeePMD MLIP-backend prototype lives separately under
``prototypes/alf_deepmd/`` and is not imported here.
"""
