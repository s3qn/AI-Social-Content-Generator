# AI-Social-Content-Generator

AI-powered Instagram viral content pipeline. See docs/ARCHITECTURE.md for design.

## Quickstart

```bash
uv sync --extra dev
uv run pytest
```

## Project layout

- `src/ai_social_content_generator/` — application code, organized by pipeline stage
- `prompts/` — versioned prompt templates
- `infra/` — VPS provisioning notes
- `scripts/` — operational one-offs
- `docs/` — architecture and decisions
