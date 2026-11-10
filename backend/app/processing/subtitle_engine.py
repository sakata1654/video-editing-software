"""
Subtitle generation engine.
Converts transcript segments into SRT and ASS subtitle formats.
Supports word-level highlighting and custom styling.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SubtitleStyle:
    font_family: str = "Arial"
    font_size: int = 48
    font_color: str = "&H00FFFFFF"   # ASS format: BBGGRR with alpha prefix
    background_color: str = "&H99000000"
    bold: bool = True
    italic: bool = False
    position: str = "bottom"         # top | middle | bottom
    max_chars_per_line: int = 40
    max_lines: int = 2


def seconds_to_srt_time(seconds: float) -> str:
    """Convert seconds to SRT timestamp: HH:MM:SS,mmm"""
    ms = int((seconds % 1) * 1000)
    s = int(seconds)
    m = s // 60
    h = m // 60
    s %= 60
    m %= 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def seconds_to_ass_time(seconds: float) -> str:
    """Convert seconds to ASS timestamp: H:MM:SS.cc"""
    cs = int((seconds % 1) * 100)
    s = int(seconds)
    m = s // 60
    h = m // 60
    s %= 60
    m %= 60
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def wrap_text(text: str, max_chars: int) -> str:
    """Wrap text at word boundaries to fit max_chars per line."""
    words = text.split()
    lines = []
    current = []
    current_len = 0

    for word in words:
        if current_len + len(word) + len(current) > max_chars and current:
            lines.append(" ".join(current))
            current = [word]
            current_len = len(word)
        else:
            current.append(word)
            current_len += len(word)

    if current:
        lines.append(" ".join(current))

    return "\\N".join(lines[:2])  # Max 2 lines in ASS format


def generate_srt(
    segments: list[dict],
    start_offset: float = 0.0,
) -> str:
    """
    Generate SRT subtitle content from transcript segments.
    segments: list of {start, end, text}
    start_offset: subtract this from all timestamps (for clip extraction)
    """
    lines = []
    for i, seg in enumerate(segments, 1):
        start = max(0.0, seg["start"] - start_offset)
        end = max(0.0, seg["end"] - start_offset)
        text = seg["text"].strip()
        if not text:
            continue
        lines.append(str(i))
        lines.append(f"{seconds_to_srt_time(start)} --> {seconds_to_srt_time(end)}")
        lines.append(text)
        lines.append("")

    return "\n".join(lines)


def generate_ass(
    segments: list[dict],
    style: SubtitleStyle,
    video_width: int = 1080,
    video_height: int = 1920,
    start_offset: float = 0.0,
) -> str:
    """
    Generate Advanced SubStation Alpha (.ass) subtitle file.
    Provides much better styling control than SRT.
    """
    # Determine vertical alignment
    alignment_map = {"top": 8, "middle": 5, "bottom": 2}
    alignment = alignment_map.get(style.position, 2)

    margin_v = 60 if style.position == "bottom" else 40

    # ASS color format: &HAABBGGRR (AA=alpha, BB=blue, GG=green, RR=red)
    primary_color = _hex_to_ass_color(style.font_color)
    back_color = _hex_to_ass_color_with_alpha(style.background_color)

    header = f"""[Script Info]
Title: Islamic Video Studio Subtitles
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{style.font_family},{style.font_size},{primary_color},&H000000FF,&H00000000,{back_color},{1 if style.bold else 0},{1 if style.italic else 0},0,0,100,100,0,0,4,0,0,{alignment},40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []
    for seg in segments:
        start = max(0.0, seg["start"] - start_offset)
        end = max(0.0, seg["end"] - start_offset)
        text = seg["text"].strip()
        if not text:
            continue
        wrapped = wrap_text(text, style.max_chars_per_line)
        events.append(
            f"Dialogue: 0,{seconds_to_ass_time(start)},{seconds_to_ass_time(end)},"
            f"Default,,0,0,0,,{wrapped}"
        )

    return header + "\n".join(events) + "\n"


def _hex_to_ass_color(hex_color: str) -> str:
    """Convert #RRGGBB to ASS &H00BBGGRR format."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 6:
        r, g, b = hex_color[0:2], hex_color[2:4], hex_color[4:6]
        return f"&H00{b}{g}{r}"
    return "&H00FFFFFF"


def _hex_to_ass_color_with_alpha(color: str) -> str:
    """Convert #RRGGBBAA or #RRGGBB to ASS &HAABBGGRR format."""
    color = color.lstrip("#")
    if len(color) == 8:
        r, g, b, a = color[0:2], color[2:4], color[4:6], color[6:8]
        # Invert alpha: ASS uses 00=opaque, FF=transparent
        alpha = format(255 - int(a, 16), "02X")
        return f"&H{alpha}{b}{g}{r}"
    elif len(color) == 6:
        r, g, b = color[0:2], color[2:4], color[4:6]
        return f"&H80{b}{g}{r}"
    return "&H80000000"


def save_subtitle_file(content: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    logger.info("Subtitle saved: %s", path.name)
