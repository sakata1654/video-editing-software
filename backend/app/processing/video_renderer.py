"""
Video rendering engine using FFmpeg.
Converts landscape lecture footage to 1080x1920 (9:16) vertical format with:
  - Blurred background extension, center crop, or optional face-tracked crop
  - Burned-in subtitles (configurable font, size, color, background, position, toggle)
  - Lecture title and scholar name header overlays
  - Organization branding & logo overlay
  - Watermark
  - Optional intro/outro video concatenation

Reusable across both Lecture Clips and future Quran Reels modules.
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.processing.subtitle_engine import SubtitleStyle, generate_ass, save_subtitle_file

logger = logging.getLogger(__name__)


def _resolve_font_path(font_name: str) -> Optional[str]:
    """
    Resolve a font family name to an actual font file path on Windows/Linux/macOS.
    Returns None if not found (caller can fall back to font='<name>').
    """
    name_lower = (font_name or "Arial").lower().strip()
    candidates: list[str] = []

    if os.name == "nt":
        fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        win_map = {
            "arial": ["arial.ttf", "arialbd.ttf"],
            "georgia": ["georgia.ttf"],
            "verdana": ["verdana.ttf"],
            "times new roman": ["times.ttf"],
            "tahoma": ["tahoma.ttf"],
            "calibri": ["calibri.ttf"],
            "segoe ui": ["segoeui.ttf"],
            "amiri": ["Amiri-Regular.ttf"],
        }
        for fname in win_map.get(name_lower, ["arial.ttf"]):
            candidates.append(str(fonts_dir / fname))
    else:
        linux_dirs = [
            "/usr/share/fonts/truetype/dejavu",
            "/usr/share/fonts/truetype/liberation",
            "/usr/share/fonts/truetype/freefont",
            "/usr/share/fonts/opentype",
            "/System/Library/Fonts",
            "/Library/Fonts",
        ]
        for d in linux_dirs:
            for fname in ["DejaVuSans-Bold.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf", "Arial.ttf"]:
                candidates.append(os.path.join(d, fname))

    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def _detect_speaker_center_x(input_path: str, start_seconds: float, duration: float) -> Optional[float]:
    """
    Optional face tracking: sample a few frames and detect speaker horizontal center
    as a normalized fraction [0.0, 1.0]. Falls back to None (safe center crop) if
    OpenCV is unavailable or detection is uncertain.
    """
    try:
        import cv2  # type: ignore
    except ImportError:
        return None

    try:
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            return None

        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        face_cascade = cv2.CascadeClassifier(cascade_path)

        centers: list[float] = []
        sample_offsets = [0.2, 0.4, 0.6, 0.8]
        for frac in sample_offsets:
            ts_ms = (start_seconds + duration * frac) * 1000.0
            cap.set(cv2.CAP_PROP_POS_MSEC, ts_ms)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            h, w = frame.shape[:2]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
            if len(faces) > 0:
                # Pick largest detected face
                x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
                centers.append((x + fw / 2.0) / float(w))

        cap.release()
        if centers:
            # Median center clamped to safe range
            centers.sort()
            return max(0.2, min(0.8, centers[len(centers) // 2]))
    except Exception as exc:
        logger.debug("Face tracking skipped: %s", exc)
    return None


@dataclass
class RenderConfig:
    """Complete configuration for rendering one clip or vertical video."""
    # Source
    input_path: str
    start_seconds: float
    end_seconds: float

    # Output
    output_path: str
    output_width: int = 1080
    output_height: int = 1920
    output_fps: float = 30.0
    video_bitrate: str = "4M"
    audio_bitrate: str = "192k"

    # Layout
    background_color: str = "#000000"
    video_crop_mode: str = "blur_background"  # blur_background | center_crop | face_track
    background_blur_strength: int = 20
    video_position_y: float = 0.5  # 0.0=top, 0.5=center, 1.0=bottom within video area

    # Overlays
    lecture_title: Optional[str] = None
    scholar_name: Optional[str] = None
    organization_name: Optional[str] = None
    logo_path: Optional[str] = None
    watermark_text: Optional[str] = None
    watermark_opacity: float = 0.6

    # Subtitles
    subtitles_enabled: bool = True
    subtitle_segments: Optional[list[dict]] = None
    subtitle_style: Optional[SubtitleStyle] = None

    # Header/footer
    header_height: int = 180
    footer_height: int = 220
    header_enabled: bool = True
    footer_enabled: bool = True

    # Colors and fonts
    title_font: str = "Arial"
    title_font_size: int = 48
    title_color: str = "#FFFFFF"
    scholar_font: str = "Arial"
    scholar_font_size: int = 36
    scholar_color: str = "#D4AF37"
    margins: int = 32

    # Intro/outro
    intro_path: Optional[str] = None
    outro_path: Optional[str] = None


def render_clip(config: RenderConfig) -> str:
    """
    Render one clip using FFmpeg. Returns the output path.
    Uses temporary files safely and cleans them up automatically.
    """
    output_path = Path(config.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration = max(0.5, config.end_seconds - config.start_seconds)

    face_center_x: Optional[float] = None
    if config.video_crop_mode == "face_track":
        face_center_x = _detect_speaker_center_x(
            config.input_path, config.start_seconds, duration
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Generate ASS subtitle file if enabled and segments exist
        subtitle_path: Optional[Path] = None
        if config.subtitles_enabled and config.subtitle_segments:
            style = config.subtitle_style or SubtitleStyle()
            ass_content = generate_ass(
                segments=config.subtitle_segments,
                style=style,
                video_width=config.output_width,
                video_height=config.output_height,
                start_offset=config.start_seconds,
            )
            subtitle_path = tmpdir_path / "subtitles.ass"
            save_subtitle_file(ass_content, subtitle_path)

        has_logo = bool(config.logo_path and Path(config.logo_path).exists())
        filter_graph = _build_filter_graph(
            config, subtitle_path, has_logo=has_logo, face_center_x=face_center_x
        )

        # If intro/outro exist, render main segment to temp file then concat
        has_intro = bool(config.intro_path and Path(config.intro_path).exists())
        has_outro = bool(config.outro_path and Path(config.outro_path).exists())

        main_target = (
            tmpdir_path / "main_segment.mp4"
            if (has_intro or has_outro)
            else output_path
        )

        cmd = _build_ffmpeg_command(
            config, filter_graph, duration, str(main_target), has_logo=has_logo
        )

        logger.info(
            "Rendering clip: %s -> %s (%.1fs, mode=%s)",
            Path(config.input_path).name,
            output_path.name,
            duration,
            config.video_crop_mode,
        )

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            logger.error("FFmpeg stderr: %s", result.stderr[-1200:])
            raise RuntimeError(f"Video rendering failed: {result.stderr[-500:]}")

        if has_intro or has_outro:
            _concat_with_intro_outro(
                main_segment=main_target,
                output_path=output_path,
                intro_path=Path(config.intro_path) if has_intro else None,
                outro_path=Path(config.outro_path) if has_outro else None,
                config=config,
                tmpdir=tmpdir_path,
            )

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("Rendered output file is empty or missing")

    logger.info(
        "Clip rendered: %s (%.1f MB)",
        output_path.name,
        output_path.stat().st_size / 1024 / 1024,
    )
    return str(output_path)


def _concat_with_intro_outro(
    main_segment: Path,
    output_path: Path,
    intro_path: Optional[Path],
    outro_path: Optional[Path],
    config: RenderConfig,
    tmpdir: Path,
) -> None:
    """Normalize intro/outro resolution and concatenate with main clip."""
    parts: list[Path] = []
    W, H = config.output_width, config.output_height

    for idx, src in enumerate([intro_path, main_segment, outro_path]):
        if src is None:
            continue
        if src == main_segment:
            parts.append(src)
            continue
        norm_path = tmpdir / f"norm_{idx}.mp4"
        cmd = [
            "ffmpeg",
            "-i", str(src),
            "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1",
            "-r", str(config.output_fps),
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-ar", "44100", "-ac", "2",
            "-pix_fmt", "yuv420p",
            "-y", str(norm_path),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if res.returncode == 0 and norm_path.exists():
            parts.append(norm_path)

    if len(parts) == 1:
        main_segment.replace(output_path)
        return

    concat_list = tmpdir / "concat.txt"
    concat_list.write_text(
        "\n".join(f"file '{p.as_posix()}'" for p in parts),
        encoding="utf-8",
    )
    cmd = [
        "ffmpeg",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy",
        "-movflags", "+faststart",
        "-y", str(output_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if res.returncode != 0:
        raise RuntimeError(f"Concatenation failed: {res.stderr[-400:]}")


def _build_filter_graph(
    config: RenderConfig,
    subtitle_path: Optional[Path],
    has_logo: bool = False,
    face_center_x: Optional[float] = None,
) -> str:
    """Build FFmpeg filter graph for 9:16 vertical conversion and overlays."""
    W = config.output_width
    H = config.output_height

    header_h = config.header_height if config.header_enabled else 0
    footer_h = config.footer_height if config.footer_enabled else 0
    video_area_h = max(300, H - header_h - footer_h)

    filters: list[str] = []

    if config.video_crop_mode in ("center_crop", "face_track"):
        # Crop source to 9:16 without stretching; center on face_center_x if detected
        x_frac = face_center_x if face_center_x is not None else 0.5
        filters.append(
            f"[0:v]scale=-2:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H}:x='max(0,min(iw-{W},iw*{x_frac:.3f}-{W}/2))':y=(ih-{H})/2,"
            f"setsar=1[with_video]"
        )
    else:
        # Default safe mode: blurred background + sharp scaled foreground
        blur_sigma = max(1, config.background_blur_strength)
        filters.append(
            f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},"
            f"gblur=sigma={blur_sigma},"
            f"setsar=1[bg]"
        )
        filters.append(
            f"[0:v]scale={W}:-2:force_original_aspect_ratio=decrease,"
            f"setsar=1[fg_raw]"
        )
        pos_y = max(0.0, min(1.0, config.video_position_y))
        fg_y = f"{header_h}+(({video_area_h}-h)*{pos_y:.2f})"
        filters.append(f"[bg][fg_raw]overlay=x=(W-w)/2:y={fg_y}[with_video]")

    base_stream = "with_video"

    # Header overlay (lecture title + scholar name)
    if config.header_enabled and (config.lecture_title or config.scholar_name):
        filters.append(
            f"[{base_stream}]drawbox=x=0:y=0:w={W}:h={header_h}:color=black@0.72:t=fill[with_header_bg]"
        )
        base_stream = "with_header_bg"

        y_pos = config.margins
        if config.lecture_title:
            safe_title = _escape_drawtext(config.lecture_title[:65])
            font_arg = _format_font_arg(config.title_font)
            filters.append(
                f"[{base_stream}]drawtext="
                f"text='{safe_title}':"
                f"fontsize={config.title_font_size}:"
                f"fontcolor={config.title_color}:"
                f"x=(w-text_w)/2:y={y_pos}:"
                f"{font_arg}[with_title]"
            )
            base_stream = "with_title"
            y_pos += config.title_font_size + 14

        if config.scholar_name:
            safe_scholar = _escape_drawtext(config.scholar_name[:60])
            font_arg = _format_font_arg(config.scholar_font)
            filters.append(
                f"[{base_stream}]drawtext="
                f"text='{safe_scholar}':"
                f"fontsize={config.scholar_font_size}:"
                f"fontcolor={config.scholar_color}:"
                f"x=(w-text_w)/2:y={y_pos}:"
                f"{font_arg}[with_scholar]"
            )
            base_stream = "with_scholar"

    # Footer / organization branding bar
    if config.footer_enabled and config.organization_name:
        safe_org = _escape_drawtext(config.organization_name[:60])
        font_arg = _format_font_arg(config.scholar_font)
        filters.append(
            f"[{base_stream}]drawtext="
            f"text='{safe_org}':"
            f"fontsize=26:"
            f"fontcolor=white@0.85:"
            f"x=(w-text_w)/2:y={H - config.margins - 30}:"
            f"{font_arg}[with_org]"
        )
        base_stream = "with_org"

    # Logo overlay (top-right corner below header)
    if has_logo:
        filters.append("[1:v]scale=110:-1[logo_scaled]")
        logo_y = header_h + 16 if config.header_enabled else config.margins
        filters.append(
            f"[{base_stream}][logo_scaled]overlay=x=W-w-{config.margins}:y={logo_y}[with_logo]"
        )
        base_stream = "with_logo"

    # Burn-in ASS subtitles
    if subtitle_path and subtitle_path.exists():
        sub_path_str = str(subtitle_path).replace("\\", "/").replace(":", "\\:")
        filters.append(f"[{base_stream}]ass='{sub_path_str}'[with_subs]")
        base_stream = "with_subs"

    # Watermark text
    if config.watermark_text:
        safe_wm = _escape_drawtext(config.watermark_text)
        font_arg = _format_font_arg(config.title_font)
        filters.append(
            f"[{base_stream}]drawtext="
            f"text='{safe_wm}':"
            f"fontsize=26:"
            f"fontcolor=white@{config.watermark_opacity:.2f}:"
            f"x=w-text_w-{config.margins}:y=h-text_h-{config.margins}:"
            f"{font_arg}[with_wm]"
        )
        base_stream = "with_wm"

    filters.append(f"[{base_stream}]copy[vout]")
    return ";".join(filters)


def _format_font_arg(font_name: str) -> str:
    resolved = _resolve_font_path(font_name)
    if resolved:
        escaped = resolved.replace("\\", "/").replace(":", "\\:")
        return f"fontfile='{escaped}'"
    safe_name = (font_name or "Arial").replace("'", "")
    return f"font='{safe_name}'"


def _build_ffmpeg_command(
    config: RenderConfig,
    filter_graph: str,
    duration: float,
    target_path: str,
    has_logo: bool = False,
) -> list[str]:
    cmd = [
        "ffmpeg",
        "-ss", str(config.start_seconds),
        "-i", config.input_path,
    ]
    if has_logo and config.logo_path:
        cmd.extend(["-i", config.logo_path])

    cmd.extend([
        "-t", str(duration),
        "-filter_complex", filter_graph,
        "-map", "[vout]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-b:v", config.video_bitrate,
        "-c:a", "aac",
        "-b:a", config.audio_bitrate,
        "-ar", "44100",
        "-r", str(config.output_fps),
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-y",
        target_path,
    ])
    return cmd


def _escape_drawtext(text: str) -> str:
    """Escape special characters for FFmpeg drawtext filter."""
    text = text.replace("\\", "\\\\")
    text = text.replace("'", "\\'")
    text = text.replace(":", "\\:")
    text = text.replace("[", "\\[")
    text = text.replace("]", "\\]")
    text = text.replace("%", "\\%")
    return text
