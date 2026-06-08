"""Stage rendered carousel slides to a public folder so the Instagram
content-publishing API can fetch them via HTTPS.

IG cURLs the `image_url` we pass it, and JPEG is the only supported
format. Our renderer writes PNG, so staging does two things:
  1. Convert each slide to JPEG.
  2. Write it to PUBLIC_IMAGE_DIR with a random uuid filename, returning
     the matching PUBLIC_IMAGE_BASE_URL/<file>.

The bot deletes staged files in a `finally:` block after publish so the
public folder stays clean — see cleanup_staged.
"""

import logging
import os
import uuid
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

DEFAULT_PUBLIC_DIR = "/var/www/img"
DEFAULT_PUBLIC_URL = "https://img.sean.build"
JPEG_QUALITY = 90


class StagingError(RuntimeError):
    """Public folder missing/unwritable, or conversion failed."""


def _public_dir() -> Path:
    return Path(os.getenv("PUBLIC_IMAGE_DIR") or DEFAULT_PUBLIC_DIR)


def _public_url_base() -> str:
    return (os.getenv("PUBLIC_IMAGE_BASE_URL") or DEFAULT_PUBLIC_URL).rstrip("/")


def _to_jpeg(src: Path, dest: Path) -> None:
    """Convert any PIL-readable image to JPEG. Flattens RGBA onto a
    white background so transparent PNGs don't render with a black
    background after IG ingests them."""
    with Image.open(src) as im:
        if im.mode in ("RGBA", "LA"):
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            bg.save(dest, "JPEG", quality=JPEG_QUALITY)
        else:
            im.convert("RGB").save(dest, "JPEG", quality=JPEG_QUALITY)


def stage_for_publish(paths: list[Path]) -> list[tuple[str, Path]]:
    """Convert each slide to JPEG and copy it to the public folder under
    a random uuid filename. Returns parallel-ordered (public_url, staged_path).

    Raises StagingError if the public folder isn't writable. Partial-
    failure cleanup is the caller's job — pass any successfully-staged
    paths back through cleanup_staged in a finally block.
    """
    if not paths:
        return []

    public_dir = _public_dir()
    if not public_dir.exists():
        raise StagingError(f"PUBLIC_IMAGE_DIR does not exist: {public_dir}")
    if not os.access(public_dir, os.W_OK):
        raise StagingError(f"PUBLIC_IMAGE_DIR not writable: {public_dir}")

    base_url = _public_url_base()
    batch = uuid.uuid4().hex[:12]
    staged: list[tuple[str, Path]] = []

    for i, src in enumerate(paths, start=1):
        if not src.exists():
            # Roll back what we've staged so far before raising.
            cleanup_staged([p for _, p in staged])
            raise StagingError(f"Slide path missing: {src}")
        name = f"carousel_{batch}_{i:02d}.jpg"
        dest = public_dir / name
        try:
            _to_jpeg(src, dest)
        except Exception as e:
            cleanup_staged([p for _, p in staged])
            raise StagingError(f"Failed to convert {src} -> {dest}: {e}") from e
        staged.append((f"{base_url}/{name}", dest))

    logger.info("Staged %d slide(s) under %s (batch=%s)", len(staged), base_url, batch)
    return staged


def cleanup_staged(paths: list[Path]) -> None:
    """Delete each staged file. Tolerant of paths that were never written
    (partial failures) and races (file removed externally). Always safe
    to call inside a finally block."""
    for p in paths:
        try:
            p.unlink(missing_ok=True)
        except Exception:
            logger.warning("Failed to remove staged file %s", p, exc_info=True)
    if paths:
        logger.info("Cleaned up %d staged file(s)", len(paths))
