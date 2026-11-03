"""Compatibility forwarder: the GCD dialect now lives in the domain package.

Kept so existing callers (``plotting_core.ingest.gcd``) keep working; the canonical
module is :mod:`plotting_core.domains.electrochemistry.gcd.ingest`.
"""

from ..domains.electrochemistry.gcd.ingest import (BRANCH_ORDER,  # noqa: F401
                                                   VARIANT_COLUMNS, load)

__all__ = ["BRANCH_ORDER", "VARIANT_COLUMNS", "load"]
