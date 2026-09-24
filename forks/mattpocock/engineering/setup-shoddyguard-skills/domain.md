# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Where agents write

**Agents write inside `.agents/` and nowhere else, unless they're making code or implementation changes.**

`docs/` is human-owned and privileged. Never write there, never create it, never move a
file into it. If something feels like it belongs in `docs/`, it belongs in the central
docs repo instead, and the rules below say how to get it there.

Everything in `.agents/` is committed except `.agents/scratchpad/`, which is gitignored
working space. Anything that needs to outlive the session goes somewhere else under
`.agents/`.

| Path | Holds | Committed |
| --- | --- | --- |
| `config/` | This file and its siblings, written by `/setup-shoddyguard-skills` | yes |
| `CONTEXT.md`, `context/` | The domain glossary | yes |
| `issues/` | Local-markdown issue tracker, when that's the configured tracker | yes |
| `out-of-scope/` | Rejected feature requests, written by `/triage` | yes |
| `research/` | Findings from `/research` | yes |
| `prototypes/` | Logic prototypes from `/prototype` | yes |
| `questionnaires/` | Questionnaires from `/to-questionnaire` | yes |
| `docs/` | ADRs and specs written while the central docs repo wasn't checked out | yes |
| `scratchpad/` | Working files with no life beyond the session | no |

The test for scratchpad is simple: would it matter if this vanished when the session
ended? If yes, it doesn't go there.

## Before exploring, read these

- **`.agents/CONTEXT.md`**, or
- **`.agents/CONTEXT-MAP.md`** if it exists: it points at one glossary per context under `.agents/context/`. Read each one relevant to the topic.
- **ADRs** that touch the area you're about to work in, in the central docs repo (see below). Also read anything in `.agents/docs/`, which holds docs written while the central repo wasn't available.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates them lazily when terms or decisions actually get resolved.

## File structure

Single-context repo (most repos):

```
/
├── .agents/
│   ├── CONTEXT.md
│   └── docs/                           ← only when the central repo was unavailable
└── src/
```

Multi-context repo (presence of `.agents/CONTEXT-MAP.md`):

```
/
├── .agents/
│   ├── CONTEXT-MAP.md
│   └── context/
│       ├── ordering.md
│       └── billing.md
└── src/
```

Glossaries stay under `.agents/` even in a multi-context repo. Don't scatter them into
`src/<context>/`, that puts agent-written files in the source tree.

## Where written docs go

ADRs, tech specs and PDRs live in a central docs repo, not in this repo.

- **Central docs repo**: `<owner>/<repo>`
- **Local clone path**: `<absolute path, or "not checked out">`
- **This product's subdirectory**: `<path within the clone>`

| Doc type | Subdirectory | Filename |
| --- | --- | --- |
| ADR | `adr/` | `NNNN-slug.md`, sequential, four digits |
| Tech spec | `specs/` | `<slug>.md` |
| PDR | `pdr/` | `<slug>.md` |

All three are relative to this product's subdirectory within the clone.

**When the clone is present**, write directly into it. Number ADRs by scanning the
product's `adr/` directory for the highest existing number, not this repo. Say which file
you wrote and remind the user it's a separate repo, so it needs its own commit.

**When the clone isn't present**, write to `.agents/docs/` in this repo instead, and say
plainly in your response that the doc has landed in the wrong place and needs moving into
the central repo. Don't silently skip writing it, and don't invent a `docs/` directory
here. `.agents/docs/` is committed, so nothing is lost while it waits.

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `.agents/CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0007 (event-sourced orders), but worth reopening because…_
