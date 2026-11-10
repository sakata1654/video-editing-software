"""
Application configuration loaded from environment variables.
Never hardcode secrets — use a .env file or real environment variables.
Supports both standard Python execution and frozen PyInstaller (.exe) execution.
"""
from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def get_runtime_dir() -> Path:
    """Directory for user data (.env, sqlite DB, storage) — next to .exe when frozen."""
    if is_frozen():
        exe_dir = Path(sys.executable).resolve().parent
        try:
            test_file = exe_dir / ".write_test"
            test_file.touch()
            test_file.unlink()
            return exe_dir
        except OSError:
            data_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "IslamicVideoStudio"
            data_dir.mkdir(parents=True, exist_ok=True)
            return data_dir
    return Path(__file__).resolve().parent.parent


def get_bundle_dir() -> Path:
    """Directory containing bundled read-only assets (PyInstaller _MEIPASS or repo root)."""
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent.parent.parent


def _setup_bundled_ffmpeg() -> None:
    """If ffmpeg/ffprobe binaries are bundled next to the exe or in _MEIPASS, prepend to PATH."""
    candidates = [
        get_runtime_dir() / "ffmpeg",
        get_runtime_dir() / "ffmpeg" / "bin",
        get_bundle_dir() / "ffmpeg",
        get_bundle_dir() / "ffmpeg" / "bin",
    ]
    existing_path = os.environ.get("PATH", "")
    extra = [str(p) for p in candidates if p.exists() and str(p) not in existing_path]
    if extra:
        os.environ["PATH"] = os.pathsep.join(extra) + os.pathsep + existing_path


_setup_bundled_ffmpeg()

_RUNTIME_DIR = get_runtime_dir()
_DEFAULT_ENV_FILE = str(_RUNTIME_DIR / ".env")
_DEFAULT_DB_URL = (
    f"sqlite+aiosqlite:///{(_RUNTIME_DIR / 'studio_data' / 'islamic_studio.db').as_posix()}"
    if is_frozen()
    else "sqlite+aiosqlite:///./islamic_studio.db"
)
_DEFAULT_STORAGE_ROOT = (
    str(_RUNTIME_DIR / "studio_data" / "storage")
    if is_frozen()
    else "../storage"
)

if is_frozen():
    (_RUNTIME_DIR / "studio_data").mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Server
    app_env: Literal["development", "production"] = "development"
    secret_key: str = "dev-secret-change-in-production"
    allowed_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]

    # Database
    database_url: str = _DEFAULT_DB_URL

    # Storage
    storage_backend: Literal["local", "s3"] = "local"
    storage_local_root: str = _DEFAULT_STORAGE_ROOT
    s3_bucket: str = ""
    s3_region: str = "us-east-1"
    s3_endpoint_url: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    # Task Queue (local asyncio or celery+redis)
    task_queue_backend: Literal["local", "celery"] = "local"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # Transcription
    transcription_provider: Literal["openai", "faster-whisper"] = "openai"
    openai_api_key: str = ""
    whisper_model: str = "whisper-1"
    faster_whisper_model: str = "large-v3"

    # LLM
    llm_provider: Literal["openai", "compatible"] = "openai"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o"

    # Processing
    max_concurrent_jobs: int = 2
    max_upload_size_mb: int = 2048
    clip_min_seconds: int = 30
    clip_max_seconds: int = 120
    clip_preferred_min_seconds: int = 45
    clip_preferred_max_seconds: int = 90

    @property
    def env_file_path(self) -> Path:
        return Path(_DEFAULT_ENV_FILE)

    @property
    def frontend_dist_dir(self) -> Optional[Path]:
        """Locate built frontend static files when running standalone / .exe."""
        candidates = [
            get_bundle_dir() / "frontend_dist",
            get_runtime_dir() / "frontend_dist",
            get_bundle_dir() / "frontend" / "dist",
        ]
        for p in candidates:
            if (p / "index.html").exists():
                return p
        return None

    @property
    def storage_root(self) -> Path:
        p = Path(self.storage_local_root).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def uploads_dir(self) -> Path:
        p = self.storage_root / "uploads"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def outputs_dir(self) -> Path:
        p = self.storage_root / "outputs"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def temp_dir(self) -> Path:
        p = self.storage_root / "temp"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def effective_llm_api_key(self) -> str:
        """Return LLM API key, falling back to OpenAI key."""
        return self.llm_api_key or self.openai_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
