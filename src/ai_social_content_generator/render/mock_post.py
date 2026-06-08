"""Mock Instagram post renderer. Produces a PNG preview that approximates
how a carousel post will look in the feed — placeholder avatar, @handle,
first slide image at 4:5, carousel dots + 1/N counter, static action-row
icons, full caption (not truncated), and hashtags.

Same Playwright pattern as carousel_render: one Chromium launch, one
page, embed all assets as base64 so output is byte-identical across
machines."""

import base64
import html
from pathlib import Path

from playwright.async_api import async_playwright

CARD_WIDTH = 1080

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
_AVATAR = _ASSETS / "mock_avatar.png"


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _img_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        return "image/jpeg"
    return "image/png"


# Inline SVG action-row icons — static, no interaction. Stroke-only so they
# scale crisply at the card width.
_HEART_SVG = """
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
  <path d="M12 21s-7-4.5-9.5-9.2C.7 8.2 2.5 4 6.4 4c2 0 3.5 1.1 4.6 2.6C12.1 5.1 13.6 4 15.6 4c3.9 0 5.7 4.2 3.9 7.8C19 16.5 12 21 12 21z"/>
</svg>
""".strip()

_COMMENT_SVG = """
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
  <path d="M21 11.5a8.4 8.4 0 0 1-1.2 4.3 8.5 8.5 0 0 1-7.3 4.2 8.4 8.4 0 0 1-4.3-1.2L3 20l1.3-5.1A8.5 8.5 0 1 1 21 11.5z"/>
</svg>
""".strip()

_SHARE_SVG = """
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
  <line x1="22" y1="2" x2="11" y2="13"/>
  <polygon points="22 2 15 22 11 13 2 9 22 2"/>
</svg>
""".strip()

_BOOKMARK_SVG = """
<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round">
  <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>
</svg>
""".strip()

_MORE_SVG = """
<svg viewBox="0 0 24 24" fill="currentColor">
  <circle cx="5" cy="12" r="1.8"/>
  <circle cx="12" cy="12" r="1.8"/>
  <circle cx="19" cy="12" r="1.8"/>
</svg>
""".strip()


def _dots_html(slide_count: int) -> str:
    """Carousel dot row — current dot (index 0) is the brighter blue."""
    if slide_count <= 1:
        return ""
    dots = "".join(
        f'<span class="dot {"active" if i == 0 else ""}"></span>'
        for i in range(slide_count)
    )
    return f'<div class="dots">{dots}</div>'


def _caption_block_html(handle: str, caption: str, hashtags: str) -> str:
    """Caption + hashtags block. dir=auto so Hebrew/Arabic content gets the
    right reading order while English content stays LTR."""
    handle_html = html.escape(f"@{handle}")
    caption_html = html.escape(caption).replace("\n", "<br>") if caption else ""
    hashtag_html = (
        html.escape(hashtags).replace("\n", "<br>") if hashtags else ""
    )

    parts: list[str] = []
    parts.append(f'<span class="caption-handle">{handle_html}</span>')
    if caption_html:
        parts.append(f'<span class="caption-text">{caption_html}</span>')

    body = f'<div class="caption-line" dir="auto">{" ".join(parts)}</div>'
    if hashtag_html:
        body += f'<div class="hashtags" dir="auto">{hashtag_html}</div>'
    return body


def _build_html(
    *,
    handle: str,
    caption: str,
    hashtags: str,
    slide_count: int,
    avatar_b64: str,
    slide_b64: str,
    slide_mime: str,
) -> str:
    handle_html = html.escape(f"@{handle}")
    counter = f"1/{slide_count}" if slide_count > 1 else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{
  background: #fafafa;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  color: #262626;
  width: {CARD_WIDTH}px;
}}
.card {{
  width: {CARD_WIDTH}px;
  background: #fff;
  border: 1px solid #dbdbdb;
  border-radius: 8px;
  overflow: hidden;
}}
.header {{
  display: flex;
  align-items: center;
  padding: 22px 24px;
  gap: 18px;
}}
.avatar {{
  width: 72px; height: 72px;
  border-radius: 50%;
  background: #fff url(data:image/png;base64,{avatar_b64}) center/cover no-repeat;
  flex-shrink: 0;
  border: 2px solid #fff;
  box-shadow: 0 0 0 2px #e1306c, 0 0 0 4px #fcaf45;
}}
.handle {{
  font-weight: 600;
  font-size: 32px;
}}
.more {{
  margin-left: auto;
  width: 36px; height: 36px;
  color: #262626;
}}
.image-wrap {{
  position: relative;
  width: {CARD_WIDTH}px;
  /* 4:5 aspect — first slide image area */
  height: {int(CARD_WIDTH * 5 / 4)}px;
  background: #000;
  overflow: hidden;
}}
.image-wrap img {{
  width: 100%; height: 100%;
  object-fit: cover;
  display: block;
}}
.counter {{
  position: absolute;
  top: 22px; right: 22px;
  background: rgba(38, 38, 38, 0.75);
  color: #fff;
  border-radius: 999px;
  padding: 8px 18px;
  font-size: 24px;
  font-weight: 600;
  letter-spacing: 0.5px;
}}
.actions {{
  display: flex;
  align-items: center;
  padding: 20px 24px 8px;
  gap: 22px;
  color: #262626;
}}
.actions svg {{ width: 44px; height: 44px; }}
.action-spacer {{ flex: 1; }}
.dots {{
  display: flex;
  justify-content: center;
  gap: 8px;
  padding: 4px 0 12px;
}}
.dot {{
  width: 10px; height: 10px;
  border-radius: 50%;
  background: #c7c7c7;
}}
.dot.active {{ background: #3897f0; }}
.caption-wrap {{
  padding: 8px 26px 28px;
  font-size: 26px;
  line-height: 1.45;
}}
.caption-line {{ word-wrap: break-word; }}
.caption-handle {{ font-weight: 600; margin-inline-end: 8px; }}
.caption-text {{ white-space: pre-wrap; }}
.hashtags {{
  margin-top: 14px;
  color: #00376b;
  white-space: pre-wrap;
  word-wrap: break-word;
}}
</style>
</head>
<body>
<div class="card">
  <div class="header">
    <div class="avatar"></div>
    <div class="handle">{handle_html}</div>
    <div class="more">{_MORE_SVG}</div>
  </div>
  <div class="image-wrap">
    <img src="data:{slide_mime};base64,{slide_b64}" alt="">
    {f'<div class="counter">{html.escape(counter)}</div>' if counter else ""}
  </div>
  <div class="actions">
    {_HEART_SVG}
    {_COMMENT_SVG}
    {_SHARE_SVG}
    <div class="action-spacer"></div>
    {_BOOKMARK_SVG}
  </div>
  {_dots_html(slide_count)}
  <div class="caption-wrap">
    {_caption_block_html(handle, caption, hashtags)}
  </div>
</div>
</body>
</html>"""


async def render_mock_post(
    first_slide_path: Path,
    handle: str,
    caption: str,
    hashtags: str,
    slide_count: int,
    out_path: Path,
) -> Path:
    """Render a realistic mock Instagram post PNG.

    Card layout: avatar + @handle header, first slide image at 4:5,
    carousel dots + '1/N' counter, static action icons, full caption,
    hashtags. Viewport width is fixed at CARD_WIDTH and the page grows
    tall to fit the caption — screenshotted with full_page so long
    captions never clip.
    """
    if not first_slide_path.exists():
        raise FileNotFoundError(f"First slide not found: {first_slide_path}")
    if not _AVATAR.exists():
        raise FileNotFoundError(f"Placeholder avatar missing: {_AVATAR}")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    doc = _build_html(
        handle=handle,
        caption=caption or "",
        hashtags=hashtags or "",
        slide_count=max(slide_count, 1),
        avatar_b64=_b64(_AVATAR),
        slide_b64=_b64(first_slide_path),
        slide_mime=_img_mime(first_slide_path),
    )

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            context = await browser.new_context(
                viewport={"width": CARD_WIDTH, "height": 1600},
                device_scale_factor=1,
            )
            page = await context.new_page()
            await page.set_content(doc, wait_until="load")
            await page.wait_for_load_state("networkidle")
            await page.screenshot(path=str(out_path), full_page=True)
            await context.close()
        finally:
            await browser.close()

    return out_path
