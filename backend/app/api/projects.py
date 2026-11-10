"""
Projects API — upload video, create projects, trigger processing.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.storage import get_storage
from app.core.task_queue import enqueue_job
from app.database import get_db
from app.models import ProcessingJob, Project
from app.processing.video_inspector import inspect_video
from app.schemas import JobResponse, ProjectCreate, ProjectResponse, ProjectUpdate

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/api/projects", tags=["projects"])

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv", ".wmv", ".m4v"}
ALLOWED_MIME_TYPES = {
    "video/mp4", "video/quicktime", "video/x-matroska",
    "video/x-msvideo", "video/webm", "video/x-flv",
    "video/x-ms-wmv", "video/mp4",
}


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    file: UploadFile = File(..., description="Lecture video file"),
    title: str = Form(..., min_length=1, max_length=512),
    scholar_name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    template_id: Optional[str] = Form(None),
    min_clip_seconds: int = Form(30),
    preferred_min_seconds: int = Form(45),
    preferred_max_seconds: int = Form(90),
    max_clip_seconds: int = Form(120),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a lecture video and create a new project.
    Returns immediately with project data; processing is started in background.
    """
    # Validate file extension
    file_ext = Path(file.filename or "").suffix.lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{file_ext}'. Supported: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    # Check file size
    max_size = settings.max_upload_size_mb * 1024 * 1024
    # We'll check during read to avoid loading everything into RAM
    storage = get_storage()

    # Save the file (streaming)
    safe_name = f"{uuid.uuid4().hex}{file_ext}"
    dest_path = settings.uploads_dir / safe_name

    try:
        total_bytes = 0
        with open(dest_path, "wb") as out:
            while chunk := await file.read(1024 * 1024):  # 1MB chunks
                total_bytes += len(chunk)
                if total_bytes > max_size:
                    out.close()
                    dest_path.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large. Maximum size: {settings.max_upload_size_mb} MB",
                    )
                out.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        dest_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")

    # Inspect the video metadata
    try:
        meta = inspect_video(str(dest_path))
    except Exception as e:
        dest_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=422,
            detail=f"Invalid video file: {e}",
        )

    # Create project record
    project = Project(
        title=title.strip(),
        scholar_name=scholar_name.strip() if scholar_name else None,
        description=description,
        original_filename=file.filename or safe_name,
        file_path=str(dest_path),
        file_size_bytes=total_bytes,
        mime_type=file.content_type,
        duration_seconds=meta.duration_seconds,
        width=meta.width,
        height=meta.height,
        fps=meta.fps,
        video_codec=meta.video_codec,
        audio_codec=meta.audio_codec,
        template_id=template_id,
        min_clip_seconds=max(10, min_clip_seconds),
        preferred_min_seconds=max(15, preferred_min_seconds),
        preferred_max_seconds=min(300, preferred_max_seconds),
        max_clip_seconds=min(300, max(min_clip_seconds, max_clip_seconds)),
        status="uploaded",
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)

    return project


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project).order_by(Project.created_at.desc()).offset(skip).limit(limit)
    )
    return result.scalars().all()


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project_id: str, db: AsyncSession = Depends(get_db)):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    update: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    for field, value in update.model_dump(exclude_none=True).items():
        setattr(project, field, value)

    await db.flush()
    await db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: str, db: AsyncSession = Depends(get_db)):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Remove uploaded file
    try:
        Path(project.file_path).unlink(missing_ok=True)
    except Exception:
        pass

    await db.delete(project)


@router.post("/{project_id}/process", response_model=JobResponse)
async def start_processing(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Enqueue the full AI processing pipeline for this project.
    Returns a job ID immediately — poll /api/jobs/{job_id} for status.
    """
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.status == "processing":
        raise HTTPException(status_code=409, detail="Project is already being processed")

    # Mark project as processing
    project.status = "processing"
    await db.flush()

    # Create job
    job_id = await enqueue_job(project_id)

    # Return job details
    result = await db.execute(
        select(ProcessingJob).where(ProcessingJob.id == job_id)
    )
    job = result.scalar_one()
    return job


@router.get("/{project_id}/job", response_model=Optional[JobResponse])
async def get_latest_project_job(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get the latest processing job for a project."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    result = await db.execute(
        select(ProcessingJob)
        .where(ProcessingJob.project_id == project_id)
        .order_by(ProcessingJob.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


@router.get("/{project_id}/transcript")
async def get_project_transcript(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Return the full lecture transcript with timestamps from the latest completed transcription job."""
    import json

    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    result = await db.execute(
        select(ProcessingJob)
        .where(
            ProcessingJob.project_id == project_id,
            ProcessingJob.transcript_json.isnot(None),
        )
        .order_by(ProcessingJob.created_at.desc())
        .limit(1)
    )
    job = result.scalar_one_or_none()
    if not job or not job.transcript_json:
        return {"language": None, "full_text": "", "segments": []}

    return json.loads(job.transcript_json)
