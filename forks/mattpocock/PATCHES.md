# Patches

What we changed and why, per skill. Anything not listed under "Patched" is byte-identical
to upstream and takes upstream's version wholesale on sync.

The `patched` flags in `skills.yaml` must match this file. If you patch a verbatim skill,
flip its flag, or the next sync will quietly overwrite your work.

## Patched

| Skill | Change |
| --- | --- |
| `setup-shoddyguard-skills` | Renamed from `setup-matt-pocock-skills`. Writes config to `.agents/config/shoddyguard-*.md`. Offers the central issue repo as the default tracker. Asks where the central docs repo is. Adds `.agents/scratchpad/` to `.gitignore`. Flags an upstream-layout repo for migration. |
| `setup-.../domain.md` | Rewritten: the "agents write only inside `.agents/`" rule, the `.agents/` layout, the central docs repo and its doc-type table for ADRs, tech specs and PDRs. |
| `setup-.../issue-tracker-local.md` | Issues move from `.scratch/` to `.agents/issues/`, which is committed. |
| `setup-.../issue-tracker-github-central.md` | New. Central repo plus product label on every command. |
| `code-review` | Config path, the renamed setup skill, and the spec search paths. |
| `domain-modeling` | Glossary at `.agents/CONTEXT.md`; multi-context glossaries at `.agents/context/`. ADRs resolve against the central docs repo, falling back to `.agents/docs/`. |
| `improve-codebase-architecture` | Glossary and ADR locations. |
| `research` | Findings land in `.agents/research/`, committed, with an offer to promote them into a tech spec. |
| `to-tickets` | Local ticket path, renamed setup skill. |
| `triage` | Renamed setup skill, glossary path, and the out-of-scope knowledge base moves from `.out-of-scope/` to `.agents/out-of-scope/` (still committed, it's institutional memory). |
| `diagnosing-bugs` | Glossary path, and the human-in-the-loop script is copied into `.agents/scratchpad/` rather than left unhomed. |
| `to-spec`, `wayfinder` | Renamed setup skill only. |
| `grill-with-docs` | Frontmatter only: "creates docs" invited exactly the `docs/` write we forbid, so it now names the glossary and the central repo. |
| `tdd`, `codebase-design`, `wait-what` | Glossary path only, one line each. |
| `to-questionnaire` | Wrote its output to the current directory; now `.agents/questionnaires/`. |
| `wizard` | Ephemeral wizards go to `.agents/scratchpad/wizards/`, and promoting one to `scripts/` is the user's call. |
| `teach` | Took over the current directory as a workspace. Now `.agents/teach/` unless it's a dedicated learning repo. |
| `prototype` | Logic prototypes are artefacts, not code, so they go to `.agents/prototypes/`. UI prototypes are real code and stay in the source tree. |
| `engineering/README.md`, `productivity/README.md` | Reframed as the forked set rather than Matt's own listing: `ask-matt` dropped, the renamed setup skill, and every description that named a path now names ours. |

## Verbatim

`implement`, `resolving-merge-conflicts`, `grilling`, `grill-me`, `handoff`,
`writing-for-agents`.

`handoff` was checked and left alone on purpose: it already writes to the OS temp
directory rather than the workspace. So does `improve-codebase-architecture` with its
HTML report, which is why that skill's patch covers only the glossary and ADR paths.

## Deliberate deviations

**Local issues aren't scratch.** Upstream's local-markdown tracker lives in `.scratch/`.
Mapping that straight onto `.agents/scratchpad/` would have put the issue tracker inside
a gitignored directory, so it went to `.agents/issues/` instead.

**`ask-matt` isn't copied.** It's a router over Matt's full skill set, and we only took
two collections of it.

**Scratch means disposable, and little qualifies.** Only `wizard` scripts and the
human-in-the-loop debugging script land in `.agents/scratchpad/`, because upstream calls
both ephemeral. Research findings, logic prototypes and questionnaires all outlive their
session, so they get committed homes. Gitignoring the prototypes in particular would have
broken the skill's own instruction to capture them on a throwaway branch.
