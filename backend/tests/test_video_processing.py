"""Tests for FFprobe inspection, FFmpeg audio extraction, and 9:16 vertical rendering."""
from __future__ import annotations

import subprocess
from pathlib import Path

from app.processing.audio_extractor import extract_audio
from app.processing.subtitle_engine import SubtitleStyle
from app.processing.video_inspector import inspect_video
from app.processing.video_renderer import RenderConfig, render_clip


def _create_synthetic_lecture(dest: Path, duration: int = 4) -> None:
    """Create a real 1280x720 landscape MP4 with test tone audio using FFmpeg."""
    cmd = [
        "ffmpeg",
        "-f", "lavfi", "-i", f"testsrc=duration={duration}:size=1280x720:rate=30",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-y", str(dest),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, f"FFmpeg failed creating synthetic video: {res.stderr}"


def test_inspect_extract_and_render(tmp_path: Path):
    src_video = tmp_path / "lecture.mp4"
    _create_synthetic_lecture(src_video, duration=4)

    # 1. Inspect with FFprobe
    meta = inspect_video(src_video)
    assert meta.width == 1280
    assert meta.height == 720
    assert meta.has_audio is True
    assert meta.duration_seconds >= 3.5

    # 2. Extract 16kHz mono WAV audio
    audio_out = tmp_path / "audio.wav"
    extract_audio(src_video, audio_out)
    assert audio_out.exists()
    assert audio_out.stat().st_size > 1000

    # 3. Render 1080x1920 vertical clip with blurred background, header, watermark, and subtitles
    clip_out = tmp_path / "vertical_clip.mp4"
    config = RenderConfig(
        input_path=str(src_video),
        start_seconds=0.5,
        end_seconds=3.0,
        output_path=str(clip_out),
        lecture_title="The Importance of Gratitude",
        scholar_name="Test Scholar",
        organization_name="Islamic Video Studio",
        watermark_text="@studio",
        subtitles_enabled=True,
        subtitle_segments=[
            {"start": 0.5, "end": 2.5, "text": "Gratitude increases blessings."},
        ],
        subtitle_style=SubtitleStyle(),
    )
    rendered = render_clip(config)
    assert Path(rendered).exists()

    # 4. Verify rendered output dimensions and codecs with FFprobe
    out_meta = inspect_video(clip_out)
    assert out_meta.width == 1080
    assert out_meta.height == 1920
    assert out_meta.video_codec == "h264"
    assert out_meta.audio_codec == "aac"
    assert 2.0 <= out_meta.duration_seconds <= 3.0
