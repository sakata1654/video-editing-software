"""
FastAPI application entry point.
Configures CORS, mounts routers, handles lifespan (startup/shutdown).
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import clips, jobs, projects, settings as settings_api, templates
from app.config import get_settings
from app.core import task_queue
from app.database import create_tables

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    logger.info("Starting Islamic Video Studio API...")

    # Create database tables
    await create_tables()
    logger.info("Database tables ready")

    # Ensure storage directories exist
    settings.uploads_dir
    settings.outputs_dir
    settings.temp_dir
    logger.info("Storage directories ready: %s", settings.storage_root)

    # Start the background task queue
    await task_queue.startup()

    # Seed default template if none exists
    await _seed_default_template()

    logger.info("API ready")
    yield

    # Shutdown
    await task_queue.shutdown()
    logger.info("API stopped")


async def _seed_default_template() -> None:
    """Create a default template on first run."""
    from sqlalchemy import select

    from app.database import AsyncSessionLocal
    from app.models import Template
    from app.schemas import LayoutConfig

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Template).limit(1))
        if result.scalar_one_or_none() is not None:
            return  # Templates already exist

        default_layout = LayoutConfig()
        template = Template(
            name="Default Islamic Theme",
            description="Clean professional layout with golden scholar name",
            is_default=True,
            output_width=1080,
            output_height=1920,
            output_fps=30.0,
            video_bitrate="4M",
            audio_bitrate="192k",
            layout_config=default_layout.model_dump_json(),
            organization_name="Islamic Video Studio",
        )
        session.add(template)
        await session.commit()
        logger.info("Default template created")


app = FastAPI(
    title="Islamic Video Studio API",
    description="AI-powered Islamic lecture clip generator",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API routers
app.include_router(projects.router)
app.include_router(jobs.router)
app.include_router(clips.router)
app.include_router(templates.router)
app.include_router(settings_api.router)

# Serve uploaded/rendered files
storage_root = settings.storage_root
if storage_root.exists():
    app.mount("/files", StaticFiles(directory=str(storage_root)), name="files")


@app.get("/health")
async def health_check():
    return {"status": "ok", "version": "1.0.0"}


# Serve built frontend SPA when available (standalone .exe or single-server mode)
_frontend_dist = settings.frontend_dist_dir
if _frontend_dist is not None:
    _assets_dir = _frontend_dist / "assets"
    if _assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="frontend-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        if full_path.startswith(("api/", "files/")):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = (_frontend_dist / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(_frontend_dist.resolve()):
            return FileResponse(candidate)
        return FileResponse(_frontend_dist / "index.html")
