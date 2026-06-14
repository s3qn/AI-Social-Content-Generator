"""Extract representative frames from a downloaded viral reel for vision
analysis (Phase 3 format-from-reel).

Scene-change detection picks the visually interesting moments; a
time-interval pass guarantees a static reel (few scene changes) still
yields several frames. Never raises — returns [] on any failure so the
caller can fall back to transcript-only analysis.

ffmpeg is blocking; call extract_frames via asyncio.to_thread.
"""

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

SCENE_THRESHOLD = 0.3
FFMPEG_TIMEOUT = 60


def _run_ffmpeg(args: list[str]) -> bool:
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", *args],
            check=True, timeout=FFMPEG_TIMEOUT,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        return True
    except Exception as e:
        logger.warning("ffmpeg failed: %s", e)
        return False


def extract_frames(
    video_path: Path,
    out_dir: Path,
    max_frames: int = 6,
    duration: float | None = None,
) -> list[Path]:
    """Scene-change frames + a time-interval fallback so even a static
    reel yields several. Returns ordered frame paths (capped at
    max_frames). Never raises — returns [] on failure."""
    if shutil.which("ffmpeg") is None:
        logger.warning("extract_frames: ffmpeg not found")
        return []
    if not video_path.exists():
        logger.warning("extract_frames: missing video %s", video_path)
        return []

    # Clear the dir first so frames from a previous run can't mix in.
    if out_dir.exists():
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Scene-change frames (the visually interesting cuts).
    _run_ffmpeg([
        "-i", str(video_path),
        "-vf", f"select='gt(scene,{SCENE_THRESHOLD})'",
        "-vsync", "vfr",
        "-frames:v", str(max_frames),
        str(out_dir / "scene_%02d.jpg"),
    ])
    scene_frames = sorted(out_dir.glob("scene_*.jpg"))

    # 2. Time-interval fallback when scene-detect was too sparse (static
    #    reel). fps=1/step samples one frame every `step` seconds.
    if len(scene_frames) < max_frames:
        step = max(2.0, (duration / max_frames)) if duration else 2.0
        _run_ffmpeg([
            "-i", str(video_path),
            "-vf", f"fps=1/{step:.3f}",
            "-frames:v", str(max_frames),
            str(out_dir / "int_%02d.jpg"),
        ])
    interval_frames = sorted(out_dir.glob("int_*.jpg"))

    # Scene frames first (more informative), then interval fill, capped.
    ordered = scene_frames + interval_frames
    return ordered[:max_frames]
