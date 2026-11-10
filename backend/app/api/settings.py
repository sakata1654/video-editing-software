"""
Settings & System Diagnostics API.
Exposes non-secret configuration state and FFmpeg availability.
Allows saving AI provider configuration to the local .env file without ever returning raw secrets.
"""
from __future__ import annotations

import shutil
import subprocess
from typing import Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])
settings = get_settings()


class SystemStatusResponse(BaseModel):
    app_env: str
    ffmpeg_available: bool
    ffprobe_available: bool
    ffmpeg_version: str | None
    storage_backend: str
    task_queue_backend: str
    transcription_provider: str
    whisper_model: str
    faster_whisper_model: str
    openai_key_configured: bool
    llm_provider: str
    llm_model: str
    llm_base_url: str
    llm_key_configured: bool
    max_concurrent_jobs: int
    max_upload_size_mb: int
    clip_min_seconds: int
    clip_preferred_min_seconds: int
    clip_preferred_max_seconds: int
    clip_max_seconds: int


class UpdateAISettingsRequest(BaseModel):
    transcription_provider: Optional[Literal["openai", "faster-whisper"]] = None
    openai_api_key: Optional[str] = None
    faster_whisper_model: Optional[str] = None
    llm_provider: Optional[Literal["openai", "compatible"]] = None
    llm_base_url: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_model: Optional[str] = None


def _build_status() -> SystemStatusResponse:
    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")
    ffmpeg_version = None

    if ffmpeg_path:
        try:
            res = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5)
            if res.returncode == 0 and res.stdout:
                ffmpeg_version = res.stdout.splitlines()[0]
        except Exception:
            pass

    return SystemStatusResponse(
        app_env=settings.app_env,
        ffmpeg_available=bool(ffmpeg_path),
        ffprobe_available=bool(ffprobe_path),
        ffmpeg_version=ffmpeg_version,
        storage_backend=settings.storage_backend,
        task_queue_backend=settings.task_queue_backend,
        transcription_provider=settings.transcription_provider,
        whisper_model=settings.whisper_model,
        faster_whisper_model=settings.faster_whisper_model,
        openai_key_configured=bool(settings.openai_api_key and not settings.openai_api_key.startswith("sk-...")),
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        llm_base_url=settings.llm_base_url,
        llm_key_configured=bool(settings.effective_llm_api_key and not settings.effective_llm_api_key.startswith("sk-...")),
        max_concurrent_jobs=settings.max_concurrent_jobs,
        max_upload_size_mb=settings.max_upload_size_mb,
        clip_min_seconds=settings.clip_min_seconds,
        clip_preferred_min_seconds=settings.clip_preferred_min_seconds,
        clip_preferred_max_seconds=settings.clip_preferred_max_seconds,
        clip_max_seconds=settings.clip_max_seconds,
    )


def _persist_env_updates(updates: dict[str, str]) -> None:
    """Update or append key=value entries in the local .env file."""
    env_path = settings.env_file_path
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    remaining = dict(updates)
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            new_lines.append(line)
            continue
        key = stripped.split("=", 1)[0].strip().upper()
        if key in remaining:
            new_lines.append(f"{key}={remaining.pop(key)}")
        else:
            new_lines.append(line)

    for key, val in remaining.items():
        new_lines.append(f"{key}={val}")

    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


@router.get("", response_model=SystemStatusResponse)
async def get_system_settings():
    return _build_status()


@router.post("/ai", response_model=SystemStatusResponse)
async def update_ai_settings(req: UpdateAISettingsRequest):
    """Update AI provider configuration in memory and persist to local .env."""
    env_updates: dict[str, str] = {}

    if req.transcription_provider is not None:
        settings.transcription_provider = req.transcription_provider
        env_updates["TRANSCRIPTION_PROVIDER"] = req.transcription_provider
    if req.openai_api_key is not None and req.openai_api_key.strip():
        val = req.openai_api_key.strip()
        settings.openai_api_key = val
        env_updates["OPENAI_API_KEY"] = val
    if req.faster_whisper_model is not None and req.faster_whisper_model.strip():
        val = req.faster_whisper_model.strip()
        settings.faster_whisper_model = val
        env_updates["FASTER_WHISPER_MODEL"] = val
    if req.llm_provider is not None:
        settings.llm_provider = req.llm_provider
        env_updates["LLM_PROVIDER"] = req.llm_provider
    if req.llm_base_url is not None and req.llm_base_url.strip():
        val = req.llm_base_url.strip()
        settings.llm_base_url = val
        env_updates["LLM_BASE_URL"] = val
    if req.llm_api_key is not None and req.llm_api_key.strip():
        val = req.llm_api_key.strip()
        settings.llm_api_key = val
        env_updates["LLM_API_KEY"] = val
    if req.llm_model is not None and req.llm_model.strip():
        val = req.llm_model.strip()
        settings.llm_model = val
        env_updates["LLM_MODEL"] = val

    if env_updates:
        _persist_env_updates(env_updates)

    return _build_status()
