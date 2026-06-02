"""Async carousel renderer. One Chromium launch per render call; one page;
loop set_content + screenshot for each slide. Fonts + background are
embedded as base64 so output is byte-identical across laptop, container,
and VPS — no system font dependency."""

import base64
import html
import re
from pathlib import Path

from playwright.async_api import async_playwright

SLIDE_W = 1080
SLIDE_H = 1350
DEVICE_SCALE = 2

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
_FONT_HEEBO = _ASSETS / "fonts" / "Heebo.ttf"
_FONT_CORMORANT = _ASSETS / "fonts" / "Cormorant-Italic.ttf"


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _body_font_size(text: str) -> int:
    """Three buckets based on character length — keeps long Hebrew sentences
    legible at 1080w."""
    n = len(text)
    if n < 70:
        return 70
    if n < 110:
        return 62
    return 54


def _fmt(raw: str) -> str:
    """HTML-escape FIRST, THEN substitute *asterisk* spans. Order matters:
    escaping after the span insertion would mangle the markup AND would not
    neutralize &/</> in untrusted model text."""
    escaped = html.escape(raw)
    return re.sub(r"\*(.+?)\*", r'<span class="hl">\1</span>', escaped)


def _motif_svg(kind: str) -> str:
    """Inline SVG motifs: rings on HOOK, key icon on CTA, empty for BODY."""
    if kind == "hook":
        return """
<svg class="motif" viewBox="0 0 220 220" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <circle cx="80" cy="110" r="56" fill="none" stroke="rgba(255,255,255,0.85)" stroke-width="3"/>
  <circle cx="140" cy="110" r="56" fill="none" stroke="rgba(255,255,255,0.85)" stroke-width="3"/>
</svg>
""".strip()
    if kind == "cta":
        return """
<svg class="motif" viewBox="0 0 220 220" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <circle cx="80" cy="110" r="40" fill="none" stroke="rgba(255,255,255,0.85)" stroke-width="3"/>
  <line x1="116" y1="110" x2="190" y2="110" stroke="rgba(255,255,255,0.85)" stroke-width="3" stroke-linecap="round"/>
  <line x1="160" y1="92" x2="160" y2="128" stroke="rgba(255,255,255,0.85)" stroke-width="3" stroke-linecap="round"/>
  <line x1="180" y1="92" x2="180" y2="120" stroke="rgba(255,255,255,0.85)" stroke-width="3" stroke-linecap="round"/>
</svg>
""".strip()
    return ""


_SWIPE_SVG = """
<svg class="swipe-arrow" viewBox="0 0 56 56" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <path d="M40 12 L20 28 L40 44" fill="none" stroke="white" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
""".strip()


def _slide_html(
    *,
    slide_text_html: str,
    handle: str,
    motif_svg: str,
    show_swipe: bool,
    page_number: str | None,
    font_size_px: int,
    highlight_color: str,
    font_heebo_b64: str,
    font_cormorant_b64: str,
    bg_b64: str,
    bg_mime: str,
) -> str:
    """Build the full HTML document for one slide. The page is exactly
    SLIDE_W x SLIDE_H so screenshot(full_page=True) yields a clean PNG."""
    handle_html = html.escape(f"@{handle}")
    swipe_block = (
        f'<div class="swipe">{_SWIPE_SVG}<span class="swipe-label">החליקו</span></div>'
        if show_swipe
        else ""
    )
    page_num_block = (
        f'<div class="page-num">{html.escape(page_number)}</div>'
        if page_number
        else ""
    )
    motif_block = f'<div class="motif-wrap">{motif_svg}</div>' if motif_svg else ""

    return f"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<style>
@font-face {{
  font-family: 'Heebo';
  src: url(data:font/ttf;base64,{font_heebo_b64}) format('truetype');
  font-weight: 100 900;
  font-style: normal;
}}
@font-face {{
  font-family: 'CormorantItalic';
  src: url(data:font/ttf;base64,{font_cormorant_b64}) format('truetype');
  font-weight: 300 700;
  font-style: italic;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{
  width: {SLIDE_W}px;
  height: {SLIDE_H}px;
  overflow: hidden;
  background: #000;
  font-family: 'Heebo', sans-serif;
}}
.slide {{
  position: relative;
  width: {SLIDE_W}px;
  height: {SLIDE_H}px;
  background-image: url(data:{bg_mime};base64,{bg_b64});
  background-size: cover;
  background-position: center;
  direction: rtl;
  color: #fff;
  overflow: hidden;
}}
.scrim {{
  position: absolute; inset: 0;
  background: linear-gradient(180deg, rgba(0,0,0,0.18) 0%,
                                       rgba(0,0,0,0.45) 60%,
                                       rgba(0,0,0,0.72) 100%);
}}
.handle {{
  position: absolute;
  top: 40px; right: 48px;
  font-family: 'CormorantItalic', serif;
  font-style: italic;
  font-size: 36px;
  color: rgba(255,255,255,0.88);
  letter-spacing: 0.5px;
  text-shadow: 0 2px 8px rgba(0,0,0,0.6);
  /* Force LTR for the Latin handle — without this the bidi algorithm
     reorders "@" (a weak neutral character) to the visual end of the
     run inside an RTL parent, producing "handle@" instead of "@handle".
     unicode-bidi: isolate keeps the handle in its own bidi context. */
  direction: ltr;
  unicode-bidi: isolate;
}}
.motif-wrap {{
  position: absolute;
  top: 130px; left: 50%; transform: translateX(-50%);
  width: 220px; height: 220px;
  opacity: 0.85;
}}
.motif {{ width: 100%; height: 100%; }}
.text-wrap {{
  position: absolute;
  top: 50%; left: 0; right: 0;
  transform: translateY(-50%);
  padding: 0 80px;
  text-align: center;
}}
.text {{
  font-family: 'Heebo', sans-serif;
  font-weight: 700;
  font-size: {font_size_px}px;
  line-height: 1.25;
  color: #fff;
  text-shadow: 0 3px 14px rgba(0,0,0,0.75), 0 1px 3px rgba(0,0,0,0.85);
  word-break: keep-all;
}}
.hl {{ color: {highlight_color}; font-weight: 800; }}
.swipe {{
  position: absolute;
  bottom: 70px; left: 50%; transform: translateX(-50%);
  display: flex; align-items: center; gap: 14px;
  color: rgba(255,255,255,0.9);
  text-shadow: 0 2px 6px rgba(0,0,0,0.7);
}}
.swipe-arrow {{ width: 32px; height: 32px; }}
.swipe-label {{
  font-family: 'Heebo', sans-serif;
  font-weight: 600;
  font-size: 24px;
  letter-spacing: 1px;
}}
.page-num {{
  position: absolute;
  bottom: 70px; right: 48px;
  font-family: 'Heebo', sans-serif;
  font-weight: 600;
  font-size: 22px;
  color: rgba(255,255,255,0.78);
  letter-spacing: 0.5px;
  text-shadow: 0 1px 4px rgba(0,0,0,0.7);
}}
</style>
</head>
<body>
<div class="slide">
  <div class="scrim"></div>
  <div class="handle">{handle_html}</div>
  {motif_block}
  <div class="text-wrap"><div class="text">{slide_text_html}</div></div>
  {swipe_block}
  {page_num_block}
</div>
</body>
</html>"""


async def render_carousel(
    slides: list[dict],
    handle: str,
    background_path: Path,
    out_dir: Path,
    highlight_color: str = "#ff7a5c",
) -> list[Path]:
    """Render each slide to a 1080x1350 PNG (2x device scale = 2160x2700)
    over the background. Returns ordered output PNG paths."""
    if not slides:
        return []
    if not background_path.exists():
        raise FileNotFoundError(f"Background image not found: {background_path}")
    if not _FONT_HEEBO.exists() or not _FONT_CORMORANT.exists():
        raise FileNotFoundError(
            f"Fonts missing under {_ASSETS / 'fonts'} (Heebo.ttf, Cormorant-Italic.ttf)"
        )

    out_dir.mkdir(parents=True, exist_ok=True)

    font_heebo_b64 = _b64(_FONT_HEEBO)
    font_cormorant_b64 = _b64(_FONT_CORMORANT)
    bg_b64 = _b64(background_path)
    bg_mime = "image/jpeg" if background_path.suffix.lower() in (".jpg", ".jpeg") else "image/png"

    total = len(slides)
    written: list[Path] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            context = await browser.new_context(
                viewport={"width": SLIDE_W, "height": SLIDE_H},
                device_scale_factor=DEVICE_SCALE,
            )
            page = await context.new_page()

            for i, slide in enumerate(slides, start=1):
                text = slide.get("text", "")
                kind = slide.get("type", "body")
                slide_text_html = _fmt(text)
                font_size = _body_font_size(text)
                # Hook slide: slightly larger to feel like a headline
                if kind == "hook":
                    font_size = min(80, font_size + 8)

                show_swipe = i < total
                page_number = (
                    f"{i} / {total}"
                    if kind == "body"
                    else None
                )

                doc = _slide_html(
                    slide_text_html=slide_text_html,
                    handle=handle,
                    motif_svg=_motif_svg(kind),
                    show_swipe=show_swipe,
                    page_number=page_number,
                    font_size_px=font_size,
                    highlight_color=highlight_color,
                    font_heebo_b64=font_heebo_b64,
                    font_cormorant_b64=font_cormorant_b64,
                    bg_b64=bg_b64,
                    bg_mime=bg_mime,
                )

                await page.set_content(doc, wait_until="load")
                # Let webfonts settle (data URLs are immediate but be defensive).
                await page.wait_for_load_state("networkidle")

                out_path = out_dir / f"slide_{i:02d}.png"
                await page.screenshot(path=str(out_path), full_page=False)
                written.append(out_path)

            await context.close()
        finally:
            await browser.close()

    return written
