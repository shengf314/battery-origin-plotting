"""Validation reporting and the blocking input-contract error."""

from dataclasses import dataclass, field
from typing import Any, Dict, List


class InputContractError(Exception):
    """Raised when the input contract requires user confirmation."""

    def __init__(self, message: str, report: "ValidationReport" = None):
        super().__init__(message)
        self.report = report


@dataclass
class ValidationReport:
    """Structured record of everything the input stage checked."""

    source: Dict[str, Any] = field(default_factory=dict)
    header_map: Dict[str, str] = field(default_factory=dict)
    applied_mappings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    questions: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    duplicates: List[Any] = field(default_factory=list)
    counts: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    _mapping_index: set = field(default_factory=set, repr=False, compare=False)

    def record_mapping(self, message: str) -> None:
        """Record an applied mapping once, however many rows it covers."""
        if message in self._mapping_index:
            return
        self._mapping_index.add(message)
        self.applied_mappings.append(message)

    @property
    def blocking(self) -> bool:
        return bool(self.errors or self.questions)

    def error(self, message: str) -> None:
        self.errors.append(message)

    def question(self, message: str) -> None:
        self.questions.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def note(self, message: str) -> None:
        self.notes.append(message)

    def raise_if_blocking(self, context: str = "input validation") -> None:
        if not self.blocking:
            return
        lines = [context + " is blocked:"]
        for message in self.errors:
            lines.append("  error: " + message)
        for message in self.questions:
            lines.append("  confirm: " + message)
        raise InputContractError("\n".join(lines), report=self)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "header_map": self.header_map,
            "applied_mappings": list(self.applied_mappings),
            "errors": list(self.errors),
            "questions": list(self.questions),
            "warnings": list(self.warnings),
            "duplicates": self.duplicates,
            "counts": self.counts,
            "notes": list(self.notes),
        }
