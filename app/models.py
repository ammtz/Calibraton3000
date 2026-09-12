"""Two tables. That is the whole data model."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # JobScout's own identifier. Unique so re-imports are idempotent.
    source_id: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    title: Mapped[Optional[str]] = mapped_column(String(500))
    company: Mapped[Optional[str]] = mapped_column(String(500))
    # Narrow why-this-fits text. Not a job description dump.
    blurb: Mapped[Optional[str]] = mapped_column(Text)
    # JobScout's raw criteria fields, untouched.
    criteria: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    imported_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    decisions: Mapped[list["Decision"]] = relationship(back_populates="job")

    def as_card(self, score: float) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "title": self.title,
            "company": self.company,
            "blurb": self.blurb,
            "criteria": self.criteria or {},
            "score": score,
        }


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), nullable=False, index=True)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)  # "like" | "dislike"

    # Deliberately two separate signals: desire and expectation.
    would_apply: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    would_get: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Frozen at swipe time so later weight changes never rewrite history.
    criteria_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_now)

    job: Mapped["Job"] = relationship(back_populates="decisions")


VERDICTS = ("like", "dislike")
