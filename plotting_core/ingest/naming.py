"""Compatibility forwarder: the sample-naming rules moved to the domain package.

Canonical module: :mod:`plotting_core.domains.electrochemistry.naming`.
"""

from ..domains.electrochemistry.naming import filename_sample, sample_names  # noqa: F401

__all__ = ["filename_sample", "sample_names"]
