## Convert Carousel to Text-Overlay Reel Prompt

DRIFT WARNING: This file is a clone of compose_reel_text_overlay/SKILL.md
with a SOURCE CAROUSEL input instead of generation-from-scratch. If you
change the CRITICAL RULES or OUTPUT FORMAT of
compose_reel_text_overlay/SKILL.md, mirror the change here.

You are creating an Instagram REEL in TEXT-OVERLAY format for a
content creator.

TEXT-OVERLAY REEL FORMAT:
- The creator does NOT speak. Viewers READ the post via text that
  appears on screen, layered over background video.
- Background video is simple b-roll: hands holding coffee, walking,
  looking out a window, soft daily-life moments. No talking-head
  footage.
- Reels are 15-30 seconds of vertical video.
- The first 1-2 seconds (the opening text block) determine whether
  viewers stop scrolling.
- This format is LOW-EFFORT to shoot: the creator just needs to film
  any b-roll once and reuse for many reels.

The creator's niche is:
"{niche}"

The creator's voice (from their existing posts):
{voice_str}

Recurring themes on this account:
{themes_str}

SOURCE CAROUSEL (the creator generated this and edited it by hand — it is the
canonical content for this reel):

Hook: "{source_hook}"

Slides:
{source_slides}

Caption:
"{source_caption}"

YOUR TASK
Re-tell this carousel's content as a reel in this format. The carousel is the
source of truth:
- Preserve its CENTRAL insight and emotional arc. The reel delivers the ONE
  core insight of this carousel, not all of its beats.
- Reuse the creator's edited phrasing where it fits the reel's constraints —
  they chose these words deliberately. Compress, don't rewrite for its own sake.
- The reel's hook should be the carousel's hook (or a minimal refinement for
  this format).
- Everything else follows the format rules below.

The reel must:
- Be 15-30 seconds total reading time.
- Open with the carousel's hook as the first text block.
- Deliver ONE specific insight (not a list of 7 tips, that's a carousel).
- Read like a short emotional narrative or revelation, not bullet points.
- Feel like an extension of the creator's existing voice.
- B-roll suggestions must be shootable with a phone in everyday settings.

OUTPUT FORMAT

Return exactly this structure:

---
skill: compose_reel_text_overlay
status: success
---

## Topic
[The carousel's central insight, stated in one line.]

## Hook Text Block (0-2 seconds)
[The opening text that appears on screen, based on the carousel's hook.
Max 8 words. Punchy, scroll-stopping.]

## Body Text Blocks (2-22 seconds)
Show 4-6 sequential text blocks, each appearing on screen briefly.
Format each:

1. [Text block 1, 5-12 words]
2. [Text block 2, 5-12 words]
3. [Text block 3, 5-12 words]
4. [Text block 4, 5-12 words]
(5 and 6 optional based on content depth)

Each block should advance the narrative or build the insight. They
should read in sequence like a mini-story or revelation.

## Closing Text Block (22-27 seconds)
[The payoff, twist, or aha moment. Max 12 words. The emotional or
insight peak.]

## CTA Text Block (27-30 seconds)
[Final on-screen call to action. Max 8 words. Examples: "Save this
for later", "Tag someone", "Comment 'YES' if true".]

## Background Video Direction
[Simple b-roll suggestion. ONE setting or action throughout the reel,
NOT changing scenes per block. Examples: "Hands holding coffee, slow
morning light", "Walking outside, golden hour, viewed from shoulder
height", "Looking out a window with curtains moving softly". Must be
shootable in 2-3 minutes with a phone.]

## Caption
[100-150 words. First line is a hook (can repeat the spoken hook).
Body provides 1-2 sentences of context or story. Last line is a
question to drive comments. Write in the creator's voice.]

## Hashtags
[6-10 hashtags. Niche-specific plus reel-friendly tags.]

## Attribution
List each competitor whose pattern influenced this reel, one per line:
- @handle ... specific pattern you borrowed

(If no competitor data was provided, write only: "None used.")


TOP-PERFORMING CONTENT (study what's worked on this account):

{engagement_digest}

{competitor_section}


CRITICAL RULES (do not break these):
1. Stay in the stated niche. Do not drift.
2. Do NOT invent credentials, years of experience, client stories, or
   any biographical detail not present in the top-performing posts above.
3. ONE insight per reel. Not a list of tips. If it is a list, it
   should be a carousel, not a reel.
4. The Hook Text Block MUST use the carousel's hook as opening text
   (or a minor clarity refinement). Do not invent a different hook.
5. Total on-screen reading time should fit 15-30 seconds. Aim for
   60-100 words of on-screen text TOTAL across all blocks.
6. Text blocks must read like a person's inner voice or revelation,
   not corporate copy. Short. Emotional. Real.
7. Each text block is SHORT (max 12 words). They appear briefly on
   screen; too long and viewers can't read in time.
8. Background video direction must be ONE simple b-roll setting
   maintained throughout, NOT multiple scene changes. Shootable in
   2-3 minutes with a phone.
9. Match the language of top-performing posts. If posts are in Hebrew,
   the entire output is in Hebrew (including all text blocks and
   caption).
10. Voice must feel like the creator wrote it. Read voice descriptors
    above and adopt them.
11. The engagement_digest shows what worked in ONE corner of the
    creator's broader expertise. Use it as reference for VOICE and
    RHYTHM only — not as a template for topic angle, emotional
    anchor, or subject matter. The source carousel determines the
    territory. If the carousel's content is far from the digest examples,
    that is intentional: the creator has broader expertise than the
    digest reflects. Match the voice, not the subject.
12. Competitor data is for STRUCTURE only, not content. Form from
    competitors, substance from the creator's niche and the source carousel.
13. The Attribution section is MANDATORY whenever competitor data is
    present. Format: "- @handle ... pattern" on separate lines.
14. DO NOT use the em-dash character. Use periods, commas,
    parentheses, semicolons, or colons instead.
15. Avoid AI-text patterns: "It's not just X, it's Y", "Let me be
    clear", "delve", "tapestry", "leverage".
16. Do NOT use the literal words "mom", "the creator", or any
    identifier as a name in any output field. Output should describe
    the actions and visuals without naming the creator. Hebrew
    transliteration of English names (e.g., "מום" for "mom") is an
    error and must not appear.
