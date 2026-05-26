# AI Social Content Generator

A Telegram bot for an Instagram content creator. Generates carousels, reel scripts, and viral content research, all in the creator's voice.

Built end-to-end. Real production system with a real user.

## What it does

The creator opens Telegram. The bot offers:

- **Analyze** — scrapes the creator's Instagram account, identifies voice, themes, and engagement patterns
- **Competitors** — analyzes up to 10 competitors in the niche for inspiration
- **Brainstorm** — generates topic ideas in the creator's voice, vault-stored, expandable
- **Carousel** — composes 5-9 slide carousels with hook, body, CTA, caption, and hashtags
- **Reel** — composes talking-head or text-overlay reel scripts
- **Viral Posts Research** — scrapes top-performing reels in the niche by keyword, exports to Excel for manual study
- **Scheduler** — daily posting reminders at 9am or 6pm Jerusalem time

Output language is matched to the creator's content. Voice and style are matched via cached analysis of existing posts.

## Why this exists

AI content tools either ignore individual voice and produce generic content, or require technical skill the end user doesn't have. This bot solves both: it learns from the creator's existing posts and runs entirely from Telegram.

## The interesting parts (engineering)

This project surfaced a lot of real production problems. Some highlights:

**Subprocess concurrency.** Early on, every Claude generation froze the bot for 30-90 seconds. Only one user could do anything at a time. Fixed by switching from synchronous subprocess calls to asyncio.create_subprocess_exec and enabling concurrent_updates on the Application.

**Hebrew transliteration bugs.** Prompts originally referenced the user by an English role term. Claude transliterated that to Hebrew and occasionally produced incoherent output. Fixed by using consistent role-neutral language across all prompts.

**AI myopia.** The bot consistently produced content from one narrow corner of the creator's expertise. Tracked it to a prompt rule that locked Claude to pattern-match tone from top posts, including topic and emotional anchor, not just voice. Rewrote the rule to separate voice and rhythm from subject matter.

**Cache-driven flows.** Each handle has profile, posts, and analysis cached on disk. Atomic writes. Manual invalidation. Survives bot restarts.

**Picker chains.** Topic vault (30-cap, UUID-keyed) feeds a topic picker, which feeds a headline picker that generates 7-10 hook variants just-in-time, which feeds the content generator. Three async stages, each editable mid-flow.

**Production persistence.** Runs under systemd with auto-restart, journal logging, and a /restart admin command that exits cleanly so systemd respawns it.

**Real iteration.** Bugs found by the actual user drove real fixes. Some sessions were observation, not coding.

More technical detail in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Tech stack

- Python 3.12 (uv-managed dependencies)
- python-telegram-bot with the job-queue extra for scheduling
- Apify for Instagram scraping (apify/instagram-scraper for profiles, patient_discovery/instagram-search-reels for viral keyword search)
- Claude Code for content generation via subprocess
- openpyxl for Excel export
- systemd for production persistence

## Status

Actively maintained for production use. Not designed for general redeployment, but the code is here for the curious.

Bug reports and feature requests welcome via [Issues](https://github.com/s3qn/AI-Social-Content-Generator/issues).

## License

MIT
