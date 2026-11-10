"""
Pydantic schemas for request/response validation.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Project schemas
# ---------------------------------------------------------------------------
class ProjectCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=512)
    scholar_name: Optional[str] = Field(None, max_length=256)
    description: Optional[str] = None
    template_id: Optional[str] = None


class ProjectUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=512)
    scholar_name: Optional[str] = None
    description: Optional[str] = None
    template_id: Optional[str] = None


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    scholar_name: Optional[str]
    description: Optional[str]
    original_filename: str
    file_size_bytes: int
    mime_type: Optional[str]
    duration_seconds: Optional[float]
    width: Optional[int]
    height: Optional[int]
    fps: Optional[float]
    video_codec: Optional[str]
    audio_codec: Optional[str]
    template_id: Optional[str]
    min_clip_seconds: int = 30
    preferred_min_seconds: int = 45
    preferred_max_seconds: int = 90
    max_clip_seconds: int = 120
    status: str
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Job schemas
# ---------------------------------------------------------------------------
class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    status: str
    current_step: Optional[str]
    progress_percent: int
    step_message: Optional[str]
    audio_extracted: bool
    transcription_done: bool
    analysis_done: bool
    clips_rendered: bool
    error_message: Optional[str]
    retry_count: int
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]


# ---------------------------------------------------------------------------
# Clip schemas
# ---------------------------------------------------------------------------
class SubtitleSegment(BaseModel):
    start: float
    end: float
    text: str


class SubtitleStyle(BaseModel):
    font_family: str = "Arial"
    font_size: int = 48
    font_color: str = "#FFFFFF"
    background_color: str = "#000000CC"
    background_enabled: bool = True
    position: str = "bottom"  # top | middle | bottom
    bold: bool = True
    italic: bool = False


class ClipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    suggested_title: Optional[str]
    transcript_text: Optional[str]
    subtitle_segments: Optional[list[SubtitleSegment]] = None
    relevance_score: Optional[float]
    ai_reasoning: Optional[str]
    rank: int
    status: str
    output_path: Optional[str]
    rendered_url: Optional[str] = None
    render_status: str
    subtitles_enabled: bool = True
    subtitle_style: Optional[SubtitleStyle] = None
    created_at: datetime
    updated_at: datetime


class ClipUpdate(BaseModel):
    suggested_title: Optional[str] = None
    status: Optional[str] = None  # approved | rejected | pending
    start_seconds: Optional[float] = None
    end_seconds: Optional[float] = None
    transcript_text: Optional[str] = None
    subtitle_segments: Optional[list[SubtitleSegment]] = None
    subtitles_enabled: Optional[bool] = None
    subtitle_style: Optional[SubtitleStyle] = None


class RenderClipsRequest(BaseModel):
    clip_ids: list[str]
    template_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Template schemas
# ---------------------------------------------------------------------------
class LayoutConfig(BaseModel):
    background_color: str = "#000000"
    background_blur_strength: int = 20
    video_crop_mode: str = "blur_background"  # blur_background | center_crop | face_track
    video_position_y: float = 0.35  # 0.0 = top, 1.0 = bottom, 0.35 = upper-third
    header_enabled: bool = True
    header_height_px: int = 160
    footer_enabled: bool = True
    footer_height_px: int = 240
    title_font_size: int = 52
    title_color: str = "#FFFFFF"
    title_font: str = "Arial"
    scholar_font_size: int = 38
    scholar_color: str = "#D4AF37"  # Islamic gold
    scholar_font: str = "Arial"
    subtitle_position: str = "bottom"
    subtitle_font_size: int = 48
    subtitle_color: str = "#FFFFFF"
    subtitle_bg_color: str = "#000000CC"
    subtitle_font: str = "Arial"
    watermark_text: str = ""
    watermark_opacity: float = 0.6
    margins_px: int = 24


class TemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    description: Optional[str] = None
    is_default: bool = False
    output_width: int = 1080
    output_height: int = 1920
    output_fps: float = 30.0
    video_bitrate: str = "4M"
    audio_bitrate: str = "192k"
    layout_config: Optional[LayoutConfig] = None
    organization_name: Optional[str] = None


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_default: Optional[bool] = None
    output_width: Optional[int] = None
    output_height: Optional[int] = None
    output_fps: Optional[float] = None
    video_bitrate: Optional[str] = None
    audio_bitrate: Optional[str] = None
    layout_config: Optional[LayoutConfig] = None
    organization_name: Optional[str] = None


class TemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: Optional[str]
    is_default: bool
    output_width: int
    output_height: int
    output_fps: float
    video_bitrate: str
    audio_bitrate: str
    layout_config: Optional[Any]
    logo_path: Optional[str]
    organization_name: Optional[str]
    intro_path: Optional[str]
    outro_path: Optional[str]
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Progress event (SSE)
# ---------------------------------------------------------------------------
class ProgressEvent(BaseModel):
    job_id: str
    status: str
    step: str
    progress: int
    message: str
    data: Optional[dict] = None
