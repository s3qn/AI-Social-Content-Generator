## Expand Topic Prompt

The user has provided a SEED idea for Instagram content. Your job is
to generate 10 related topic ideas that build on the seed and explore
it from different angles.

USER'S SEED IDEA:
"{idea}"

CREATOR CONTEXT

Niche:
"{niche}"

Voice descriptors:
{voice_str}

Recurring themes:
{themes_str}

Match the language of the existing posts and voice. If they wrote in
Hebrew, generate in Hebrew. If English, English. The entire output
language must match the voice and themes above.

TOP-PERFORMING CONTENT (signal for what resonates):

{engagement_digest}

{competitor_section}

TOPICS ALREADY BRAINSTORMED (DO NOT REPEAT THESE):

{existing_topics_str}

YOUR TASK

Generate exactly 10 topic ideas that build on the seed idea above.
Each topic:
- Connects directly to the seed idea (same broad territory).
- Approaches the seed from a DIFFERENT angle than the other 9.
- Is 5 to 15 words.
- Is specific and concrete (a post-ready angle, not a vague theme).
- Does NOT duplicate any topic in "TOPICS ALREADY BRAINSTORMED".
- Is format-agnostic (could become a carousel, reel, or single post).

Vary the shape across the 10. Mix several of:
- Pain-points the audience feels.
- Frameworks or step-by-step structures.
- Contrarian takes the niche rarely says out loud.
- Story arcs (real situations, before and after).
- How-tos with a specific outcome.
- Myth-busting common beliefs in the niche.

Do not make all 10 the same shape.

OUTPUT FORMAT

Return ONLY a numbered list 1 through 10. One topic per line.

Format exactly:
1. <topic>
2. <topic>
3. <topic>
...
10. <topic>

No headers. No preamble like "Here are 10 topics:". No commentary
after. No JSON. No markdown code fences. Just the numbered list.
This is critical for parsing.

CRITICAL RULES (do not break these)
1. The seed idea drives the territory. Do NOT drift to unrelated
   areas. Every one of the 10 topics must connect to the seed.
2. Generate exactly 10 topics. Not 5, not 15. Ten.
3. Do NOT repeat any topic listed in TOPICS ALREADY BRAINSTORMED.
   Generate fresh ones.
4. Vary angles across the 10: pain-points, frameworks, contrarian
   takes, story arcs, how-tos, myth-busting. Don't make all 10 the
   same shape.
5. Topics inform direction only. Do NOT write the carousel itself.
   No slide structure, no captions, no hashtags. Just the topic line.
6. DO NOT USE THE EM-DASH CHARACTER. Use periods, commas, parentheses,
   semicolons, or colons instead.
7. Match the language of the existing posts and voice.
8. Output is ONLY the numbered list. No preamble. No closing remarks.
   The first character of your response must be "1" and the last
   character must be the final topic's last word.
