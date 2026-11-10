"""Tests for SRT and ASS subtitle generation."""
from __future__ import annotations

from app.processing.subtitle_engine import (
    SubtitleStyle,
    generate_ass,
    generate_srt,
    seconds_to_ass_time,
    seconds_to_srt_time,
    wrap_text,
)


def test_time_formatting():
    assert seconds_to_srt_time(0.0) == "00:00:00,000"
    assert seconds_to_srt_time(65.5) == "00:01:05,500"
    assert seconds_to_srt_time(3661.25) == "01:01:01,250"

    assert seconds_to_ass_time(0.0) == "0:00:00.00"
    assert seconds_to_ass_time(65.5) == "0:01:05.50"


def test_wrap_text():
    text = "Indeed Allah is with those who are patient and grateful in every trial."
    wrapped = wrap_text(text, max_chars=35)
    assert "\\N" in wrapped
    lines = wrapped.split("\\N")
    assert len(lines) <= 2


def test_generate_srt_with_offset():
    segments = [
        {"start": 30.0, "end": 34.5, "text": "First sentence here."},
        {"start": 34.5, "end": 39.0, "text": "Second sentence here."},
    ]
    srt = generate_srt(segments, start_offset=30.0)
    assert "00:00:00,000 --> 00:00:04,500" in srt
    assert "00:00:04,500 --> 00:00:09,000" in srt
    assert "First sentence here." in srt


def test_generate_ass_styling():
    segments = [{"start": 10.0, "end": 15.0, "text": "Alhamdulillah rabbil alamin"}]
    style = SubtitleStyle(
        font_family="Arial",
        font_size=52,
        font_color="#FFFFFF",
        background_color="#000000CC",
        position="bottom",
    )
    ass = generate_ass(segments, style=style, start_offset=10.0)
    assert "[Script Info]" in ass
    assert "PlayResX: 1080" in ass
    assert "PlayResY: 1920" in ass
    assert "Dialogue: 0,0:00:00.00,0:00:05.00" in ass
    assert "Alhamdulillah rabbil alamin" in ass
