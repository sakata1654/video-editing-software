"""
Templates API — create and manage video layout templates.
"""
from __future__ import annotations

import json
import logging

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import get_storage
from app.database import get_db
from app.models import Template
from app.schemas import TemplateCreate, TemplateResponse, TemplateUpdate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/templates", tags=["templates"])


@router.post("", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    template_in: TemplateCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new video template."""
    # If this is set as default, unset previous default
    if template_in.is_default:
        result = await db.execute(
            select(Template).where(Template.is_default == True)
        )
        for t in result.scalars():
            t.is_default = False

    layout_json = None
    if template_in.layout_config:
        layout_json = template_in.layout_config.model_dump_json()

    template = Template(
        name=template_in.name,
        description=template_in.description,
        is_default=template_in.is_default,
        output_width=template_in.output_width,
        output_height=template_in.output_height,
        output_fps=template_in.output_fps,
        video_bitrate=template_in.video_bitrate,
        audio_bitrate=template_in.audio_bitrate,
        layout_config=layout_json,
        organization_name=template_in.organization_name,
    )
    db.add(template)
    await db.flush()
    await db.refresh(template)

    # Parse layout_config JSON back to dict for response
    return _template_to_response(template)


@router.get("", response_model=list[TemplateResponse])
async def list_templates(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Template).order_by(Template.is_default.desc(), Template.created_at.desc())
    )
    return [_template_to_response(t) for t in result.scalars().all()]


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(template_id: str, db: AsyncSession = Depends(get_db)):
    t = await db.get(Template, template_id)
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    return _template_to_response(t)


@router.patch("/{template_id}", response_model=TemplateResponse)
async def update_template(
    template_id: str,
    update: TemplateUpdate,
    db: AsyncSession = Depends(get_db),
):
    t = await db.get(Template, template_id)
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")

    if update.is_default is True:
        # Unset other defaults
        result = await db.execute(select(Template).where(Template.is_default == True))
        for other in result.scalars():
            if other.id != template_id:
                other.is_default = False

    for field, value in update.model_dump(exclude_none=True).items():
        if field == "layout_config" and value is not None:
            setattr(t, "layout_config", update.layout_config.model_dump_json())
        else:
            setattr(t, field, value)

    await db.flush()
    await db.refresh(t)
    return _template_to_response(t)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(template_id: str, db: AsyncSession = Depends(get_db)):
    t = await db.get(Template, template_id)
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    await db.delete(t)


@router.post("/{template_id}/logo", response_model=TemplateResponse)
async def upload_template_logo(
    template_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a logo image (PNG/JPG/WEBP) for a template."""
    t = await db.get(Template, template_id)
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")

    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise HTTPException(status_code=400, detail="Logo must be PNG, JPG, or WEBP")

    storage = get_storage()
    t.logo_path = storage.save_asset(file.file, "logos", file.filename or f"logo{ext}")
    await db.flush()
    await db.refresh(t)
    return _template_to_response(t)


@router.post("/{template_id}/intro", response_model=TemplateResponse)
async def upload_template_intro(
    template_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload an intro video clip for a template."""
    t = await db.get(Template, template_id)
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")

    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".mp4", ".mov", ".mkv", ".webm"}:
        raise HTTPException(status_code=400, detail="Intro must be a video file (MP4, MOV, MKV, WebM)")

    storage = get_storage()
    t.intro_path = storage.save_asset(file.file, "intros", file.filename or f"intro{ext}")
    await db.flush()
    await db.refresh(t)
    return _template_to_response(t)


@router.post("/{template_id}/outro", response_model=TemplateResponse)
async def upload_template_outro(
    template_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload an outro video clip for a template."""
    t = await db.get(Template, template_id)
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")

    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".mp4", ".mov", ".mkv", ".webm"}:
        raise HTTPException(status_code=400, detail="Outro must be a video file (MP4, MOV, MKV, WebM)")

    storage = get_storage()
    t.outro_path = storage.save_asset(file.file, "outros", file.filename or f"outro{ext}")
    await db.flush()
    await db.refresh(t)
    return _template_to_response(t)


def _template_to_response(t: Template) -> dict:
    layout = None
    if t.layout_config:
        try:
            layout = json.loads(t.layout_config)
        except json.JSONDecodeError:
            layout = None

    return {
        "id": t.id,
        "name": t.name,
        "description": t.description,
        "is_default": t.is_default,
        "output_width": t.output_width,
        "output_height": t.output_height,
        "output_fps": t.output_fps,
        "video_bitrate": t.video_bitrate,
        "audio_bitrate": t.audio_bitrate,
        "layout_config": layout,
        "logo_path": t.logo_path,
        "organization_name": t.organization_name,
        "intro_path": t.intro_path,
        "outro_path": t.outro_path,
        "created_at": t.created_at,
        "updated_at": t.updated_at,
    }
