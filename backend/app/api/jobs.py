"""
Jobs API — query job status and subscribe to live progress via SSE.
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.task_queue import subscribe_to_job, unsubscribe_from_job
from app.database import AsyncSessionLocal, get_db
from app.models import ProcessingJob
from app.schemas import JobResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """Get current job status."""
    job = await db.get(ProcessingJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/{job_id}/progress")
async def stream_job_progress(job_id: str, db: AsyncSession = Depends(get_db)):
    """
    Server-Sent Events stream for live job progress.
    Connect once and receive updates until job completes or fails.
    """
    job = await db.get(ProcessingJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # If already completed, return final state immediately
    if job.status in ("completed", "failed"):
        async def immediate_response():
            data = json.dumps({
                "job_id": job_id,
                "status": job.status,
                "step": job.current_step or job.status,
                "progress": job.progress_percent,
                "message": job.step_message or job.status,
                "data": {},
            })
            yield f"data: {data}\n\n"

        return StreamingResponse(immediate_response(), media_type="text/event-stream")

    async def event_generator():
        queue = subscribe_to_job(job_id)
        try:
            # Send current state first
            current = {
                "job_id": job_id,
                "status": job.status,
                "step": job.current_step or "pending",
                "progress": job.progress_percent,
                "message": job.step_message or "Waiting to start...",
                "data": {},
            }
            yield f"data: {json.dumps(current)}\n\n"

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=3.0)
                    yield f"data: {json.dumps(event)}\n\n"

                    if event.get("status") in ("completed", "failed"):
                        break

                except asyncio.TimeoutError:
                    # Also check DB state (handles cross-process Celery updates or heartbeat)
                    async with AsyncSessionLocal() as poll_db:
                        fresh_job = await poll_db.get(ProcessingJob, job_id)
                        if fresh_job:
                            snapshot = {
                                "job_id": job_id,
                                "status": fresh_job.status,
                                "step": fresh_job.current_step or fresh_job.status,
                                "progress": fresh_job.progress_percent,
                                "message": fresh_job.step_message or fresh_job.status,
                                "data": {},
                            }
                            yield f"data: {json.dumps(snapshot)}\n\n"
                            if fresh_job.status in ("completed", "failed"):
                                break
                    yield ": heartbeat\n\n"

        except asyncio.CancelledError:
            pass
        finally:
            unsubscribe_from_job(job_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
