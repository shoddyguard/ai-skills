---
name: research
description: Investigate a question against high-trust primary sources and capture the findings as a Markdown file in .agents/research/. Use when the user wants a topic researched, docs or API facts gathered, or reading legwork delegated to a background agent.
---

Spin up a **background agent** to do the research, so you keep working while it reads.

Its job:

1. Investigate the question against **primary sources** (official docs, source code, specs, first-party APIs), not a secondary write-up of them. Follow every claim back to the source that owns it.
2. Write the findings to a single Markdown file, citing each claim's source.
3. Save it to `.agents/research/<slug>.md` and say where. That directory is committed: the reading was expensive, and a later session shouldn't have to redo it. Where the findings settle something durable, offer to promote them into a tech spec in the central docs repo (see `.agents/config/shoddyguard-domain.md`). Never write to `docs/`.
