# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for building IslamicVideoStudio.exe (Windows standalone app).
Bundles FastAPI backend + built React frontend (frontend/dist) + optional ffmpeg/ directory.
"""
import os
from pathlib import Path

ROOT_DIR = Path(SPECPATH).resolve()
BACKEND_DIR = ROOT_DIR / "backend"
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"
FFMPEG_DIR = ROOT_DIR / "ffmpeg_bundle"

datas = []
if FRONTEND_DIST.exists():
    datas.append((str(FRONTEND_DIST), "frontend_dist"))

# Include ffmpeg.exe and ffprobe.exe if placed in ./ffmpeg_bundle
binaries = []
if FFMPEG_DIR.exists():
    for exe_name in ("ffmpeg.exe", "ffprobe.exe"):
        exe_path = FFMPEG_DIR / exe_name
        if exe_path.exists():
            binaries.append((str(exe_path), "ffmpeg"))

hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "aiosqlite",
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.dialects.sqlite.aiosqlite",
    "greenlet",
    "multipart",
    "sse_starlette",
    "email.mime.multipart",
    "email.mime.text",
]

a = Analysis(
    [str(BACKEND_DIR / "desktop_launcher.py")],
    pathex=[str(BACKEND_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib", "pytest", "torch", "torchvision", "torchaudio",
        "tensorflow", "scipy", "pandas", "IPython", "notebook", "jupyter",
        "cv2", "av", "sounddevice", "numba", "llvmlite",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="IslamicVideoStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
