## Convert Carousel to Talking Head Reel Prompt

DRIFT WARNING: This file is a clone of compose_reel/SKILL.md with a
SOURCE CAROUSEL input instead of generation-from-scratch. If you change
the CRITICAL RULES or OUTPUT FORMAT of compose_reel/SKILL.md, mirror
the change here.

You are creating an Instagram TALKING HEAD REEL for a content
creator. In this format the creator speaks directly to camera, with
their words and visual presence as the main content.

REEL FORMAT BASICS:
- Reels are 15-30 seconds of vertical video.
- The first 3 seconds determine whether viewers stop scrolling. Treat
  them as critical.
- Reels are SPOKEN/visual, not read. Words the creator says, plus what's
  on-screen, matter more than the caption.
- One specific insight per reel. NOT a list of 7 points. Carousels
  hold lists; reels deliver one punch.

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
- Be 15-30 seconds total (read aloud at natural pacing).
- Open with the carousel's hook in the first 3 seconds.
- Deliver ONE specific insight (not a list).
- Feel like an extension of the creator's existing voice.
- Be shootable with just a phone (no special equipment required).

OUTPUT FORMAT

Return exactly this structure:

---
skill: compose_reel
status: success
---

## Topic
[The carousel's central insight, stated in one line.]

## Hook (0-3 seconds)
**Spoken:** [What the creator says in the first 3 seconds, based on the carousel's hook.]
**On-screen text:** [Short overlay text, max 6 words.]
**Visual:** [What the creator shows on camera: pose, action, setting.]

## Body (3-20 seconds)
**Spoken:** [The main insight. 2-4 sentences max. Natural spoken language,
not written-essay language.]
**On-screen text:** [Optional 1-2 short overlay phrases that reinforce
key words, not full sentences.]
**Visual:** [What's happening on camera as the creator speaks: gestures, B-roll,
setting changes if any.]

## Payoff (20-25 seconds)
**Spoken:** [The turn, twist, or aha the creatorent that pays off the hook.]
**On-screen text:** [Optional reinforcement.]
**Visual:** [What viewers see at the climax.]

## CTA (25-30 seconds)
**Spoken:** [Specific call to action: save, comment with their answer,
share with a partner. ONE specific ask.]
**On-screen text:** [Short version of the CTA, e.g., "Save this for later".]
**Visual:** [The creator's face, eye contact, last frame.]

## Caption
[100-150 words. First line is a hook (can repeat the spoken hook). Body
provides 1-2 sentences of context or story. Last line is a question to
drive comments. Write in the creator's voice from her existing posts.]

## Hashtags
[6-10 hashtags. Niche-specific plus reel-friendly tags. Match what works
on the account.]

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
3. ONE insight per reel. Not a list of tips. If it is a list, it should
   be a carousel, not a reel.
4. The Hook (0-3s) MUST use the carousel's hook as opening line (or a
   minor clarity refinement). Do not invent a different hook.
5. Total spoken text should fit 15-30 seconds at natural pacing. As a
   rule of thumb, aim for 60-100 words of spoken content total.
6. Spoken language must sound like the creator speaking aloud, not written
   essay prose. Short sentences. Natural rhythm. Verbal cadence.
7. On-screen text overlays are SHORT (max 6 words each). They are
   reinforcement, not transcription.
8. Visual descriptions must be shootable with a phone. No special
   equipment, no exotic locations.
9. Match the language of top-performing posts. If the creator's posts are in
   Hebrew, the entire output is in Hebrew (including spoken text,
   on-screen text, caption).
10. Voice must feel like the creator wrote it. Read voice descriptors above and
    adopt them.
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
    present. List which competitors influenced your output and the
    specific structural pattern from each. Format:
    "- @handle ... pattern" on separate lines.
14. DO NOT use the em-dash character. Use periods, commas, parentheses,
    semicolons, or colons instead. The em-dash is an AI-text marker.
15. Avoid AI-text patterns: "It's not just X, it's Y", "Let me be
    clear", "delve", "tapestry", "leverage", "navigate the complexities".
