"""
Async task queue backed by SQLite.
Runs jobs in a process pool so CPU-heavy work (FFmpeg, AI) doesn't block FastAPI.

Architecture:
  - Jobs are stored in DB (ProcessingJob table)
  - A background asyncio loop picks pending jobs and dispatches to ProcessPoolExecutor
  - WebSocket/SSE clients subscribe to progress updates via asyncio.Queue
  - On restart, jobs left in "running" state are reset to "pending" for retry
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from typing import Callable

from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import ProcessingJob

logger = logging.getLogger(__name__)
settings = get_settings()

# Maps job_id -> list of asyncio Queues listening for progress events
_progress_subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)

# Global executor — created once at startup
_executor: ProcessPoolExecutor | None = None
_queue_loop_task: asyncio.Task | None = None


async def startup() -> None:
    """Call on FastAPI startup."""
    global _executor, _queue_loop_task
    _executor = ProcessPoolExecutor(max_workers=settings.max_concurrent_jobs)

    # Reset any jobs that were interrupted mid-run
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(ProcessingJob).where(ProcessingJob.status == "running")
        )
        for job in result.scalars():
            job.status = "pending"
            job.current_step = None
            job.step_message = "Requeued after restart"
        await session.commit()

    if settings.task_queue_backend == "local":
        _queue_loop_task = asyncio.create_task(_worker_loop(), name="task-queue-loop")
        logger.info("Local task queue started")
    else:
        logger.info("Celery task queue mode enabled")


async def shutdown() -> None:
    """Call on FastAPI shutdown."""
    global _queue_loop_task, _executor
    if _queue_loop_task:
        _queue_loop_task.cancel()
    if _executor:
        _executor.shutdown(wait=False)
    logger.info("Task queue stopped")


async def _worker_loop() -> None:
    """
    Continuously poll for pending jobs and dispatch them.
    Uses a semaphore to limit concurrency.
    """
    sem = asyncio.Semaphore(settings.max_concurrent_jobs)

    while True:
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(ProcessingJob)
                    .where(ProcessingJob.status == "pending")
                    .order_by(ProcessingJob.created_at)
                    .limit(settings.max_concurrent_jobs)
                )
                pending_jobs = result.scalars().all()

            for job in pending_jobs:
                asyncio.create_task(_run_job_with_semaphore(job.id, sem))

        except Exception as exc:
            logger.exception("Worker loop error: %s", exc)

        await asyncio.sleep(2)  # Poll every 2 seconds


async def _run_job_with_semaphore(job_id: str, sem: asyncio.Semaphore) -> None:
    async with sem:
        await _run_job(job_id)


async def _run_job(job_id: str) -> None:
    """Mark job as running, then execute the pipeline in a thread."""
    from app.processing.pipeline import run_pipeline  # avoid circular import

    async with AsyncSessionLocal() as session:
        job = await session.get(ProcessingJob, job_id)
        if not job or job.status != "pending":
            return
        job.status = "running"
        job.started_at = datetime.utcnow()
        await session.commit()

    logger.info("Starting job %s", job_id)

    try:
        loop = asyncio.get_event_loop()
        # Run pipeline in a thread (not process) since it uses async I/O internally
        await loop.run_in_executor(None, _sync_pipeline_runner, job_id)
    except Exception as exc:
        logger.exception("Job %s failed: %s", job_id, exc)
        async with AsyncSessionLocal() as session:
            job = await session.get(ProcessingJob, job_id)
            if job:
                job.status = "failed"
                job.error_message = str(exc)
                job.completed_at = datetime.utcnow()
            await session.commit()
        await publish_progress(
            job_id, "failed", "error", 0, f"Job failed: {exc}"
        )


def _sync_pipeline_runner(job_id: str) -> None:
    """Run the async pipeline in a new event loop (called from thread executor)."""
    import asyncio as _asyncio
    from app.processing.pipeline import run_pipeline

    _asyncio.run(run_pipeline(job_id))


async def enqueue_job(project_id: str) -> str:
    """Create a new ProcessingJob and return its ID."""
    from app.models import ProcessingJob

    async with AsyncSessionLocal() as session:
        job = ProcessingJob(project_id=project_id, status="pending")
        session.add(job)
        await session.commit()
        await session.refresh(job)
        job_id = job.id

    if settings.task_queue_backend == "celery":
        from app.core.celery_app import process_lecture_job
        if process_lecture_job is None:
            raise RuntimeError("Celery is not installed. Run: pip install celery redis")
        process_lecture_job.delay(job_id)

    return job_id


async def publish_progress(
    job_id: str, status: str, step: str, progress: int, message: str, data: dict | None = None
) -> None:
    """Broadcast a progress event to all subscribers of this job."""
    event = {
        "job_id": job_id,
        "status": status,
        "step": step,
        "progress": progress,
        "message": message,
        "data": data or {},
    }
    for q in _progress_subscribers.get(job_id, []):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass


def subscribe_to_job(job_id: str) -> asyncio.Queue:
    """Return a queue that receives progress events for the given job."""
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _progress_subscribers[job_id].append(q)
    return q


def unsubscribe_from_job(job_id: str, q: asyncio.Queue) -> None:
    """Remove a subscriber queue."""
    subs = _progress_subscribers.get(job_id, [])
    if q in subs:
        subs.remove(q)
    if not subs:
        _progress_subscribers.pop(job_id, None)
