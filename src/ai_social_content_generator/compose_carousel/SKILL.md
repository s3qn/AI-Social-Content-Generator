## Compose Carousel Prompt
You are creating an Instagram carousel post for a content creator.

The creator's niche is:
"{niche}"

The top-performing content from this account is below. Use it to 
understand voice, audience, themes, and what drives engagement. Match 
the language: if posts are in Hebrew, respond in Hebrew. If English, 
English.

YOUR TASK
Compose ONE complete carousel post the creator could publish today, 
informed by what has worked on this account before.

TOPIC SELECTION (do this first):
Before writing the carousel, pick ONE specific topic anchored to the 
creator's data:
1. The topic must connect to themes or recent posts shown below 
   (not invented, not generic).
2. The topic must have a CONCRETE angle (a specific question, a 
   specific situation, a specific story arc) — not a vague theme.
3. Vary your choices: avoid the most obvious topic in the niche. 
   Reach for the second or third interesting topic, not the first.

State your chosen topic at the top of your output as:
TOPIC: [the specific topic, 5-12 words]

The carousel must:
- Be relevant to the chosen topic AND the stated niche above (niche 
  is ground truth, do not drift)
- Be ONE cohesive idea expanded across slides, NOT a list of unrelated tips
- Build on patterns from top-performing posts — similar tone, similar 
  hook style — but bring a fresh angle. Do NOT copy a previous post.
- Match the creator's existing voice — feel like an extension of what 
  they already do

SLIDE COUNT
Pick 5 to 9 slides based on the idea:
- 5-6 slides for a single insight or short story
- 7-8 slides for a framework or multi-step process
- 9 slides only if the idea genuinely needs that much space
Do not pad slides with filler to hit a number.

VISUAL CONCEPTS — IMPORTANT
Avoid coaching-cliché visuals: two chairs facing each other, dim 
therapy rooms, hands clasped across desks, sad person looking out 
window, couple silhouettes against sunset. These are overused.

Use real-world METAPHORS instead. Each slide's visual should be a 
distinct concept, not variations of the same scene. Examples of 
metaphor patterns (use as inspiration, not as templates):
- Two trees with intertwined roots (partnership)
- A bridge being built mid-air (repair, trust)
- A garden where two sections meet (growth together)
- Hands kneading dough together (slow collaboration)
- A compass with two needles pointing different directions (misalignment)
- A house with two architects sketching simultaneously (shared vision)
- A boat with two oars in sync vs out of sync (rhythm)

Reach for ordinary objects and natural scenes that carry the meaning 
metaphorically. Vary across slides — don't repeat the same metaphor 
type twice in one carousel.

OUTPUT FORMAT

Return exactly this structure:

TOPIC: [the specific topic you chose, 5-12 words]

---
skill: compose_carousel
status: success
---

## Slide 1 (Hook)
Text: [The opening line that makes people stop scrolling. A question, a 
bold claim, or a surprising statement. Avoid generic openers like 
"Did you know..." or "5 tips for..."]
Visual: [Metaphorical visual concept, not a literal coaching scene]

## Slide 2
Text: [...]
Visual: [Different metaphor concept from Slide 1]

[Continue for chosen number of slides — at least 5, at most 9]

## Slide N (CTA)
Text: [A call to action: comment, save, share, or DM. Specific.]
Visual: [...]

## Caption
[100-200 words. First line hooks. Body provides context or story. 
End with a question for engagement. Line breaks between sections.]

## Hashtags
[8-12 hashtags. Niche-specific + broader reach. Avoid only-massive-tags.]

## Attribution
List each competitor whose pattern influenced this carousel, one per line in this format:
- @handle ... specific pattern you borrowed

(If no competitor data was provided in the input, write only: "None used.")


TOP-PERFORMING CONTENT (study what's worked on this account):

{engagement_digest}

{competitor_section}


CRITICAL RULES (do not break these):
1. Stay in the stated niche. Do not drift.
2. Do NOT invent credentials, years of experience, client stories, or 
   any biographical detail not present in the top-performing posts above.
3. ONE cohesive idea across all slides — not 5 separate tips.
4. The hook (Slide 1) must make people swipe. Generic openers fail.
5. The CTA (last slide) must be specific and actionable.
6. Match the language of the top-performing posts. If they wrote in 
   Hebrew, the entire output is in Hebrew.
7. Voice should feel like the creator wrote it.
8. Build on what's worked — don't copy. Pattern-match tone and direction, 
   then bring a fresh angle.
9. Competitor data is for STRUCTURE only, not for content. Extract 
   patterns (hook style, slide flow, CTA type, topic framing). Do NOT 
   borrow topics, examples, or specific claims from competitor posts. 
   Form from competitors, substance from the creator's niche.
10. The Attribution section is MANDATORY whenever competitor data is 
    present in the input above. List which competitors influenced your 
    output and the specific structural pattern from each. Do not omit. 
    Format: "- @handle ... pattern" on separate lines, one per competitor.
11. DO NOT USE THE EM-DASH CHARACTER. Use periods, commas, parentheses, 
    semicolons, or colons instead. The em-dash is an AI-text marker. 
    Write like a real person.
12. Avoid AI-text patterns: "It's not just X, it's Y" constructions, 
    "Let me be clear", "delve", "tapestry", "leverage", "robust", 
    "navigate the complexities". Write naturally, not like a marketing blog.
13. Visual descriptions must use real-world metaphors, NOT literal 
    coaching scenes (no two chairs, no dim rooms, no hands across desks). 
    Each slide visual must be a different metaphor.