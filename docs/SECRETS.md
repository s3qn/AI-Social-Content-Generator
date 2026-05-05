# Secret keys

Secrets live in a single .env file at the project root.

- Listed in `.gitignore`
- Set to `user rw` only
- Loaded with `python-dotenv`
- Documented in `.env.example`

I picked plain `.env` over SOPS/Vault because I'm one dev on one VPS — encryption shifts the threat rather than solving it. I'll revisit when another dev joins or when this thing handles other people's data.

# How to add your own keys


When I sign up for a new service (e.g. ElevenLabs) and get an API key, here's
exactly what to do with it. Steps in order.

## 1. Add it to `.env.example` (committed template)

Open `.env.example` and add a placeholder line under the right section:

```bash
ELEVENLABS_API_KEY=
```

Empty value is fine — this file is the template, not the real one.

## 2. Add the real value to `.env` (NEVER committed)

```bash
nano .env
```

Add the line with the real value:

```bash
ELEVENLABS_API_KEY=sk_abc123...
```

Save (Ctrl+O, Enter, Ctrl+X).

## 3. Verify `.env` is still gitignored

```bash
git status
```

Should NOT list `.env`. If it does, STOP — `.gitignore` is broken, do not commit.

## 4. Use it in code

```python
import os
from dotenv import load_dotenv

load_dotenv()  # reads .env into environment

api_key = os.environ["ELEVENLABS_API_KEY"]
```

`load_dotenv()` only needs to be called once per process, usually at the
entrypoint of whatever script/module is running.

## 5. Update `docs/SECRETS.md`

Add a row to the "Currently held secrets" table so future-me remembers what
this key is for and where to get a new one if it gets revoked.

## 6. Commit

```bash
git status
```

Confirm `.env` is NOT listed but `.env.example` and `docs/SECRETS.md` ARE.

```bash
git add .
git commit -m "Add ELEVENLABS_API_KEY"
git push
```

---

## Common mistakes to avoid

- **Never `cat .env` in a screen-sharing session, recording, or chat.** Same
  for any AI assistant you paste output into. The whole point of secrets is
  that they live in one place; pasting them anywhere else defeats it.
- **Never hardcode a key in Python.** If I'm tempted, that means I haven't
  loaded `.env` correctly — fix that, don't shortcut.
- **Don't commit a key by accident.** If it happens, the key is burned —
  rotate it immediately at the provider, then `git rm` and force-push won't
  save you (the key is in history forever, scrapers find it within minutes).

## Rotating a key

If a key leaks or just on a regular schedule:

1. Log into the provider's dashboard
2. Revoke the old key
3. Generate a new one
4. Update `.env` with the new value
5. Restart any running services that use it
6. (No commit needed — `.env` isn't tracked)

