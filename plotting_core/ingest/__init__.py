"""Input contract: read-only Excel access, validation and normalisation.

The pipeline never modifies the source workbook and never invents values.  Every
blocking condition (unknown header, unmapped branch value, missing number,
possible duplicate, ambiguous sample identity) is reported instead of guessed;
user-approved mappings and skips are carried in the plot spec.
"""

from .report import InputContractError, ValidationReport  # noqa: F401
from .normalize import NormalizedData, NormalizedSeries  # noqa: F401
from .service import load_normalized_data  # noqa: F401

__all__ = [
    "InputContractError",
    "NormalizedData",
    "NormalizedSeries",
    "ValidationReport",
    "load_normalized_data",
]
