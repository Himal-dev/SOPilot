"""Append-only evidence ledger.

Every conclusion the agent reaches points to evidence. The ledger is the
trust/explainability spine of the platform: output fields and decisions
reference ledger entries by id.
"""

from core.evidence_ledger.ledger import EvidenceLedger, EvidenceRecord

__all__ = ["EvidenceLedger", "EvidenceRecord"]
