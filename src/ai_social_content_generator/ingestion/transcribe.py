"""Lazy Whisper transcription of locally-downloaded viral reels.

Transcription is deferred to the first 💡/🎤 button tap (the ~22s CPU
step), while media DOWNLOAD happens at scrape time — Instagram CDN URLs
die within hours, so an on-demand download is impossible but an
on-demand transcribe of a local file is fine.

Measured on the production VPS: faster-whisper `medium`, device=cpu,
compute_type=int8 — model load ~8s (lazy singleton), ~22s per reel,
Hebrew correct. Callers MUST run transcribe_local in a thread
(asyncio.to_thread); on the event loop it freezes the bot for everyone.
"""

import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

WHISPER_MODEL_SIZE = "medium"
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE_TYPE = "int8"

_MODEL = None


def _get_model():
    """Lazy singleton — the ~8s model load happens once per process, on
    the first transcription, not at import/startup."""
    global _MODEL
    if _MODEL is None:
        from faster_whisper import WhisperModel
        start = time.monotonic()
        _MODEL = WhisperModel(
            WHISPER_MODEL_SIZE,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE_TYPE,
        )
        logger.info(
            "Whisper model loaded (%s/%s/%s) in %.1fs",
            WHISPER_MODEL_SIZE, WHISPER_DEVICE, WHISPER_COMPUTE_TYPE,
            time.monotonic() - start,
        )
    return _MODEL


def transcribe_local(video_path: Path, max_chars: int = 1000) -> str:
    """Transcribe an already-downloaded reel to JOINED TEXT. Returns ''
    on ANY failure; never raises. Blocking ~22s of CPU — call via
    asyncio.to_thread. Kept for the text-only callers; pacing-aware
    callers use transcribe_local_segments."""
    return transcribe_local_segments(video_path, max_chars=max_chars)["text"]


def transcribe_local_segments(video_path: Path, max_chars: int = 1000) -> dict:
    """Transcribe an already-downloaded reel, returning BOTH the joined
    text AND per-segment timings:
        {"text": str, "segments": [{"start","end","text"}, ...]}
    faster-whisper already yields the segments; we used to discard them.
    Returns {"text": "", "segments": []} on ANY failure; never raises.
    Blocking ~22s of CPU — call via asyncio.to_thread."""
    try:
        if not video_path.exists():
            logger.warning("transcribe_local: missing file %s", video_path)
            return {"text": "", "segments": []}

        model = _get_model()
        start = time.monotonic()
        segments, info = model.transcribe(str(video_path))
        seg_list = [
            {"start": float(s.start), "end": float(s.end), "text": s.text.strip()}
            for s in segments
        ]
        text = " ".join(s["text"] for s in seg_list if s["text"]).strip()
        if len(text) > max_chars:
            text = text[:max_chars].rstrip() + "..."

        logger.info(
            "Transcribed %s in %.1fs lang=%s chars=%d segments=%d",
            video_path.name, time.monotonic() - start,
            getattr(info, "language", "?"), len(text), len(seg_list),
        )
        return {"text": text, "segments": seg_list}
    except Exception:
        logger.exception("transcribe_local failed for %s", video_path)
        return {"text": "", "segments": []}


def transcript_text(val) -> str:
    """Read the text view from a stored transcript that may be a plain
    string (old reports) or a {"text","segments"} object (new)."""
    if isinstance(val, dict):
        return val.get("text", "") or ""
    return val or ""


def transcript_segments(val) -> list[dict]:
    """Read segment timings from a stored transcript. Old plain-string
    transcripts have none → []."""
    if isinstance(val, dict):
        return val.get("segments", []) or []
    return []
