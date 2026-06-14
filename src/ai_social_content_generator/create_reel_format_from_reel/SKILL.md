## Create Reel Format Template From a Viral Reel

DRIFT WARNING: This is a clone of create_reel_format/SKILL.md with a real
reel (transcript + pacing + frames) as input instead of a typed
description. The PLACEHOLDER CONTRACT, HOUSE RULES, and OUTPUT rules below
are identical to that file — if you change them there, mirror the change
here.

You are reverse-engineering an Instagram reel into a REUSABLE TEMPLATE for
its FORMAT. Your output is NOT a reel and is NOT about this reel's topic.
Your output is a PROMPT TEMPLATE (a .md file) that will later be filled in
to generate many reels — on OTHER topics — in this reel's structural
style.

THE SOURCE REEL

Transcript (what is said; may be empty if the reel has no speech):
"{reel_transcript}"

Pacing (measured from the audio timing):
{reel_pacing}

Visuals:
{reel_visual_note}

YOUR TASK

Analyze the reel's STRUCTURE, not its subject matter. Capture:
- The HOOK MECHANISM: how the first line and first frame stop the scroll.
- The BEAT SEQUENCE: the order of moves from open to close.
- The PACING and HOLDS: from the pacing data above. A pause before a
  payoff, or a fast stack of lines, is a STRUCTURAL feature — templatize
  it (e.g. "hold on a still for a beat before the turn").
- The CTA style and the tone/register.
- The VISUAL structure you actually SEE in the attached frames: on-screen
  text presence and placement, shot type, whether it looks like one
  continuous take or cuts. Fold this into the template's visual guidance,
  ANCHORED to what is in the frames and the pacing. Frame it as direction
  for the creator ("open on a close-up talking-head shot", "hold on a
  still during the pause"). Do NOT claim cuts or motion you cannot see
  between the sampled frames.

Produce a niche-NEUTRAL structural template: the creator's {{niche}} and
{{chosen_topic}} fill in later. Do NOT bake this reel's subject matter
into the template.

THIN-INPUT GUARD: if the transcript is empty or garbled AND the frames
carry no usable structure (e.g. a music reel with no on-screen text and no
discernible format), DO NOT fabricate a format. Output exactly the token
INSUFFICIENT_SIGNAL and nothing else.

THE TEMPLATE YOU OUTPUT MUST FOLLOW THESE RULES EXACTLY

1. PLACEHOLDERS. The template must include each of these tokens at least
   once, spelled EXACTLY like this (single curly braces, no spaces):
   {{niche}} {{voice_str}} {{themes_str}} {{chosen_topic}}
   {{chosen_headline}} {{engagement_digest}} {{competitor_section}}
   These get filled in automatically later:
   - {{niche}} the creator's niche
   - {{voice_str}} the creator's voice descriptors
   - {{themes_str}} recurring themes on their account
   - {{chosen_topic}} the topic chosen for THIS reel
   - {{chosen_headline}} the hook the creator picked (the opening line)
   - {{engagement_digest}} what has performed well on their account
   - {{competitor_section}} competitor signal for structure reference

2. NO OTHER PLACEHOLDERS. Do NOT invent any other {{token}}. Only the
   seven above are allowed. Any other curly-brace token will break
   generation. Write everything else as plain text.

3. STRUCTURE. Include an OUTPUT FORMAT section that defines a structured
   reel matching the analyzed format. Use the built-in talking-head reel
   as the reference shape (Hook / Body / Payoff / CTA / Caption /
   Hashtags), but ADAPT the beats to the structure you extracted above.

4. THE HOOK. The template must instruct that the reel OPENS with
   {{chosen_headline}} (the creator's chosen hook) in the first seconds,
   used verbatim or refined minimally.

5. HOUSE RULES (copy these into the template verbatim as CRITICAL RULES):
   - ONE specific insight per reel, never a list of tips.
   - Do NOT invent credentials, years of experience, or client stories
     not present in the creator's context.
   - Match the language of the creator's niche and voice. If Hebrew, the
     entire reel is in Hebrew.
   - DO NOT use the em-dash character. Use periods, commas, parentheses,
     semicolons, or colons instead.
   - The opening must use {{chosen_headline}}; do not invent a different
     hook.

OUTPUT

Output ONLY the template text (or the token INSUFFICIENT_SIGNAL). No
preamble, no explanation, no code fences. The first characters of your
response are the first line of the template itself.
