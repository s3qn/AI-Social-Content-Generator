## Brainstorm Topics Prompt

You are brainstorming Instagram content TOPICS for a content creator.

These are core ideas (concept-level), not headlines and not full posts.
Each topic will later be turned into a carousel, reel, single image,
or other post format. Brainstorming is format-agnostic. Your job is to
surface strong topic angles, not to compose any specific post.

CREATOR CONTEXT

Niche:
"{niche}"

Voice descriptors:
{voice_str}

Recurring themes:
{themes_str}

Match the language of the existing posts and voice. If they wrote in
Hebrew, brainstorm in Hebrew. If English, English. The entire output
language must match the voice and themes above.

TOP-PERFORMING CONTENT (signal for what resonates):

{engagement_digest}

{competitor_section}

TOPICS ALREADY BRAINSTORMED (DO NOT REPEAT THESE):

{existing_topics_str}

YOUR TASK

Generate 10 to 15 distinct topic ideas. Each topic:
- Is 5 to 15 words.
- Connects to the stated niche above.
- Is specific enough to build one Instagram post around (not a vague
  theme like "relationships", but a concrete angle like "Why couples
  in business stop having sex").
- Is meaningfully different from the other topics in your list
  (different angle, not 10 variations of one theme).
- Does NOT duplicate any topic in "TOPICS ALREADY BRAINSTORMED" above.

Vary the shape of the topics. Mix several of:
- Pain-points the audience feels.
- Frameworks or step-by-step structures.
- Contrarian takes the niche rarely says out loud.
- Story arcs (real situations, before and after).
- How-tos with a specific outcome.
- Myth-busting common beliefs in the niche.

Do not make all of them the same shape.

OUTPUT FORMAT

Return ONLY a numbered list. One topic per line. Nothing else.

Format exactly:
1. <topic>
2. <topic>
3. <topic>
...

No headers. No preamble like "Here are 10 topics:". No commentary
after. No JSON. No markdown code fences. Just the numbered list.
This is critical for parsing.

CRITICAL RULES (do not break these)
1. Each topic must be specific enough to build one Instagram post
   around (carousel, reel, or single image). Not vague themes like
   "relationships", but concrete angles like "Why couples in business
   stop having sex".
2. Do NOT repeat any topic listed in TOPICS ALREADY BRAINSTORMED.
   Generate fresh ones.
3. Vary angles: pain-points, frameworks, contrarian takes, story arcs,
   how-tos, myth-busting. Don't make all topics the same shape.
4. Topics inform direction only. Do NOT write the carousel itself.
   No slide structure, no captions, no hashtags. Just the topic line.
5. DO NOT USE THE EM-DASH CHARACTER. Use periods, commas, parentheses,
   semicolons, or colons instead. The em-dash is an AI-text marker.
6. Match the language of the existing posts and voice. If they wrote
   in Hebrew, the entire output is in Hebrew.
7. Output is ONLY the numbered list. No "Here are 10 topics:" preamble.
   No closing remarks. The first character of your response must be
   "1" and the last character must be the final topic's last word.
