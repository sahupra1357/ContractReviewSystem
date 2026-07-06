"""Pipeline job queue on Postgres (→ SQS + Step Functions in production).

Workers claim with FOR UPDATE SKIP LOCKED so multiple workers never run the
same job. Every state change is audited by the caller that owns the
transaction.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models import Job, JobState


def enqueue(session: Session, *, document_id: str, stage: str) -> Job:
    job = Job(document_id=document_id, stage=stage, state=JobState.pending)
    session.add(job)
    return job


def claim_next(session: Session, *, stage: str) -> Job | None:
    """Claim the oldest pending job for a stage; None if queue is empty."""
    job = session.execute(
        select(Job)
        .where(Job.stage == stage, Job.state == JobState.pending)
        .order_by(Job.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if job is None:
        return None
    job.state = JobState.running
    job.attempts += 1
    job.claimed_at = datetime.now(UTC)
    return job


def complete(job: Job) -> None:
    job.state = JobState.done


def fail(job: Job, error: str) -> None:
    job.state = JobState.failed
    job.error = error
