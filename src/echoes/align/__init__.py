"""Corpus and annotation alignment layers.

The versification-crosswalk schema is Milestone 4 preparation; annotation
alignment itself is implemented in later milestones.
"""

from echoes.align.versification import (
    CrosswalkValidationError,
    VersificationCrosswalk,
    load_versification_crosswalk,
)

__all__ = [
    "CrosswalkValidationError",
    "VersificationCrosswalk",
    "load_versification_crosswalk",
]
