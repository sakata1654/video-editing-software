"""
Audio extraction using FFmpeg.
Extracts audio from video without re-encoding when possible.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_audio(
    video_path: str | Path,
    output_path: str | Path,
    sample_rate: int = 16000,
    channels: int = 1,
) -> Path:
    """
    Extract audio from video as 16kHz mono WAV (optimal for Whisper).
    Returns the output path.
    """
    video_path = Path(video_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-i", str(video_path),
        "-vn",                          # No video
        "-acodec", "pcm_s16le",         # PCM 16-bit little-endian (WAV)
        "-ar", str(sample_rate),        # Sample rate
        "-ac", str(channels),           # Channels (1 = mono)
        "-y",                           # Overwrite
        str(output_path),
    ]

    logger.info("Extracting audio: %s -> %s", video_path.name, output_path.name)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=600,  # 10 minutes max
    )

    if result.returncode != 0:
        raise RuntimeError(f"Audio extraction failed: {result.stderr[-500:]}")

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("Audio extraction produced empty file")

    logger.info("Audio extracted: %.1f MB", output_path.stat().st_size / 1024 / 1024)
    return output_path
