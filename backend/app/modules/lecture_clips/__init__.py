"""
Lecture Clips module.
Wraps the reusable processing and rendering engines for Islamic lecture clipping.
"""
from app.processing.analyzer import ClipCandidate, analyze_transcript
from app.processing.pipeline import render_approved_clips, run_pipeline
from app.processing.video_renderer import RenderConfig, render_clip

__all__ = [
    "ClipCandidate",
    "analyze_transcript",
    "render_approved_clips",
    "run_pipeline",
    "RenderConfig",
    "render_clip",
]
