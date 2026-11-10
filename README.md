# Islamic Video Studio

AI-powered web application that converts long Islamic lectures into professionally edited, ready-to-upload 9:16 vertical short videos (Reels, Shorts, TikTok).

## Features

- **Simple Workflow**: Upload lecture video, enter lecture title (and optional scholar name), click **Generate Clips**.
- **Video Processing (FFmpeg / FFprobe)**:
  - Supports MP4, MOV, MKV, AVI, WebM, FLV, WMV, M4V.
  - Streaming large-file upload with progress bar and validation.
  - Automatic 1080×1920 (9:16) H.264/AAC vertical conversion with blurred background extension, center crop, or optional face-tracking crop.
  - Automatic header (lecture title + scholar name), footer branding, logo overlay, watermark, and optional intro/outro concatenation.
- **AI Lecture Analysis**:
  - Provider-independent transcription (OpenAI Whisper API or local `faster-whisper`).
  - Provider-independent LLM clip selection (OpenAI GPT-4o or any OpenAI-compatible endpoint such as Ollama/LM Studio).
  - Never fabricates or rewrites the scholar's words; snaps clip timestamps to complete sentences.
  - Configurable target duration (default: min 30s, preferred 45–90s, max 120s).
- **Subtitle Engine**:
  - Timestamped SRT and styled ASS subtitle generation.
  - Editable transcript/subtitle lines, position (`top`/`middle`/`bottom`), font, size, color, background box, and on/off toggle.
- **Administrator Template Editor**:
  - Live 9:16 preview with reusable templates, default template selection, and logo/intro/outro asset uploads.
- **Clip Review & Export**:
  - Approve/reject clips, edit timestamps & subtitles, regenerate individual clips, preview rendered vertical videos, and download individually or as a ZIP archive.
- **Future-Ready Architecture**:
  - Modular separation in `backend/app/modules/` (`lecture_clips` and `quran_reels` stub) sharing the reusable FFmpeg rendering and template engines.

---

## Tech Stack

- **Frontend**: React 18, TypeScript, Vite, Tailwind CSS, shadcn/ui-style components, TanStack Query, React Router
- **Backend**: Python 3.11, FastAPI, Pydantic, SQLAlchemy (Async)
- **Video/Audio**: FFmpeg, FFprobe
- **Background Queue**: Local `asyncio` worker pool (default for dev) or Celery + Redis (production)
- **Database**: SQLite (dev) or PostgreSQL (production)
- **Storage**: Local filesystem (dev) or S3-compatible object storage (production)

---

## Local Development Setup

### Prerequisites
- Python 3.11+
- Node.js 20+
- FFmpeg & FFprobe available on `PATH`

### 1. Configure Backend
```bash
cd backend
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY (or configure faster-whisper + local LLM)
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 2. Configure Frontend
```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` in your browser.

---

## Environment Variables (`backend/.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `TRANSCRIPTION_PROVIDER` | `openai` | `openai` or `faster-whisper` (local) |
| `OPENAI_API_KEY` | — | OpenAI API key for Whisper / GPT-4o |
| `WHISPER_MODEL` | `whisper-1` | OpenAI Whisper model |
| `FASTER_WHISPER_MODEL` | `large-v3` | Local faster-whisper model size |
| `LLM_PROVIDER` | `openai` | `openai` or `compatible` |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | Base URL for OpenAI-compatible APIs |
| `LLM_API_KEY` | — | LLM API key (falls back to `OPENAI_API_KEY`) |
| `LLM_MODEL` | `gpt-4o` | Model name |
| `DATABASE_URL` | `sqlite+aiosqlite:///./islamic_studio.db` | SQLite (dev) or `postgresql+asyncpg://...` |
| `STORAGE_BACKEND` | `local` | `local` or `s3` |
| `TASK_QUEUE_BACKEND` | `local` | `local` or `celery` |
| `MAX_CONCURRENT_JOBS` | `2` | Max parallel processing jobs |

---

## Running Tests

```bash
cd backend
python -m pytest -v
```

Frontend typecheck & production build:
```bash
cd frontend
npm run build
```

---

## Docker Production Deployment (PostgreSQL + Redis + Celery)

1. Export or create a root `.env` with `OPENAI_API_KEY` (and `POSTGRES_PASSWORD`, `SECRET_KEY`).
2. Start the full stack:
```bash
docker compose up --build -d
```
3. Access the app at `http://localhost:3000` (API at `http://localhost:8000`).

---

## Upload to GitHub & Build Windows `.exe` via GitHub Actions

### 1. Push Repository to GitHub
```powershell
cd "d:\video editing"
git init
git add .
git commit -m "Initial commit: Islamic Video Studio"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

### 2. Trigger the GitHub Workflows
- **CI (`.github/workflows/ci.yml`)**: Runs automatically on every push/PR to `main` (runs `pytest` with FFmpeg and builds the React frontend).
- **Build Windows EXE (`.github/workflows/build-exe.yml`)**:
  1. Open your GitHub repository → **Actions** tab → **Build Windows EXE**.
  2. Click **Run workflow** (with *Bundle FFmpeg & FFprobe* checked for a zero-dependency `.exe`).
  3. Once complete, download the **`IslamicVideoStudio-Windows-x64`** artifact containing `IslamicVideoStudio.exe`.
  - Or push a version tag (`git tag v1.0.0 && git push origin v1.0.0`) to automatically attach the `.exe` and `.zip` to a GitHub Release.

### 3. Build `.exe` Locally on Windows
```powershell
cd "d:\video editing"
.\build_exe.ps1 -IncludeFFmpeg
```
Then double-click `dist\IslamicVideoStudio.exe`. It will launch the server, open the web UI automatically in your browser, and allow you to enter your OpenAI/AI key directly on the **Settings** page (stored locally in `.env` next to the `.exe`).

