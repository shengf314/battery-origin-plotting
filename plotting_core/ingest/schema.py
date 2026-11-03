"""Compatibility forwarder: the input contract of electrochemistry moved to the domain.

Canonical module: :mod:`plotting_core.domains.electrochemistry.schema`.
"""

from ..domains.electrochemistry.schema import (ALIASES, BRANCH_ALIASES,  # noqa: F401
                                               CANONICAL_FIELDS, excluded_value_matches,
                                               map_headers, normalize_branch,
                                               normalize_cycle, normalize_header,
                                               numeric_value, require_fields)

__all__ = ["ALIASES", "BRANCH_ALIASES", "CANONICAL_FIELDS", "excluded_value_matches",
           "map_headers", "normalize_branch", "normalize_cycle", "normalize_header",
           "numeric_value", "require_fields"]
