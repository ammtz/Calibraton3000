"""Two tables. Calibraton stores the source's items verbatim and adds one key."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# The 5-point gut check. The number is the ordinal; the label is what the button says.
RATINGS: dict[int, str] = {
    1: "No way",
    2: "Bad",
    3: "Meh",
    4: "Ok",
    5: "Great",
}

# A shrug clears the card and counts toward the floor, but casts no vote.
NEUTRAL_RATING = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Job(Base):
    """One ranked item. `card` is the ingested payload, untouched."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # The source's own id for this item. Unique, so re-ingesting is idempotent.
    source_id: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    # Who ranked it, for display only. The service works without it.
    source: Mapped[Optional[str]] = mapped_column(String(100))

    title: Mapped[Optional[str]] = mapped_column(String(500))
    company: Mapped[Optional[str]] = mapped_column(String(500))
    blurb: Mapped[Optional[str]] = mapped_column(Text)

    # The source's points map: string -> number. Absent means unknown, never zero.
    criteria: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # The source's own verdict, stored, never recomputed. Null when it declined to rank.
    scored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_score: Mapped[Optional[float]] = mapped_column(Float)
    source_rank: Mapped[Optional[int]] = mapped_column(Integer)
    rank_total: Mapped[Optional[int]] = mapped_column(Integer)
    known: Mapped[Optional[int]] = mapped_column(Integer)
    known_total: Mapped[Optional[int]] = mapped_column(Integer)

    # The payload exactly as it arrived, so the extra key is all we ever add.
    card: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    imported_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    decisions: Mapped[list["Decision"]] = relationship(back_populates="job")

    def as_card(self) -> dict[str, Any]:
        """What the swipe UI renders. The source's numbers, never ours."""
        return {
            "id": self.id,
            "source_id": self.source_id,
            "source": self.source,
            "title": self.title,
            "company": self.company,
            "blurb": self.blurb,
            "criteria": self.criteria or {},
            "scored": self.scored,
            "score": self.source_score,
            "rank": self.source_rank,
            "rank_total": self.rank_total,
            "known": self.known,
            "known_total": self.known_total,
        }


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), nullable=False, index=True)

    # 1..5. On a ranked item this is a gut check on that placement; on an
    # unranked one there is nothing to check, so it reads as an absolute call.
    rating: Mapped[int] = mapped_column(Integer, nullable=False)

    # Deliberately two separate signals: desire and expectation.
    would_apply: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    would_get: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Did the source have a rank for this item? Splits the two training sets.
    was_scored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)

    # Frozen at swipe time so later corrections never rewrite history.
    criteria_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    # Outbox. A decision is pending until something acknowledges carrying it
    # somewhere else. The core service never does that itself — it has no
    # network — it just keeps the ledger honest for whatever does.
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)
    sync_error: Mapped[Optional[str]] = mapped_column(Text)

    job: Mapped["Job"] = relationship(back_populates="decisions")
