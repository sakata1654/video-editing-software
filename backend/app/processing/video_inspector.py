"""
FFprobe wrapper — inspect video metadata without loading the file into RAM.
"""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class VideoMetadata:
    duration_seconds: float
    width: int
    height: int
    fps: float
    video_codec: str
    audio_codec: str
    has_audio: bool
    file_size_bytes: int
    bit_rate: int


def inspect_video(file_path: str | Path) -> VideoMetadata:
    """
    Use ffprobe to extract video metadata.
    Raises RuntimeError if ffprobe fails or the file is invalid.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Video file not found: {path}")

    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        str(path),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("ffprobe timed out inspecting video")
    except FileNotFoundError:
        raise RuntimeError(
            "ffprobe not found. Ensure FFmpeg is installed and on PATH."
        )

    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"ffprobe returned invalid JSON: {e}")

    streams = data.get("streams", [])
    fmt = data.get("format", {})

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if not video_stream:
        raise ValueError("No video stream found in file")

    # Parse FPS (can be "30/1" or "30000/1001" etc.)
    fps_raw = video_stream.get("r_frame_rate", "30/1")
    try:
        num, den = fps_raw.split("/")
        fps = float(num) / float(den) if float(den) != 0 else 30.0
    except (ValueError, ZeroDivisionError):
        fps = 30.0

    # Duration — prefer format-level, fall back to stream
    duration = float(fmt.get("duration") or video_stream.get("duration") or 0)

    return VideoMetadata(
        duration_seconds=duration,
        width=int(video_stream.get("width", 0)),
        height=int(video_stream.get("height", 0)),
        fps=round(fps, 3),
        video_codec=video_stream.get("codec_name", "unknown"),
        audio_codec=audio_stream.get("codec_name", "unknown") if audio_stream else "none",
        has_audio=audio_stream is not None,
        file_size_bytes=int(fmt.get("size", 0)),
        bit_rate=int(fmt.get("bit_rate", 0)),
    )
