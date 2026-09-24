# Matt Pocock's skills

These skills are Matt Pocock's work, taken from
[github.com/mattpocock/skills](https://github.com/mattpocock/skills) and modified to fit
our conventions. All credit for the design and the writing goes to him; the bugs I
introduce are mine.

Licensed MIT, see [LICENSE](./LICENSE). The original copyright notice is preserved
unchanged.

## What's here

The `engineering` and `productivity` collections, 24 skills, laid out as upstream lays
them out. `ask-matt` is deliberately excluded: it's a router over Matt's full skill set,
and this isn't Matt's full skill set.

Nothing from `misc`, `in-progress` or `deprecated` is taken.

## What we changed

See [PATCHES.md](./PATCHES.md) for the per-skill breakdown. In short, the skills assume a
repo layout we don't use:

| Upstream | Ours |
| --- | --- |
| `docs/agents/*.md` | `.agents/config/shoddyguard-*.md` |
| `.scratch/` (agent working files) | `.agents/scratchpad/`, gitignored |
| `.scratch/` (local issue tracker) | `.agents/issues/`, committed |
| `CONTEXT.md` at the repo root | `.agents/CONTEXT.md` |
| `src/<context>/CONTEXT.md` | `.agents/context/<name>.md` |
| `docs/adr/` | the central docs repo, or `.agents/docs/` as a fallback |
| Issues in the product's own repo | a central repo, tagged per product |
| `setup-matt-pocock-skills` | `setup-shoddyguard-skills` |

The underlying rule: agents write inside `.agents/` and nowhere else, unless they're
making code or implementation changes. `docs/` is ours, not theirs.

## Provenance

Initially imported at upstream `c55ee46073ed923f86ce59a5eb3b6d895095d1b7`
(2026-09-18), byte-identical, with the patches applied as a separate commit on top so the
diff stays reviewable.

That import deliberately skipped the 30-day quarantine window that
`policy.min_age_days` applies to pinned skills, on the grounds that every file was read
by a human on the way in. Subsequent syncs run the full gate.
