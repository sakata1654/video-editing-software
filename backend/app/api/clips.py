"""
Clips API — manage, approve, edit, render, regenerate, and download clips.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.storage import get_storage
from app.database import get_db
from app.models import Clip
from app.schemas import ClipResponse, ClipUpdate, RenderClipsRequest

logger = logging.getLogger(__name__)
settings = get_settings()
storage = get_storage()
router = APIRouter(prefix="/api/clips", tags=["clips"])


def _clip_to_response(clip: Clip) -> dict:
    """Convert Clip ORM model to response dict."""
    segments = None
    if clip.subtitle_segments_json:
        try:
            segments = json.loads(clip.subtitle_segments_json)
        except json.JSONDecodeError:
            segments = None

    sub_style = None
    if clip.subtitle_style_json:
        try:
            sub_style = json.loads(clip.subtitle_style_json)
        except json.JSONDecodeError:
            sub_style = None

    rendered_url = None
    if clip.output_path and clip.render_status == "completed":
        rendered_url = storage.absolute_to_url(clip.output_path)

    return {
        "id": clip.id,
        "project_id": clip.project_id,
        "start_seconds": clip.start_seconds,
        "end_seconds": clip.end_seconds,
        "duration_seconds": max(0.0, clip.end_seconds - clip.start_seconds),
        "suggested_title": clip.suggested_title,
        "transcript_text": clip.transcript_text,
        "subtitle_segments": segments,
        "relevance_score": clip.relevance_score,
        "ai_reasoning": clip.ai_reasoning,
        "rank": clip.rank,
        "status": clip.status,
        "output_path": clip.output_path,
        "rendered_url": rendered_url,
        "render_status": clip.render_status,
        "subtitles_enabled": clip.subtitles_enabled,
        "subtitle_style": sub_style,
        "created_at": clip.created_at,
        "updated_at": clip.updated_at,
    }


@router.get("/project/{project_id}", response_model=list[ClipResponse])
async def list_project_clips(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """List all clips for a project, sorted by rank."""
    result = await db.execute(
        select(Clip)
        .where(Clip.project_id == project_id)
        .order_by(Clip.rank)
    )
    clips = result.scalars().all()
    return [_clip_to_response(c) for c in clips]


@router.get("/{clip_id}", response_model=ClipResponse)
async def get_clip(clip_id: str, db: AsyncSession = Depends(get_db)):
    clip = await db.get(Clip, clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    return _clip_to_response(clip)


@router.patch("/{clip_id}", response_model=ClipResponse)
async def update_clip(
    clip_id: str,
    update: ClipUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update clip title, status (approve/reject), timestamps, transcript, or subtitle styling."""
    clip = await db.get(Clip, clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    if update.suggested_title is not None:
        clip.suggested_title = update.suggested_title
    if update.status is not None:
        if update.status not in ("approved", "rejected", "pending"):
            raise HTTPException(
                status_code=400, detail="Status must be approved, rejected, or pending"
            )
        clip.status = update.status
    if update.start_seconds is not None:
        clip.start_seconds = max(0.0, update.start_seconds)
    if update.end_seconds is not None:
        if update.end_seconds <= clip.start_seconds:
            raise HTTPException(
                status_code=400, detail="end_seconds must be greater than start_seconds"
            )
        clip.end_seconds = update.end_seconds
    if update.transcript_text is not None:
        clip.transcript_text = update.transcript_text
    if update.subtitle_segments is not None:
        clip.subtitle_segments_json = json.dumps(
            [s.model_dump() for s in update.subtitle_segments], ensure_ascii=False
        )
    if update.subtitles_enabled is not None:
        clip.subtitles_enabled = update.subtitles_enabled
    if update.subtitle_style is not None:
        clip.subtitle_style_json = update.subtitle_style.model_dump_json()

    await db.flush()
    await db.refresh(clip)
    return _clip_to_response(clip)


@router.post("/render", status_code=status.HTTP_202_ACCEPTED)
async def render_clips(
    request: RenderClipsRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger rendering for a list of clip IDs.
    Processing happens in background — check clip.render_status for updates.
    """
    if not request.clip_ids:
        raise HTTPException(status_code=400, detail="No clip IDs provided")

    result = await db.execute(
        select(Clip).where(Clip.id.in_(request.clip_ids))
    )
    clips = result.scalars().all()

    if len(clips) != len(request.clip_ids):
        raise HTTPException(status_code=404, detail="One or more clips not found")

    project_id = clips[0].project_id
    for c in clips:
        c.render_status = "rendering"
    await db.flush()

    if settings.task_queue_backend == "celery":
        from app.core.celery_app import render_clips_task
        if render_clips_task is None:
            raise HTTPException(status_code=500, detail="Celery not installed")
        render_clips_task.delay(project_id, request.clip_ids, request.template_id)
    else:
        background_tasks.add_task(
            _run_render_async,
            project_id,
            request.clip_ids,
            request.template_id,
        )

    return {
        "message": f"Rendering {len(clips)} clip(s) in background",
        "count": len(clips),
    }


@router.post("/{clip_id}/regenerate", status_code=status.HTTP_202_ACCEPTED)
async def regenerate_clip(
    clip_id: str,
    background_tasks: BackgroundTasks,
    template_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Re-render a single clip with its current timestamps, subtitle edits, and template."""
    clip = await db.get(Clip, clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")

    clip.render_status = "rendering"
    await db.flush()

    if settings.task_queue_backend == "celery":
        from app.core.celery_app import render_clips_task
        if render_clips_task is None:
            raise HTTPException(status_code=500, detail="Celery not installed")
        render_clips_task.delay(clip.project_id, [clip_id], template_id)
    else:
        background_tasks.add_task(
            _run_render_async,
            clip.project_id,
            [clip_id],
            template_id,
        )

    return {"message": "Regenerating clip in background", "clip_id": clip_id}


async def _run_render_async(
    project_id: str, clip_ids: list[str], template_id: Optional[str]
) -> None:
    from app.processing.pipeline import render_approved_clips
    try:
        await render_approved_clips(project_id, clip_ids, template_id)
    except Exception as e:
        logger.exception("Background render failed: %s", e)


@router.get("/{clip_id}/download")
async def download_clip(clip_id: str, db: AsyncSession = Depends(get_db)):
    """Download a rendered clip video file."""
    clip = await db.get(Clip, clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    if not clip.output_path or clip.render_status != "completed":
        raise HTTPException(
            status_code=400,
            detail="Clip has not been rendered yet. Render it first.",
        )

    output_path = storage.ensure_local(clip.output_path)
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="Rendered file not found on disk")

    safe_title = (clip.suggested_title or "clip").replace("/", "-").replace("\\", "-")[:60]
    return FileResponse(
        path=str(output_path),
        media_type="video/mp4",
        filename=f"{safe_title}.mp4",
    )


def _cleanup_file(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


@router.post("/download-zip")
async def download_clips_zip(
    clip_ids: list[str],
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Download multiple rendered clips as a ZIP archive without loading videos into RAM."""
    result = await db.execute(
        select(Clip).where(Clip.id.in_(clip_ids))
    )
    clips = result.scalars().all()

    ready_clips = [c for c in clips if c.output_path and c.render_status == "completed"]
    if not ready_clips:
        raise HTTPException(
            status_code=400,
            detail="No rendered clips found in the provided IDs",
        )

    tmp_fd, tmp_zip_path = tempfile.mkstemp(suffix=".zip", dir=str(settings.temp_dir))
    os.close(tmp_fd)

    try:
        with zipfile.ZipFile(tmp_zip_path, "w", zipfile.ZIP_STORED) as zf:
            used_names: set[str] = set()
            for clip in ready_clips:
                path = storage.ensure_local(clip.output_path)
                if path.exists():
                    base = (clip.suggested_title or clip.id[:8]).replace("/", "-").replace("\\", "-")[:60]
                    name = f"{base}.mp4"
                    if name in used_names:
                        name = f"{base}_{clip.id[:6]}.mp4"
                    used_names.add(name)
                    zf.write(path, name)
    except Exception:
        _cleanup_file(tmp_zip_path)
        raise

    background_tasks.add_task(_cleanup_file, tmp_zip_path)
    return FileResponse(
        path=tmp_zip_path,
        media_type="application/zip",
        filename="islamic_lecture_clips.zip",
    )
