# Systemd setup for AI Social Content Generator Bot

This service runs the Telegram bot as a persistent background service
on the VPS. After setup, the bot survives:
- SSH disconnect
- VPS reboot
- Bot crashes (auto-restart)
- Clean exit via /restart admin command

## One-time setup

Run these commands as `sean` user (sudo where indicated). The repo must
be at `/home/sean/ai-projects/AI-Social-Content-Generator`. If the path
differs, edit `infra/ai-social-bot.service` accordingly before installing.

### 1. Verify the .env file exists and has correct permissions

```bash
ls -la /home/sean/ai-projects/AI-Social-Content-Generator/.env
# If it doesn't exist, create it with your tokens:
# TELEGRAM_BOT_TOKEN=...
# APIFY_API_KEY=...
# (any other env vars the bot needs)

# Restrict permissions so only sean can read it
chmod 600 /home/sean/ai-projects/AI-Social-Content-Generator/.env
```

### 2. Stop any manually-started bot process

```bash
# Find the PID
ps aux | grep "ai_social_content_generator.telegram_bot.bot" | grep -v grep

# Kill it (replace PID with the number from above)
kill <PID>

# Verify it's gone
ps aux | grep "ai_social_content_generator.telegram_bot.bot" | grep -v grep
# (should return nothing)
```

### 3. Install the service file

```bash
# Copy the service file into systemd's directory
sudo cp /home/sean/ai-projects/AI-Social-Content-Generator/infra/ai-social-bot.service /etc/systemd/system/ai-social-bot.service

# Reload systemd so it sees the new file
sudo systemctl daemon-reload
```

### 4. Enable and start

```bash
# Enable so it auto-starts on VPS boot
sudo systemctl enable ai-social-bot

# Start it now
sudo systemctl start ai-social-bot

# Verify it's running
sudo systemctl status ai-social-bot
```

You should see `Active: active (running)` in green.

### 5. Verify the bot responds in Telegram

Send `/start` to the bot. If it responds, you're done.

## Operating commands

### Check status / uptime
```bash
sudo systemctl status ai-social-bot
```

### View live logs
```bash
sudo journalctl -u ai-social-bot -f
```
(`Ctrl+C` to exit)

### View recent logs (last 100 lines)
```bash
sudo journalctl -u ai-social-bot -n 100
```

### View logs since a specific time
```bash
sudo journalctl -u ai-social-bot --since "10 min ago"
sudo journalctl -u ai-social-bot --since today
```

### Manually restart the bot
```bash
sudo systemctl restart ai-social-bot
```

### Stop the bot
```bash
sudo systemctl stop ai-social-bot
```

### Disable auto-start on boot (rarely needed)
```bash
sudo systemctl disable ai-social-bot
```

## Updating the service file

If you change `infra/ai-social-bot.service` (e.g., to add an env var
or change a path):

```bash
# Copy updated file
sudo cp /home/sean/ai-projects/AI-Social-Content-Generator/infra/ai-social-bot.service /etc/systemd/system/ai-social-bot.service

# Reload systemd
sudo systemctl daemon-reload

# Restart so the changes take effect
sudo systemctl restart ai-social-bot
```

## Updating the bot code

After `git pull` to update bot code:

```bash
sudo systemctl restart ai-social-bot

# Verify it came back
sudo systemctl status ai-social-bot
```

## Troubleshooting

### Bot won't start
Check logs:
```bash
sudo journalctl -u ai-social-bot -n 50
```

Common issues:
- `.env` file missing or wrong permissions → run step 1 above
- Path to `.venv/bin/python` wrong → check WorkingDirectory + ExecStart in the service file
- Token invalid → bot will log "Unauthorized" — update .env, restart
- Port conflicts → unlikely since bot uses polling, not webhooks
- Bot logs `FileNotFoundError` for `claude` or `claude: command not found` →
  the `claude` CLI isn't in systemd's PATH. The service file already prepends
  `/home/sean/.local/bin` to PATH; if claude was installed elsewhere, run
  `which claude` and update the `Environment="PATH=..."` line accordingly,
  then `daemon-reload` + `restart`.

### Bot keeps restarting
If logs show repeated `Started ...` followed by errors:
- Bot is crash-looping. Disable temporarily:
```bash
  sudo systemctl stop ai-social-bot
```
- Run manually to debug:
```bash
  cd /home/sean/ai-projects/AI-Social-Content-Generator
  .venv/bin/python -m ai_social_content_generator.telegram_bot.bot
```
- Fix the issue, then `sudo systemctl start ai-social-bot`

### Test SSH-close survival
1. `sudo systemctl status ai-social-bot` — note the PID
2. Exit SSH
3. SSH back in
4. `sudo systemctl status ai-social-bot` — PID should be the same, status `active (running)`

## Bot self-restart via /restart admin command

The bot's `/restart` admin command calls `sys.exit(0)`. Because the
service file has `Restart=always`, systemd will automatically respawn
the bot within 3 seconds.

DO NOT CHANGE the service file's `Restart=always` directive — the
admin command depends on it.
