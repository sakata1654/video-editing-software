"""Tests for AI transcript analyzer (duration filtering & segment snapping)."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.processing.analyzer import _snap_to_segments, analyze_transcript
from app.processing.transcriber import TranscriptSegment, TranscriptionResult


def _sample_transcript() -> TranscriptionResult:
    segments = [
        TranscriptSegment(start=0.0, end=10.0, text="Assalamu alaikum everyone.", words=[]),
        TranscriptSegment(start=10.0, end=30.0, text="Today we reflect on gratitude in times of ease and hardship.", words=[]),
        TranscriptSegment(start=30.0, end=58.0, text="Allah reminds us that if you are grateful, He will surely increase you.", words=[]),
        TranscriptSegment(start=58.0, end=68.0, text="Short remark.", words=[]),
    ]
    return TranscriptionResult(
        language="en",
        segments=segments,
        full_text=" ".join(s.text for s in segments),
    )


def test_snap_to_segments():
    tr = _sample_transcript()
    start, end = _snap_to_segments(tr, 10.4, 57.6)
    assert start == 10.0
    assert end == 58.0


@pytest.mark.asyncio
async def test_analyze_transcript_filters_and_ranks(monkeypatch):
    tr = _sample_transcript()
    mock_payload = {
        "clips": [
            {
                "start_seconds": 10.2,
                "end_seconds": 57.8,
                "suggested_title": "The Promise of Gratitude",
                "transcript_text": "Today we reflect on gratitude in times of ease and hardship. Allah reminds us that if you are grateful, He will surely increase you.",
                "relevance_score": 0.94,
                "reasoning": "Complete explanation with Quranic reminder.",
            },
            {
                "start_seconds": 58.0,
                "end_seconds": 68.0,
                "suggested_title": "Too short clip",
                "transcript_text": "Short remark.",
                "relevance_score": 0.99,
                "reasoning": "Too short (10s).",
            },
        ]
    }

    fake_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(mock_payload)))]
    )
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(return_value=fake_response)

    with patch("app.processing.analyzer.settings") as mock_settings:
        mock_settings.clip_min_seconds = 30
        mock_settings.clip_max_seconds = 120
        mock_settings.clip_preferred_min_seconds = 45
        mock_settings.clip_preferred_max_seconds = 90
        mock_settings.effective_llm_api_key = "test-key"
        mock_settings.llm_provider = "openai"
        mock_settings.llm_base_url = "https://api.openai.com/v1"
        mock_settings.llm_model = "gpt-4o"

        with patch("openai.AsyncOpenAI", return_value=fake_client):
            candidates = await analyze_transcript(
                tr, lecture_title="Gratitude", scholar_name="Scholar"
            )

    assert len(candidates) == 1
    assert candidates[0].suggested_title == "The Promise of Gratitude"
    assert candidates[0].start_seconds == 10.0
    assert candidates[0].end_seconds == 58.0
    assert candidates[0].rank == 0
