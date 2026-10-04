"""Evidence-bound wording for the local decision-support experience.

This module deliberately does not call an external model. It is a small composition
point for a future provider, but the live demo remains useful without credentials.
Any future provider should receive only the evidence pack and return citations that
can be validated against that pack before a response is shown to an operator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .engine import TriageReport


@dataclass(frozen=True)
class GroundedNarrative:
    provider: str
    text: str
    citations: list[str]


class NarrativeProvider(Protocol):
    """Optional provider contract for an evidence-constrained narrative layer."""

    name: str

    def compose(self, report: TriageReport) -> GroundedNarrative:
        """Return a narrative that cites only ids present in report.evidence."""


class DeterministicNarrativeProvider:
    """Credential-free provider used by the demo and offline test suite."""

    name = "deterministic-evidence-v1"

    def compose(self, report: TriageReport) -> GroundedNarrative:
        citations = [evidence.source_id for evidence in report.evidence]
        text = f"Prochaine étape proposée : {report.decision[0].lower()}{report.decision[1:]} Hypothèse principale : {report.hypothesis}"
        return GroundedNarrative(provider=self.name, text=text, citations=citations)


def compose_grounded_narrative(report: TriageReport) -> GroundedNarrative:
    """Use the local provider. External providers are intentionally opt-in only."""
    return DeterministicNarrativeProvider().compose(report)
