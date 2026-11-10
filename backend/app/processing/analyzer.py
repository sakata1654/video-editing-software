"""
LLM-powered clip selection engine.
Analyzes the full lecture transcript and identifies the most valuable
segments to extract as short video clips.

Design principles:
- Provider-agnostic (OpenAI API or any compatible endpoint)
- Never fabricates or rewrites the scholar's words
- Prioritizes complete thoughts and proper context
- Respects configured duration constraints
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

from app.config import get_settings
from app.processing.transcriber import TranscriptionResult

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class ClipCandidate:
    start_seconds: float
    end_seconds: float
    suggested_title: str
    transcript_text: str
    relevance_score: float  # 0.0 – 1.0
    reasoning: str
    rank: int


SYSTEM_PROMPT = """You are an expert Islamic content curator. Your task is to analyze 
transcripts of Islamic lectures and identify the most beneficial short video segments 
suitable for social media clips (Reels, Shorts, TikTok).

SELECTION CRITERIA (prioritize in this order):
1. Complete, self-contained explanations of Islamic concepts
2. Powerful reminders (tawbah, death, Day of Judgment, gratitude, etc.)
3. Practical advice rooted in Quran or Sunnah
4. Question-and-answer exchanges with clear answers
5. Interesting stories or parables with a moral lesson
6. Memorable quotes or wisdom statements

STRICT RULES:
- NEVER cut a sentence halfway — always start and end at complete sentences
- NEVER select a segment that lacks context (e.g., mid-explanation without setup)
- NEVER select content that could be misunderstood out of context
- NEVER alter, paraphrase, or summarize — select exact transcript segments only
- Each clip must stand alone and be fully understandable without watching more
- Prefer segments where the scholar is explaining a point clearly, not just listing

OUTPUT FORMAT:
Return a JSON object with a "clips" array. Each clip must have:
{
  "start_seconds": <number>,
  "end_seconds": <number>,
  "suggested_title": "<engaging title for social media, max 80 chars>",
  "transcript_text": "<exact text from transcript>",
  "relevance_score": <0.0 to 1.0>,
  "reasoning": "<why this clip is beneficial and stands alone>"
}

Return 5-10 clips sorted by relevance_score descending.
"""


async def analyze_transcript(
    result: TranscriptionResult,
    lecture_title: str,
    scholar_name: Optional[str] = None,
    min_seconds: Optional[int] = None,
    max_seconds: Optional[int] = None,
) -> list[ClipCandidate]:
    """
    Send the transcript to the LLM and parse clip candidates.
    Returns candidates sorted by relevance score.
    """
    min_s = min_seconds or settings.clip_min_seconds
    max_s = max_seconds or settings.clip_max_seconds
    pref_min = settings.clip_preferred_min_seconds
    pref_max = settings.clip_preferred_max_seconds

    if not settings.effective_llm_api_key:
        raise ValueError(
            "LLM API key not configured. Set LLM_API_KEY or OPENAI_API_KEY in .env"
        )

    # Build transcript representation with timestamps
    transcript_lines = []
    for seg in result.segments:
        mm_start = int(seg.start // 60)
        ss_start = int(seg.start % 60)
        transcript_lines.append(f"[{mm_start:02d}:{ss_start:02d} | {seg.start:.1f}s] {seg.text}")

    transcript_text = "\n".join(transcript_lines)

    scholar_info = f"Scholar: {scholar_name}" if scholar_name else ""
    duration_info = (
        f"Target clip duration: {min_s}–{max_s} seconds "
        f"(preferred: {pref_min}–{pref_max} seconds)"
    )

    user_message = f"""Lecture Title: {lecture_title}
{scholar_info}
{duration_info}

TRANSCRIPT (format: [MM:SS | seconds] text):
{transcript_text}

Analyze this transcript and select the most beneficial segments as described.
Each segment's start_seconds and end_seconds must correspond EXACTLY to segment 
boundaries in the transcript — do not interpolate timestamps.
"""

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=settings.effective_llm_api_key,
            base_url=settings.llm_base_url if settings.llm_provider == "compatible" else None,
        )

        logger.info("Analyzing transcript with %s model: %s", settings.llm_provider, settings.llm_model)

        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,  # Low temperature for consistent, factual output
            max_tokens=4096,
        )

        content = response.choices[0].message.content
        data = json.loads(content)
        raw_clips = data.get("clips", [])

    except Exception as e:
        logger.error("LLM analysis failed: %s", e)
        raise RuntimeError(f"AI analysis failed: {e}")

    # Parse and validate clips
    candidates = []
    for i, clip in enumerate(raw_clips):
        try:
            start = float(clip["start_seconds"])
            end = float(clip["end_seconds"])
            duration = end - start

            # Validate duration constraints
            if duration < min_s:
                logger.debug("Skipping clip (too short: %.1fs): %s", duration, clip.get("suggested_title"))
                continue
            if duration > max_s:
                logger.debug("Skipping clip (too long: %.1fs): %s", duration, clip.get("suggested_title"))
                continue

            # Snap timestamps to actual segment boundaries
            start, end = _snap_to_segments(result, start, end)

            candidates.append(ClipCandidate(
                start_seconds=start,
                end_seconds=end,
                suggested_title=clip.get("suggested_title", f"Clip {i + 1}"),
                transcript_text=clip.get("transcript_text", ""),
                relevance_score=float(clip.get("relevance_score", 0.5)),
                reasoning=clip.get("reasoning", ""),
                rank=i,
            ))

        except (KeyError, ValueError, TypeError) as e:
            logger.warning("Skipping malformed clip candidate: %s", e)
            continue

    # Sort by relevance score
    candidates.sort(key=lambda c: c.relevance_score, reverse=True)
    for i, c in enumerate(candidates):
        c.rank = i

    logger.info("Found %d valid clip candidates", len(candidates))
    return candidates


def _snap_to_segments(result: TranscriptionResult, start: float, end: float) -> tuple[float, float]:
    """
    Snap start/end to the nearest actual transcript segment boundaries
    to avoid cutting mid-sentence.
    """
    if not result.segments:
        return start, end

    # Find the closest segment start
    best_start = min(result.segments, key=lambda s: abs(s.start - start))
    # Find the closest segment end
    best_end = min(result.segments, key=lambda s: abs(s.end - end))

    snapped_start = best_start.start
    snapped_end = best_end.end

    # Ensure start < end
    if snapped_start >= snapped_end:
        snapped_start = start
        snapped_end = end

    return snapped_start, snapped_end
