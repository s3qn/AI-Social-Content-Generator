"""Phase 1 standalone demo. Runs parser → renderer → contact sheet on a
hardcoded sample compose_carousel output, prints output paths + elapsed
render time. No bot wiring."""

import asyncio
import sys
import time
from pathlib import Path

# Make 'src/' importable when running from repo root
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from ai_social_content_generator.render.parse_slides import parse_carousel_markdown
from ai_social_content_generator.render.carousel_render import render_carousel
from ai_social_content_generator.render.contact_sheet import build_contact_sheet

# Real-shaped compose_carousel output. Hebrew, 8 slides, with two
# *asterisk*-highlighted keywords planted on slides 2 and 5 to exercise
# the renderer's <span class="hl"> path. Slide 4's Text includes an &
# to exercise the escape-then-highlight ordering.
SAMPLE_RAW = """TOPIC: when partners stop being lovers in business

---
skill: compose_carousel
status: success
---

## Slide 1 (Hook)
Text: השותפים שלכם בעסק הפסיקו להיות הזוג שלכם במיטה
Visual: Two chairs at a kitchen table, one slightly pushed back, morning light, an open laptop between them.

## Slide 2
Text: זה מתחיל בקטן. *פגישת בוקר* במקום קפה ביחד.
Visual: A coffee cup growing cold next to a notebook covered in to-do items.

## Slide 3
Text: אתם מתאמנים על תפקידים, לא על קרבה. הילדים, החובות, הלקוחות.
Visual: A scheduling board with sticky notes layered on top of each other.

## Slide 4
Text: והסקס? הוא הופך לעוד משימה ברשימה. & כשהוא משימה, הוא מפסיק להיות רצון.
Visual: A checklist being filled out by hand, the last line crossed off forcefully.

## Slide 5
Text: השאלה היא לא איך מוצאים יותר זמן. השאלה היא איך *חוזרים להיות זוג* בתוך הזמן הזה.
Visual: Two hands reaching across a wooden table, fingers almost but not quite touching.

## Slide 6
Text: התחילו עם עשר דקות ביום בלי לדבר על העסק. רק עליכם.
Visual: A small clock on a windowsill, light moving across it.

## Slide 7
Text: זה מרגיש מלאכותי בהתחלה. תמשיכו. הקרבה היא שריר.
Visual: Hands kneading dough together, slowly and rhythmically.

## Slide 8 (CTA)
Text: שמרו את הפוסט הזה ושלחו אותו לבן או בת הזוג שלכם. תתחילו את השיחה.
Visual: A phone screen showing a saved post, finger hovering over a share button.

## Caption
זוגיות עסקית היא לא הבעיה. הבעיה היא שכחנו שאנחנו זוג גם בלי העסק.
אתם מכירים את התחושה?

## Hashtags
#זוגיותעסקית #שותפותעסקית #מערכתיחסים #קואצינג #זוגיות #אינטימיות #קרבה

## Attribution
- @gabormatemd ... opening with a quiet, intimate observation that names a tension the audience already feels
"""

# Sample with all asterisks removed — used by test #6 (plain-text path).
SAMPLE_RAW_NO_HL = SAMPLE_RAW.replace("*", "")

# Malformed sample — no '## Slide' headers — for test #8 (parse failure).
SAMPLE_RAW_MALFORMED = "TOPIC: nothing here\n\nJust some prose, no slide headers at all.\n"


def _print_slides(slides: list[dict]) -> None:
    if not slides:
        print("  (no slides parsed)")
        return
    for s in slides:
        preview = s["text"][:60] + ("..." if len(s["text"]) > 60 else "")
        print(f"  slide {s['n']:>2} [{s['type']:>4}] {preview}")


async def main() -> int:
    handle = "inna_cheskis"
    bg = REPO / "src" / "ai_social_content_generator" / "assets" / "sample_bg.jpg"
    out_dir = REPO / "cache" / "demo_render"

    print("=" * 60)
    print("Phase 1 carousel render demo")
    print("=" * 60)
    print(f"Background: {bg}  (exists={bg.exists()})")
    print(f"Output dir: {out_dir}")
    print()

    # --- Parse ---
    print("Parsing real sample (8 slides, 2 with *asterisks*)...")
    slides = parse_carousel_markdown(SAMPLE_RAW)
    print(f"Parsed {len(slides)} slide(s):")
    _print_slides(slides)
    if not slides:
        print("ERROR: parser returned no slides. Aborting.")
        return 1
    print()

    # Pre-flight sanity: asterisks preserved in parsed text
    has_asterisk = any("*" in s["text"] for s in slides)
    print(f"Asterisks preserved through parser: {has_asterisk}")

    # Pre-flight: malformed input returns []
    bad = parse_carousel_markdown(SAMPLE_RAW_MALFORMED)
    print(f"Malformed input parses to: {bad!r} (expected: [])")
    print()

    # --- Render ---
    print(f"Rendering {len(slides)} slides via Playwright...")
    t0 = time.monotonic()
    png_paths = await render_carousel(
        slides=slides,
        handle=handle,
        background_path=bg,
        out_dir=out_dir,
        highlight_color="#ff7a5c",
    )
    elapsed = time.monotonic() - t0
    print(f"Wrote {len(png_paths)} PNG(s) in {elapsed:.1f}s:")
    for p in png_paths:
        size_kb = p.stat().st_size / 1024
        print(f"  {p}  ({size_kb:.0f} KB)")
    print()

    # --- Contact sheet ---
    print("Composing contact sheet...")
    sheet_path = out_dir / "contact_sheet.png"
    build_contact_sheet(png_paths, sheet_path)
    sheet_kb = sheet_path.stat().st_size / 1024
    print(f"Wrote {sheet_path}  ({sheet_kb:.0f} KB)")
    print()

    print("=" * 60)
    print(f"DONE. Total render time: {elapsed:.1f}s")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
