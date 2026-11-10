"""
Celery application for distributed background video processing (production / Docker).
Used when TASK_QUEUE_BACKEND=celery and Redis is available.
"""
from __future__ import annotations

import asyncio
import logging

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

try:
    from celery import Celery

    celery_app = Celery(
        "islamic_video_studio",
        broker=settings.celery_broker_url,
        backend=settings.celery_result_backend,
    )
    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        worker_concurrency=settings.max_concurrent_jobs,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
    )

    @celery_app.task(name="process_lecture_job", bind=True, max_retries=2)
    def process_lecture_job(self, job_id: str) -> None:
        from app.processing.pipeline import run_pipeline
        try:
            asyncio.run(run_pipeline(job_id))
        except Exception as exc:
            logger.exception("Celery job %s failed", job_id)
            raise self.retry(exc=exc, countdown=10)

    @celery_app.task(name="render_clips_task", bind=True, max_retries=2)
    def render_clips_task(
        self, project_id: str, clip_ids: list[str], template_id: str | None = None
    ) -> None:
        from app.processing.pipeline import render_approved_clips
        try:
            asyncio.run(render_approved_clips(project_id, clip_ids, template_id))
        except Exception as exc:
            logger.exception("Celery render failed for project %s", project_id)
            raise self.retry(exc=exc, countdown=10)

except ImportError:
    celery_app = None
    process_lecture_job = None
    render_clips_task = None
