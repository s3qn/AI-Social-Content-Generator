## Create Reel Format Template Prompt

You are building a REUSABLE TEMPLATE for an Instagram reel format, based
on a content creator's description of the format they want. Your output
is NOT a reel. Your output is a PROMPT TEMPLATE (a .md file) that will
later be filled in and used to generate many reels in this format.

THE FORMAT THE CREATOR WANTS

Name: "{format_name}"

Description (their words):
"{format_description}"

YOUR TASK

Write a complete compose-reel prompt template that captures this format.
When the template is later filled with a specific creator's context and a
chosen topic+hook, it must produce ONE shootable reel in the described
style.

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
   reel adapted to the described format. Use the built-in talking-head
   reel as the reference shape (Hook / Body / Payoff / CTA / Caption /
   Hashtags), but ADAPT the beats to the format described above — the
   creator's description drives the structure and tone.

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

Output ONLY the template text. No preamble, no explanation, no code
fences. The first characters of your response are the first line of the
template itself.
