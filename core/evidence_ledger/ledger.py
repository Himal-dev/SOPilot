"""Append-only claim -> evidence records.

The ledger never mutates or deletes entries. Records are created as the agent
makes observations and decisions; downstream consumers (the output generator,
auditors, the CLI) read records back by id, step, or claim.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, List, Optional

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return f"ev_{uuid.uuid4().hex[:12]}"


class EvidenceRecord(BaseModel):
    """A single auditable claim and the evidence supporting it.

    Attributes mirror the platform contract from the architecture plan:
    ``{claim, evidence[], model, confidence, human_confirmed}`` plus bookkeeping
    fields (``id``, ``step_id``, ``created_at``) so output fields can reference
    a specific ledger entry.
    """

    id: str = Field(default_factory=_new_id)
    claim: str
    evidence: List[str] = Field(
        default_factory=list,
        description="Opaque references to supporting artifacts (image ids, tool "
        "result ids, transcript spans).",
    )
    model: str = Field(
        default="local-stub",
        description="The model/adapter that produced the claim.",
    )
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    human_confirmed: bool = False
    step_id: Optional[str] = None
    created_at: str = Field(default_factory=_now)


class EvidenceLedger:
    """Thin, append-only helper over a list of :class:`EvidenceRecord`.

    The canonical store is the ``evidence`` list on the central state; this
    class wraps a snapshot of that list to provide append + query helpers. It is
    intentionally stateless beyond the records it holds so it can be rebuilt from
    a checkpointed state at any time.
    """

    def __init__(self, records: Optional[Iterable[EvidenceRecord]] = None) -> None:
        self._records: List[EvidenceRecord] = list(records or [])

    @classmethod
    def from_state(cls, records: Iterable[Any]) -> "EvidenceLedger":
        """Rebuild a ledger from state, coercing dicts to records as needed."""
        coerced: List[EvidenceRecord] = []
        for r in records or []:
            if isinstance(r, EvidenceRecord):
                coerced.append(r)
            else:
                coerced.append(EvidenceRecord.model_validate(r))
        return cls(coerced)

    def record(
        self,
        claim: str,
        *,
        evidence: Optional[List[str]] = None,
        model: str = "local-stub",
        confidence: float = 0.0,
        human_confirmed: bool = False,
        step_id: Optional[str] = None,
    ) -> EvidenceRecord:
        """Append a new claim->evidence record and return it."""
        entry = EvidenceRecord(
            claim=claim,
            evidence=evidence or [],
            model=model,
            confidence=confidence,
            human_confirmed=human_confirmed,
            step_id=step_id,
        )
        self._records.append(entry)
        return entry

    @property
    def records(self) -> List[EvidenceRecord]:
        return list(self._records)

    def by_step(self, step_id: str) -> List[EvidenceRecord]:
        return [r for r in self._records if r.step_id == step_id]

    def get(self, record_id: str) -> Optional[EvidenceRecord]:
        return next((r for r in self._records if r.id == record_id), None)

    def confirm(self, record_id: str) -> Optional[EvidenceRecord]:
        """Mark a record human-confirmed (append-only semantics: same object)."""
        entry = self.get(record_id)
        if entry is not None:
            entry.human_confirmed = True
        return entry

    def to_list(self) -> List[dict]:
        return [r.model_dump() for r in self._records]

    def __len__(self) -> int:
        return len(self._records)
