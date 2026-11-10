"""
Main processing pipeline — orchestrates all stages:
  1. Inspect video metadata (FFprobe)
  2. Extract audio (FFmpeg)
  3. Transcribe lecture (Whisper)
  4. Analyze transcript, select clips (LLM)
  5. Store clip candidates in DB
  6. Render approved clips (FFmpeg)

Each step publishes progress via the task queue's pub/sub system.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.core.storage import get_storage
from app.core.task_queue import publish_progress
from app.database import AsyncSessionLocal
from app.models import Clip, ProcessingJob, Project
from app.processing.analyzer import analyze_transcript
from app.processing.audio_extractor import extract_audio
from app.processing.subtitle_engine import SubtitleStyle
from app.processing.transcriber import TranscriptionResult, get_transcription_provider
from app.processing.video_inspector import inspect_video
from app.processing.video_renderer import RenderConfig, render_clip

logger = logging.getLogger(__name__)
settings = get_settings()
storage = get_storage()

# Step names and their progress percentages
STEPS = {
    "inspecting":      (5,  "Inspecting video"),
    "extracting":      (15, "Extracting audio"),
    "transcribing":    (35, "Transcribing lecture"),
    "analyzing":       (55, "Analyzing content"),
    "saving_clips":    (65, "Saving clip suggestions"),
    "complete":        (100, "Processing complete"),
}


async def run_pipeline(job_id: str) -> None:
    """
    Full processing pipeline for one job.
    Runs asynchronously, publishes progress updates.
    """
    async with AsyncSessionLocal() as session:
        job = await session.get(ProcessingJob, job_id)
        if not job:
            logger.error("Job not found: %s", job_id)
            return
        project = await session.get(Project, job.project_id)
        if not project:
            await _fail_job(job_id, "Project not found")
            return

        project_id = project.id
        video_path = str(storage.ensure_local(project.file_path))
        lecture_title = project.title
        scholar_name = project.scholar_name
        min_clip_seconds = project.min_clip_seconds
        max_clip_seconds = project.max_clip_seconds

    try:
        # ------------------------------------------------------------------ #
        # STEP 1: Inspect video
        # ------------------------------------------------------------------ #
        await _update_step(job_id, "inspecting")
        meta = inspect_video(video_path)

        async with AsyncSessionLocal() as session:
            proj = await session.get(Project, project_id)
            proj.duration_seconds = meta.duration_seconds
            proj.width = meta.width
            proj.height = meta.height
            proj.fps = meta.fps
            proj.video_codec = meta.video_codec
            proj.audio_codec = meta.audio_codec
            await session.commit()

        # ------------------------------------------------------------------ #
        # STEP 2: Extract audio
        # ------------------------------------------------------------------ #
        await _update_step(job_id, "extracting")

        audio_filename = f"{project_id}_audio.wav"
        audio_path = settings.temp_dir / audio_filename

        if not meta.has_audio:
            raise ValueError("Video has no audio stream — cannot transcribe")

        extract_audio(video_path, audio_path)

        async with AsyncSessionLocal() as session:
            job = await session.get(ProcessingJob, job_id)
            job.audio_extracted = True
            await session.commit()

        # ------------------------------------------------------------------ #
        # STEP 3: Transcribe
        # ------------------------------------------------------------------ #
        await _update_step(job_id, "transcribing", "This may take several minutes...")

        provider = get_transcription_provider()
        transcription = await provider.transcribe(audio_path)

        # Clean up audio temp file
        try:
            audio_path.unlink()
        except Exception:
            pass

        async with AsyncSessionLocal() as session:
            job = await session.get(ProcessingJob, job_id)
            job.transcription_done = True
            job.transcript_json = transcription.to_json()
            await session.commit()

        # ------------------------------------------------------------------ #
        # STEP 4: Analyze transcript — LLM clip selection
        # ------------------------------------------------------------------ #
        await _update_step(job_id, "analyzing", "AI is finding the best clips...")

        candidates = await analyze_transcript(
            result=transcription,
            lecture_title=lecture_title,
            scholar_name=scholar_name,
            min_seconds=min_clip_seconds,
            max_seconds=max_clip_seconds,
        )

        async with AsyncSessionLocal() as session:
            job = await session.get(ProcessingJob, job_id)
            job.analysis_done = True
            await session.commit()

        # ------------------------------------------------------------------ #
        # STEP 5: Save clip candidates to DB
        # ------------------------------------------------------------------ #
        await _update_step(job_id, "saving_clips")

        async with AsyncSessionLocal() as session:
            for candidate in candidates:
                # Build subtitle segments for this clip
                clip_segments = [
                    {"start": s.start, "end": s.end, "text": s.text}
                    for s in transcription.segments
                    if s.start >= candidate.start_seconds and s.end <= candidate.end_seconds + 1.0
                ]

                clip = Clip(
                    project_id=project_id,
                    start_seconds=candidate.start_seconds,
                    end_seconds=candidate.end_seconds,
                    suggested_title=candidate.suggested_title,
                    transcript_text=candidate.transcript_text,
                    subtitle_segments_json=json.dumps(clip_segments),
                    relevance_score=candidate.relevance_score,
                    ai_reasoning=candidate.reasoning,
                    rank=candidate.rank,
                    status="pending",
                )
                session.add(clip)

            # Mark project complete
            project = await session.get(Project, project_id)
            project.status = "completed"

            job = await session.get(ProcessingJob, job_id)
            job.status = "completed"
            job.clips_rendered = False  # Will be True after user triggers render
            job.completed_at = datetime.utcnow()
            job.progress_percent = 100
            job.current_step = "complete"

            await session.commit()

        await publish_progress(
            job_id, "completed", "complete", 100,
            f"Found {len(candidates)} clip suggestions. Review and approve them!",
            data={"clip_count": len(candidates)},
        )

        logger.info("Pipeline completed: job=%s, clips=%d", job_id, len(candidates))

    except Exception as exc:
        logger.exception("Pipeline failed: job=%s", job_id)
        await _fail_job(job_id, str(exc))
        async with AsyncSessionLocal() as session:
            proj = await session.get(Project, project_id)
            if proj:
                proj.status = "failed"
            await session.commit()


async def render_approved_clips(project_id: str, clip_ids: list[str], template_id: str | None) -> None:
    """
    Render approved clips using saved template settings.
    Called separately from main pipeline (user-triggered).
    """
    from app.models import Template

    async with AsyncSessionLocal() as session:
        project = await session.get(Project, project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")

        # Load template
        template = None
        effective_template_id = template_id or project.template_id
        if effective_template_id:
            template = await session.get(Template, effective_template_id)
        if not template:
            # Try default template
            result = await session.execute(
                select(Template).where(Template.is_default == True).limit(1)
            )
            template = result.scalar_one_or_none()

        # Load clips
        result = await session.execute(
            select(Clip).where(
                Clip.id.in_(clip_ids),
                Clip.project_id == project_id,
            )
        )
        clips = result.scalars().all()

        if not clips:
            raise ValueError("No clips found to render")

        project_data = {
            "file_path": project.file_path,
            "title": project.title,
            "scholar_name": project.scholar_name,
        }

        template_data = _extract_template_data(template)

        clip_data = [
            {
                "id": c.id,
                "start_seconds": c.start_seconds,
                "end_seconds": c.end_seconds,
                "suggested_title": c.suggested_title,
                "subtitle_segments": json.loads(c.subtitle_segments_json or "[]"),
                "subtitles_enabled": c.subtitles_enabled,
                "subtitle_style": json.loads(c.subtitle_style_json) if c.subtitle_style_json else None,
            }
            for c in clips
        ]

    local_input = str(storage.ensure_local(project_data["file_path"]))

    # Render each clip
    for clip_info in clip_data:
        clip_id = clip_info["id"]
        try:
            async with AsyncSessionLocal() as session:
                clip = await session.get(Clip, clip_id)
                clip.render_status = "rendering"
                await session.commit()

            output_filename = f"{project_id}_{clip_id[:8]}.mp4"
            output_path = storage.get_output_path(output_filename)

            # Build subtitle style: per-clip override > template default
            clip_sub = clip_info.get("subtitle_style") or {}
            bg_enabled = clip_sub.get("background_enabled", True)
            bg_color = (
                clip_sub.get("background_color", template_data.get("subtitle_bg_color", "#000000CC"))
                if bg_enabled
                else "#00000000"
            )
            sub_style = SubtitleStyle(
                font_family=clip_sub.get("font_family", template_data.get("subtitle_font", "Arial")),
                font_size=clip_sub.get("font_size", template_data.get("subtitle_font_size", 48)),
                font_color=clip_sub.get("font_color", template_data.get("subtitle_color", "#FFFFFF")),
                background_color=bg_color,
                position=clip_sub.get("position", template_data.get("subtitle_position", "bottom")),
                bold=clip_sub.get("bold", True),
                italic=clip_sub.get("italic", False),
            )

            render_config = RenderConfig(
                input_path=local_input,
                start_seconds=clip_info["start_seconds"],
                end_seconds=clip_info["end_seconds"],
                output_path=str(output_path),
                output_width=template_data.get("output_width", 1080),
                output_height=template_data.get("output_height", 1920),
                output_fps=template_data.get("output_fps", 30.0),
                video_bitrate=template_data.get("video_bitrate", "4M"),
                audio_bitrate=template_data.get("audio_bitrate", "192k"),
                background_color=template_data.get("background_color", "#000000"),
                video_crop_mode=template_data.get("video_crop_mode", "blur_background"),
                background_blur_strength=template_data.get("background_blur_strength", 20),
                video_position_y=template_data.get("video_position_y", 0.5),
                lecture_title=project_data["title"],
                scholar_name=project_data["scholar_name"],
                organization_name=template_data.get("organization_name"),
                logo_path=template_data.get("logo_path"),
                watermark_text=template_data.get("watermark_text"),
                watermark_opacity=template_data.get("watermark_opacity", 0.6),
                subtitles_enabled=clip_info.get("subtitles_enabled", True),
                subtitle_segments=clip_info["subtitle_segments"],
                subtitle_style=sub_style,
                header_enabled=template_data.get("header_enabled", True),
                header_height=template_data.get("header_height_px", 180),
                footer_enabled=template_data.get("footer_enabled", True),
                footer_height=template_data.get("footer_height_px", 220),
                title_font=template_data.get("title_font", "Arial"),
                title_font_size=template_data.get("title_font_size", 48),
                title_color=template_data.get("title_color", "#FFFFFF"),
                scholar_font=template_data.get("scholar_font", "Arial"),
                scholar_font_size=template_data.get("scholar_font_size", 36),
                scholar_color=template_data.get("scholar_color", "#D4AF37"),
                margins=template_data.get("margins_px", 32),
                intro_path=template_data.get("intro_path"),
                outro_path=template_data.get("outro_path"),
            )

            render_clip(render_config)
            stored_output = storage.upload_output(output_path, output_filename)

            async with AsyncSessionLocal() as session:
                clip = await session.get(Clip, clip_id)
                clip.render_status = "completed"
                clip.output_path = stored_output
                await session.commit()

        except Exception as exc:
            logger.exception("Failed to render clip %s", clip_id)
            async with AsyncSessionLocal() as session:
                clip = await session.get(Clip, clip_id)
                if clip:
                    clip.render_status = "failed"
                await session.commit()


def _extract_template_data(template) -> dict:
    """Extract template settings as a flat dict."""
    data = {}
    if template:
        data["output_width"] = template.output_width
        data["output_height"] = template.output_height
        data["output_fps"] = template.output_fps
        data["video_bitrate"] = template.video_bitrate
        data["audio_bitrate"] = template.audio_bitrate
        data["organization_name"] = template.organization_name
        data["logo_path"] = template.logo_path
        data["intro_path"] = template.intro_path
        data["outro_path"] = template.outro_path
        if template.layout_config:
            try:
                layout = json.loads(template.layout_config)
                data.update(layout)
            except json.JSONDecodeError:
                pass
    return data


async def _update_step(job_id: str, step_key: str, extra_msg: str = "") -> None:
    """Update job step in DB and publish progress event."""
    progress, label = STEPS[step_key]
    message = f"{label}{'... ' + extra_msg if extra_msg else '...'}"

    async with AsyncSessionLocal() as session:
        job = await session.get(ProcessingJob, job_id)
        if job:
            job.current_step = step_key
            job.progress_percent = progress
            job.step_message = message
            await session.commit()

    await publish_progress(job_id, "running", step_key, progress, message)


async def _fail_job(job_id: str, error: str) -> None:
    """Mark job as failed in DB and publish error event."""
    async with AsyncSessionLocal() as session:
        job = await session.get(ProcessingJob, job_id)
        if job:
            job.status = "failed"
            job.error_message = error
            job.completed_at = datetime.utcnow()
            await session.commit()

    await publish_progress(job_id, "failed", "error", 0, f"Error: {error}")
