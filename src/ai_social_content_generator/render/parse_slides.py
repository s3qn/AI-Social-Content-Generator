"""Parse compose_carousel markdown into ordered slide dicts.

The model's real output drifts from the idealized SKILL.md format: optional
(Hook)/(CTA) header tags, smart-quoted Text values, extra blank lines, the
Text body sometimes spanning multiple lines before the Visual: marker.
This parser is deliberately liberal — it mirrors the defensive style of
headline_picker_generate (returns [] when fewer than 3 slides parse so the
caller can fall back)."""

import re

MIN_SLIDES = 3

_SLIDE_HEADER = re.compile(
    r"^\s*##\s*Slide\s*(\d+)\s*(?:\(([^)]+)\))?\s*$",
    re.IGNORECASE,
)
_TEXT_LINE = re.compile(r"^\s*Text\s*:\s*(.*)$", re.IGNORECASE)
_VISUAL_LINE = re.compile(r"^\s*Visual\s*:", re.IGNORECASE)
_OTHER_SECTION_HEADER = re.compile(r"^\s*##\s+", re.IGNORECASE)


def _strip_text(value: str) -> str:
    """Strip whitespace AND a single pair of surrounding quotes (any kind)."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("\"", "'", "“", "”", "‘", "’", "`"):
        value = value[1:-1].strip()
    # Drop wrapping square brackets used as Text placeholder markers
    if len(value) >= 2 and value[0] == "[" and value[-1] == "]":
        value = value[1:-1].strip()
    return value


def _classify(slide_n: int, header_tag: str | None, total_count: int) -> str:
    """Classify a slide as hook / cta / body. The model usually labels them
    explicitly; fall back to position (1 = hook, last = cta)."""
    tag = (header_tag or "").strip().lower()
    if "hook" in tag:
        return "hook"
    if "cta" in tag or "call to action" in tag:
        return "cta"
    if slide_n == 1:
        return "hook"
    if total_count and slide_n == total_count:
        return "cta"
    return "body"


def parse_carousel_markdown(raw_output: str) -> list[dict]:
    """Parse compose_carousel markdown into ordered slide dicts.

    Returns: [{"type": "hook"|"body"|"cta", "n": int, "text": str,
               "sub": str | None}, ...]

    Behavior:
    - Liberal header matching: '## Slide 3', '## Slide 3 (CTA)', etc.
    - Text body is collected from the 'Text:' line and any continuation
      lines until the next 'Visual:' line, next '##' header, or end of
      input. The first Text-line content plus continuations join with a
      space; whitespace and one pair of wrapping quotes/brackets are
      stripped from the final string.
    - 'Visual:' lines are DROPPED.
    - Any '*asterisk*' markers in the text are PRESERVED verbatim for the
      renderer to style.
    - Returns [] if fewer than MIN_SLIDES slides parse (defensive — caller
      should treat as a parse failure and fall back).
    """
    if not raw_output or not raw_output.strip():
        return []

    lines = raw_output.splitlines()
    raw_slides: list[tuple[int, str | None, str]] = []  # (n, tag, text)

    i = 0
    while i < len(lines):
        m = _SLIDE_HEADER.match(lines[i])
        if not m:
            i += 1
            continue

        slide_n = int(m.group(1))
        header_tag = m.group(2)
        i += 1

        # Find the Text: line, then collect continuation lines until a stop.
        text_parts: list[str] = []
        in_text = False
        while i < len(lines):
            line = lines[i]
            if _SLIDE_HEADER.match(line):
                break  # Next slide
            tm = _TEXT_LINE.match(line)
            if tm:
                in_text = True
                first = tm.group(1)
                if first:
                    text_parts.append(first)
                i += 1
                continue
            if in_text and _VISUAL_LINE.match(line):
                break
            if in_text and _OTHER_SECTION_HEADER.match(line):
                break
            if in_text:
                # Continuation line for multi-line Text values
                stripped = line.strip()
                if stripped:
                    text_parts.append(stripped)
            i += 1

        if text_parts:
            text = _strip_text(" ".join(text_parts))
            if text:
                raw_slides.append((slide_n, header_tag, text))

    if len(raw_slides) < MIN_SLIDES:
        return []

    total = len(raw_slides)
    return [
        {
            "type": _classify(n, tag, total),
            "n": n,
            "text": text,
            "sub": None,
        }
        for (n, tag, text) in raw_slides
    ]


_SECTION_HEADER = re.compile(r"^\s*##\s+(.+?)\s*$")


def _extract_section(raw_output: str, name: str) -> str:
    """Return the body of '## {name}' (everything until the next '## ' header
    or end of input). Empty string if the section is missing. Tolerant of
    extra whitespace and blank lines."""
    if not raw_output:
        return ""

    target = name.strip().lower()
    lines = raw_output.splitlines()
    body: list[str] = []
    in_section = False

    for line in lines:
        header = _SECTION_HEADER.match(line)
        if header:
            if in_section:
                break
            if header.group(1).strip().lower() == target:
                in_section = True
            continue
        if in_section:
            body.append(line)

    return "\n".join(body).strip()


def parse_carousel_caption_hashtags(raw_output: str) -> tuple[str, str]:
    """Return (caption, hashtags) from the ## Caption and ## Hashtags sections.

    Either may be '' if absent. Never raises — missing sections, weird
    spacing, or empty input all yield empty strings. Parses against the
    full raw output so it works whether caller passes the pre-Attribution
    slice or the entire model response.
    """
    if not raw_output:
        return "", ""
    return _extract_section(raw_output, "Caption"), _extract_section(raw_output, "Hashtags")
