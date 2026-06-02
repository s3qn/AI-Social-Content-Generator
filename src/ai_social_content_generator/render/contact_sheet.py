"""Compose ordered slide PNGs into a single 4-column contact sheet on a
dark background — proven layout from the prototype."""

from pathlib import Path

from PIL import Image

COLS = 4
THUMB_W = 420
THUMB_H = 525  # 4:5 aspect
GUTTER = 18
PAD = 24
BG = (28, 22, 34)  # #1c1622


def build_contact_sheet(slide_paths: list[Path], out_path: Path) -> Path:
    """Compose slide PNGs into a 4-column grid. Returns out_path."""
    if not slide_paths:
        raise ValueError("build_contact_sheet: no slide paths provided")

    n = len(slide_paths)
    rows = (n + COLS - 1) // COLS

    sheet_w = PAD * 2 + COLS * THUMB_W + (COLS - 1) * GUTTER
    sheet_h = PAD * 2 + rows * THUMB_H + (rows - 1) * GUTTER
    sheet = Image.new("RGB", (sheet_w, sheet_h), BG)

    for i, p in enumerate(slide_paths):
        row, col = divmod(i, COLS)
        x = PAD + col * (THUMB_W + GUTTER)
        y = PAD + row * (THUMB_H + GUTTER)
        with Image.open(p) as im:
            im = im.convert("RGB")
            im.thumbnail((THUMB_W, THUMB_H), Image.LANCZOS)
            # Center within the cell if aspect mismatch leaves padding
            ox = x + (THUMB_W - im.width) // 2
            oy = y + (THUMB_H - im.height) // 2
            sheet.paste(im, (ox, oy))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, "PNG")
    return out_path
