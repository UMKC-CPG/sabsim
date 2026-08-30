"""The bootstrap: manufacturing the production potential (steps 1-2).

Reads a force-model recipe (DESIGN.md §4.8), builds the training
structures, writes and harvests the VASP labels, and — in later slices —
hands them to ALF to train the DeePMD committee and refines it by
uncertainty (DESIGN.md §4.5, PSEUDOCODE.md §11). Driven by the
``sabsim bootstrap`` verb; runs on its own clock, before any project.
"""
