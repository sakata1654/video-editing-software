"""
Transcription engine — provider-agnostic interface.
Supports:
  - openai: Uses OpenAI Whisper API (cloud, requires API key)
  - faster-whisper: Uses faster-whisper library (local, no API key)

Configure via TRANSCRIPTION_PROVIDER env var.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class TranscriptSegment:
    """One timestamped segment of transcription."""
    start: float       # seconds
    end: float         # seconds
    text: str
    words: list[dict]  # [{word, start, end}] if word-level available


@dataclass
class TranscriptionResult:
    language: str
    segments: list[TranscriptSegment]
    full_text: str

    def to_json(self) -> str:
        return json.dumps({
            "language": self.language,
            "full_text": self.full_text,
            "segments": [
                {
                    "start": s.start,
                    "end": s.end,
                    "text": s.text,
                    "words": s.words,
                }
                for s in self.segments
            ],
        }, ensure_ascii=False)

    @classmethod
    def from_json(cls, data: str) -> "TranscriptionResult":
        d = json.loads(data)
        segments = [
            TranscriptSegment(
                start=s["start"],
                end=s["end"],
                text=s["text"],
                words=s.get("words", []),
            )
            for s in d["segments"]
        ]
        return cls(
            language=d["language"],
            segments=segments,
            full_text=d["full_text"],
        )


class TranscriptionProvider(Protocol):
    async def transcribe(self, audio_path: Path) -> TranscriptionResult: ...


# ---------------------------------------------------------------------------
# OpenAI Whisper API provider
# ---------------------------------------------------------------------------
class OpenAITranscriptionProvider:
    """Uses the OpenAI Whisper API. Requires OPENAI_API_KEY."""

    def __init__(self):
        if not settings.openai_api_key:
            raise ValueError(
                "OPENAI_API_KEY is not set. "
                "Set it in .env or use TRANSCRIPTION_PROVIDER=faster-whisper for local transcription."
            )
        try:
            from openai import AsyncOpenAI
            self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        except ImportError:
            raise ImportError("Install openai package: pip install openai")

    async def transcribe(self, audio_path: Path) -> TranscriptionResult:
        logger.info("Transcribing with OpenAI Whisper: %s", audio_path.name)

        # OpenAI Whisper API has a 25MB limit — chunk if needed
        file_size_mb = audio_path.stat().st_size / 1024 / 1024
        if file_size_mb > 24:
            return await self._transcribe_chunked(audio_path)

        with open(audio_path, "rb") as f:
            response = await self.client.audio.transcriptions.create(
                model=settings.whisper_model,
                file=f,
                response_format="verbose_json",
                timestamp_granularities=["segment", "word"],
            )

        return self._parse_response(response)

    async def _transcribe_chunked(self, audio_path: Path) -> TranscriptionResult:
        """Split large audio into chunks and transcribe each."""
        import subprocess
        import tempfile
        import os

        logger.info("Audio is large (%.1f MB), chunking...", audio_path.stat().st_size / 1024 / 1024)

        chunk_duration = 600  # 10 minutes per chunk
        all_segments: list[TranscriptSegment] = []
        language = "en"
        offset = 0.0

        with tempfile.TemporaryDirectory() as tmpdir:
            # Get total duration
            probe_cmd = [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", str(audio_path)
            ]
            import subprocess, json as _json
            probe = subprocess.run(probe_cmd, capture_output=True, text=True)
            fmt = _json.loads(probe.stdout).get("format", {})
            total_duration = float(fmt.get("duration", 0))

            chunk_index = 0
            while offset < total_duration:
                chunk_path = Path(tmpdir) / f"chunk_{chunk_index:04d}.wav"
                cmd = [
                    "ffmpeg", "-i", str(audio_path),
                    "-ss", str(offset),
                    "-t", str(chunk_duration),
                    "-y", str(chunk_path),
                ]
                subprocess.run(cmd, capture_output=True, timeout=120)

                if not chunk_path.exists():
                    break

                with open(chunk_path, "rb") as f:
                    response = await self.client.audio.transcriptions.create(
                        model=settings.whisper_model,
                        file=f,
                        response_format="verbose_json",
                        timestamp_granularities=["segment"],
                    )

                result = self._parse_response(response)
                language = result.language

                # Adjust timestamps by offset
                for seg in result.segments:
                    all_segments.append(TranscriptSegment(
                        start=seg.start + offset,
                        end=seg.end + offset,
                        text=seg.text,
                        words=[
                            {**w, "start": w["start"] + offset, "end": w["end"] + offset}
                            for w in seg.words
                        ],
                    ))

                offset += chunk_duration
                chunk_index += 1

        full_text = " ".join(s.text for s in all_segments)
        return TranscriptionResult(
            language=language,
            segments=all_segments,
            full_text=full_text,
        )

    def _parse_response(self, response) -> TranscriptionResult:
        segments = []
        for seg in getattr(response, "segments", []):
            words = []
            for w in getattr(seg, "words", []):
                words.append({
                    "word": w.word,
                    "start": w.start,
                    "end": w.end,
                })
            segments.append(TranscriptSegment(
                start=seg.start,
                end=seg.end,
                text=seg.text.strip(),
                words=words,
            ))

        full_text = " ".join(s.text for s in segments)
        return TranscriptionResult(
            language=getattr(response, "language", "en"),
            segments=segments,
            full_text=full_text,
        )


# ---------------------------------------------------------------------------
# Local faster-whisper provider
# ---------------------------------------------------------------------------
class FasterWhisperProvider:
    """Uses faster-whisper for local transcription. No API key needed."""

    def __init__(self):
        try:
            from faster_whisper import WhisperModel
            logger.info("Loading faster-whisper model: %s", settings.faster_whisper_model)
            self.model = WhisperModel(settings.faster_whisper_model, device="cpu")
        except ImportError:
            raise ImportError(
                "faster-whisper not installed. "
                "Run: pip install faster-whisper"
            )

    async def transcribe(self, audio_path: Path) -> TranscriptionResult:
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_transcribe, audio_path)

    def _sync_transcribe(self, audio_path: Path) -> TranscriptionResult:
        logger.info("Transcribing with faster-whisper: %s", audio_path.name)
        segments_gen, info = self.model.transcribe(
            str(audio_path),
            beam_size=5,
            word_timestamps=True,
        )

        segments = []
        for seg in segments_gen:
            words = []
            for w in (seg.words or []):
                words.append({"word": w.word, "start": w.start, "end": w.end})
            segments.append(TranscriptSegment(
                start=seg.start,
                end=seg.end,
                text=seg.text.strip(),
                words=words,
            ))

        full_text = " ".join(s.text for s in segments)
        return TranscriptionResult(
            language=info.language,
            segments=segments,
            full_text=full_text,
        )


def get_transcription_provider() -> TranscriptionProvider:
    """Return configured transcription provider."""
    if settings.transcription_provider == "faster-whisper":
        return FasterWhisperProvider()
    return OpenAITranscriptionProvider()
