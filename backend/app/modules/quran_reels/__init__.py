"""
Future Module: Quran Reels (Architectural Design Stub — Not Implemented Yet).

Planned capabilities:
  - Accept Quran recitation audio/video
  - Accept Arabic ayat and user-provided translations (never auto-translated or altered)
  - Support any Unicode translation language
  - Detect individual ayah timings
  - Synchronize Arabic text and translations with recitation
  - Apply saved Quran video themes
  - Reuse app.processing.video_renderer.RenderConfig / render_clip and Template engine
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class AyahSegment:
    """Represents one Quranic ayah with exact recitation timestamps and user-provided translation."""
    surah_number: int
    ayah_number: int
    start_seconds: float
    end_seconds: float
    arabic_text: str
    translation_text: Optional[str] = None  # Exact user-provided Unicode text; never altered
    translation_language: Optional[str] = None


class QuranReelsPipeline:
    """Extension point for the future Quran Reels module."""

    async def generate_reel(self, *args, **kwargs) -> None:
        raise NotImplementedError("Quran Reels module is planned for a future release.")
