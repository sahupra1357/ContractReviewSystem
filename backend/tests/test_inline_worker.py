"""In-process pipeline loop for hosts with no worker tier.

The loop itself is the same code the standalone worker runs (test_worker.py
covers the stages). What is new here is orphan recovery: claim_next only ever
selects `pending`, so a job whose process died mid-run would wedge its document
forever on a host that idles processes out.
"""

import pytest
from sqlalchemy import select

from backend import jobs, worker
from backend.config import get_settings
from backend.models import Job, JobState


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_inline_worker_is_off_by_default():
    # compose and the AWS build run a real worker service; nothing changes there
    assert get_settings().inline_worker is False


def test_inline_worker_enabled_by_config(monkeypatch):
    monkeypatch.setenv("CRS_INLINE_WORKER", "1")
    assert get_settings().inline_worker is True


def test_orphaned_running_job_is_requeued(session):
    session.add(Job(document_id="doc-1", stage="extract", state=JobState.running))
    session.commit()

    requeued = jobs.requeue_orphaned(session)
    session.commit()

    assert [j.document_id for j in requeued] == ["doc-1"]
    assert session.execute(select(Job)).scalar_one().state == JobState.pending


def test_requeue_leaves_pending_and_done_jobs_alone(session):
    session.add_all([
        Job(document_id="doc-p", stage="extract", state=JobState.pending),
        Job(document_id="doc-d", stage="extract", state=JobState.done),
        Job(document_id="doc-f", stage="extract", state=JobState.failed),
    ])
    session.commit()

    assert jobs.requeue_orphaned(session) == []
    states = {j.document_id: j.state for j in session.execute(select(Job)).scalars()}
    assert states == {
        "doc-p": JobState.pending,
        "doc-d": JobState.done,
        "doc-f": JobState.failed,
    }


def test_supervisor_restarts_a_crashing_loop():
    # a thread that dies leaves the API healthy but the pipeline dead — the
    # supervisor must outlive any exception the stages can throw
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("storage unreachable")

    restarts = worker.supervise(
        run_fn=boom, sleep_fn=lambda _: None, max_restarts=3
    )

    assert restarts == 3
    assert len(calls) == 3


def test_supervisor_backs_off_between_restarts():
    delays = []
    worker.supervise(
        run_fn=lambda: (_ for _ in ()).throw(RuntimeError("nope")),
        sleep_fn=delays.append,
        max_restarts=4,
    )

    assert delays[0] == worker.INLINE_RETRY_SECONDS
    assert delays == sorted(delays)                      # monotonic backoff
    assert max(delays) <= worker.INLINE_RETRY_MAX_SECONDS  # and capped


def test_supervisor_returns_when_loop_exits_cleanly():
    # run(once=True) semantics: a clean return is not an error, no restart
    assert worker.supervise(run_fn=lambda: None, sleep_fn=lambda _: None) == 0


def test_requeued_job_is_claimable_again(session):
    session.add(Job(document_id="doc-1", stage="extract", state=JobState.running))
    session.commit()
    # before recovery the orphan is invisible to the queue — that is the bug
    assert jobs.claim_next(session, stage="extract") is None

    jobs.requeue_orphaned(session)
    session.commit()

    claimed = jobs.claim_next(session, stage="extract")
    assert claimed is not None and claimed.document_id == "doc-1"
