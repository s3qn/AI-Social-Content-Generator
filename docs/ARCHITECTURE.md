# Architecture

Technical overview of the system. For curious readers and for future-me coming back to this code.

## High-level flow

A user interacts with the bot via Telegram. The bot's job is to gather context about the creator's content, feed that context to Claude with a structured prompt, and return polished output back through Telegram.

A typical generation request flows: User taps a button in Telegram → action handler fires → handler loads user state from the JSON vault → handler reads cached Instagram analysis from disk → handler loads the relevant SKILL.md template and fills it with context → handler calls Claude via subprocess → output streams back → handler formats and sends the response to Telegram.

External calls go to Apify (Instagram scraping) and to the Claude Code CLI (content generation). No external state — everything persists to disk.

## Key components

### Telegram interface
- bot.py is the main entry, registers all handlers, builds the Application
- actions/ contains one module per top-level user action (carousel, reel, brainstorm, competitors, viral, settings, admin)
- auth.py provides require_auth and require_admin decorators

### Persistence
- users/<user_id>.json holds per-user vault state (handle, niche, competitors, topics, viral keywords, reminder schedule)
- cache/<handle>-profile.json holds the Instagram profile snapshot
- cache/<handle>-posts.json holds the top 20 most-recent Instagram posts
- cache/<handle>-analysis.json holds derived voice, themes, and engagement digest
- cache/viral_<keyword>.json holds scraped viral reels per keyword

All writes are atomic (write-to-temp, then rename) to survive crashes mid-write.

### Skills (prompt templates)
- src/ai_social_content_generator/<skill>/SKILL.md is one per content type
- Skills are Python .format() templates with placeholders like {niche}, {voice_str}, {engagement_digest}
- Rules embedded in the template enforce voice, language, format, and a no-em-dash policy

### Claude integration
- call_claude.py exposes message_claude(prompt) as an async wrapper
- Uses asyncio.create_subprocess_exec to invoke the Claude Code CLI
- Returns stdout, returncode, and stderr
- Subprocess is non-blocking; the bot remains responsive during generation

### Scheduling
- scheduler.py uses python-telegram-bot's job_queue, which wraps APScheduler
- Stores schedule choice in user vault as reminder_schedule with enabled and slot fields
- Rebuilds all jobs from vault on bot startup via the post_init hook
- One job per user with deterministic naming so cancel and replace are safe

### Production runtime
- infra/ai-social-bot.service is the systemd unit
- Restart=always plus RestartSec=3 enables the /restart admin command (process exits cleanly, systemd respawns within seconds)
- Environment loaded from .env via systemd's EnvironmentFile directive
- Logs go to the system journal, viewable via journalctl -u ai-social-bot

## Data flows by feature

### Analyze
The user taps Analyze. The bot checks if cache/<handle>-profile.json exists. If not, Apify scrapes the profile and the 20 most-recent posts. Cached posts and profile then feed into the analyze prompt. Claude returns structured analysis (voice, themes, top_posts, engagement_patterns), which is cached as <handle>-analysis.json.

### Brainstorm
Cached analysis loads as context. Claude generates 5-7 fresh topic ideas. Each topic gets a UUID. The vault stores up to 30 topics with FIFO eviction. The user can polish or expand any existing topic via a re-prompt.

### Carousel and Reel
The user picks Carousel or Reel from the main menu. A topic picker shows the vault. After topic pick, a headline picker generates 7-10 hook variants just-in-time. After headline pick, full content generation runs with chosen topic plus chosen hook. Claude returns slides or script plus caption plus hashtags plus attribution.

### Viral Posts Research
The user adds up to 15 keywords. On Generate, each keyword scrapes 2 pages of Instagram reels via Apify. Per-keyword pipeline: dedupe by post code, compute engagement score as (shares + comments) divided by views, tier by selecting the top 3 all-time plus the top 2 from the last 30 days. Results assemble into an openpyxl workbook (one sheet per keyword) and ship to Telegram as a document.

### Scheduler
The user picks Morning (09:00) or Evening (18:00) Jerusalem time. The vault stores enabled true and the chosen slot. schedule_reminder_for_user registers a daily APScheduler job. The job sends a plain text reminder when its time hits. On bot restart, rebuild_all_reminders_on_startup walks the users directory and re-registers all jobs.

### Admin commands
Four commands are gated to a single user_id.
- /restart calls os._exit(0); systemd respawns within 3 seconds
- /broadcast <message> iterates iter_all_users(), sends to each user, throttled to 20 messages per second
- /status reports uptime since process start, user count, and PID
- /testschedule [seconds] fires the daily-brief callback once, N seconds from now (default 60, floor 5), for the calling admin only. Test tool; does not affect the real daily reminder schedule.

## Real lessons

A few notes for future-me:

**Subprocess vs API.** Started with subprocess to the Claude Code CLI because it was the fastest path. The real cost was process startup per generation (slow) and parsing stdout (fragile). The real benefit was no API key in the bot and the Claude Max subscription covering usage. Trade-off has been worth it so far.

**JSON vault beats a database.** For a single-digit user count, files are fine. Atomic writes give crash safety. No migrations, no schema. When user count grows, swap to SQLite without changing the action layer.

**Caching is half the value.** Real cost without caching: every menu interaction triggers an Apify scrape (slow plus dollars). With cache: scrape once, browse instantly. Manual invalidation beat automatic — the user knows when to refresh.

**Production is a different environment.** Same code works in a terminal and breaks under systemd because the PATH differs. Real fix: explicit Environment="PATH=..." in the service file. Real lesson: always test the production runtime, not just python -m.

**Iteration beats planning.** The first version of every feature was wrong. The carousel SKILL.md was rewritten three times. The brainstorm flow had two pivot rounds. The viral tool went through three Actor candidates before landing on the working one. Plan less, ship more, fix fast.
