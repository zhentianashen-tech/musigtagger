"""Findings: severity, classification, and the finding record.

Every significant harness observation is classified per the Evaluation &
Review Agent's routing scheme so defects land with the responsible role.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class Severity(enum.Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

    @property
    def rank(self) -> int:
        order = ("critical", "high", "medium", "low", "info")
        return order.index(self.value)


class Classification(enum.Enum):
    TAXONOMY_SPEC = "taxonomy/specification problem"
    ENGINE_DEFECT = "tagging-engine defect"
    APP_INTEGRATION_DEFECT = "application/integration defect"
    EVALUATION_DATA = "evaluation-data problem"
    ARCHITECTURAL = "architectural/cross-component problem"


@dataclass(frozen=True)
class Finding:
    """One reproducible observation routed to a responsible role."""

    severity: Severity
    classification: Classification
    summary: str
    evidence: str = ""
    reproduction: str = ""
    responsible_role: str = ""

    def sort_key(self) -> tuple[int, str]:
        return (self.severity.rank, self.summary)


@dataclass
class FindingList:
    """Ordered collection of findings, worst first."""

    items: list[Finding] = field(default_factory=list)

    def add(self, finding: Finding) -> None:
        self.items.append(finding)

    def extend(self, findings: list[Finding]) -> None:
        self.items.extend(findings)

    def ordered(self) -> list[Finding]:
        return sorted(self.items, key=Finding.sort_key)

    def has_at_least(self, severity: Severity) -> bool:
        return any(item.severity.rank <= severity.rank for item in self.items)
