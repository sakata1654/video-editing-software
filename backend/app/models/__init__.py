"""
SQLAlchemy ORM models for all database entities.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Project — one uploaded lecture
# ---------------------------------------------------------------------------
class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    scholar_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Upload info
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    mime_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # Video metadata (filled after FFprobe)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fps: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    video_codec: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    audio_codec: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Template to use for rendering
    template_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("templates.id"), nullable=True
    )

    # Duration preferences (seconds)
    min_clip_seconds: Mapped[int] = mapped_column(Integer, default=30)
    preferred_min_seconds: Mapped[int] = mapped_column(Integer, default=45)
    preferred_max_seconds: Mapped[int] = mapped_column(Integer, default=90)
    max_clip_seconds: Mapped[int] = mapped_column(Integer, default=120)

    # Status
    status: Mapped[str] = mapped_column(String(32), default="uploaded")
    # uploaded | processing | completed | failed

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    jobs: Mapped[list["ProcessingJob"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    clips: Mapped[list["Clip"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    template: Mapped[Optional["Template"]] = relationship(back_populates="projects")


# ---------------------------------------------------------------------------
# ProcessingJob — tracks the full pipeline execution
# ---------------------------------------------------------------------------
class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id"), nullable=False
    )

    status: Mapped[str] = mapped_column(String(32), default="pending")
    # pending | running | completed | failed | cancelled

    # Pipeline step tracking
    current_step: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    step_message: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # Pipeline step completion flags
    audio_extracted: Mapped[bool] = mapped_column(Boolean, default=False)
    transcription_done: Mapped[bool] = mapped_column(Boolean, default=False)
    analysis_done: Mapped[bool] = mapped_column(Boolean, default=False)
    clips_rendered: Mapped[bool] = mapped_column(Boolean, default=False)

    # Result data
    transcript_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="jobs")


# ---------------------------------------------------------------------------
# Clip — one candidate clip identified from the lecture
# ---------------------------------------------------------------------------
class Clip(Base):
    __tablename__ = "clips"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id"), nullable=False
    )

    # Timestamps (seconds from start of original video)
    start_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    end_seconds: Mapped[float] = mapped_column(Float, nullable=False)

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds

    # AI-generated metadata
    suggested_title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    transcript_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # JSON list of {start, end, text} word-level segments
    subtitle_segments_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    relevance_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ai_reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rank: Mapped[int] = mapped_column(Integer, default=0)

    # User review
    status: Mapped[str] = mapped_column(String(32), default="pending")
    # pending | approved | rejected

    # Rendered output
    output_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    render_status: Mapped[str] = mapped_column(String(32), default="not_started")
    # not_started | rendering | completed | failed

    # Subtitle customization overrides (JSON)
    subtitles_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    subtitle_style_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="clips")


# ---------------------------------------------------------------------------
# Template — reusable video layout configuration
# ---------------------------------------------------------------------------
class Template(Base):
    __tablename__ = "templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    # Output format
    output_width: Mapped[int] = mapped_column(Integer, default=1080)
    output_height: Mapped[int] = mapped_column(Integer, default=1920)
    output_fps: Mapped[float] = mapped_column(Float, default=30.0)
    video_bitrate: Mapped[str] = mapped_column(String(16), default="4M")
    audio_bitrate: Mapped[str] = mapped_column(String(16), default="192k")

    # Visual layout (stored as JSON for flexibility)
    # Contains: background_color, background_blur_strength, video_crop_mode,
    #           video_position, header_config, footer_config,
    #           title_config, scholar_config, subtitle_config,
    #           logo_path, watermark_config, margins
    layout_config: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Branding
    logo_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    organization_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    # Intro/outro clip paths
    intro_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    outro_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    projects: Mapped[list["Project"]] = relationship(back_populates="template")
