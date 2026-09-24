---
name: setup-shoddyguard-skills
description: "Configure this repo for the engineering skills: set up its issue tracker, triage label vocabulary, and domain doc layout. Run once before first use of the other engineering skills."
disable-model-invocation: true
---

# Setup Shoddyguard Skills

Scaffold the per-repo configuration that the engineering skills assume:

- **Issue tracker**: where issues live (a central repo tagged per product by default; GitHub, GitLab and local markdown are also supported)
- **Triage labels**: the strings used for the five canonical triage roles
- **Domain docs**: where the glossary lives, where ADRs and specs are written, and the consumer rules for reading them

This is a prompt-driven skill, not a deterministic script. Explore, present what you found, confirm with the user, then write.

Everything this skill writes goes under `.agents/`. `docs/` is human-owned: never write there.

## Process

### 1. Explore

Look at the current repo to understand its starting state. Read whatever exists; don't assume:

- `git remote -v` and `.git/config`: is this a GitHub repo? Which one?
- `AGENTS.md` and `CLAUDE.md` at the repo root: does either exist? Is there already an `## Agent skills` section in either?
- `.agents/CONTEXT.md` and `.agents/CONTEXT-MAP.md`
- `.agents/config/`: does this skill's prior output already exist?
- `.agents/issues/`: a sign that a local-markdown issue tracker convention is already in use
- `.gitignore`: is `.agents/scratchpad/` already ignored?
- A stray root `CONTEXT.md`, or a `docs/adr/` directory: signs this repo was set up with upstream's layout and needs migrating. Flag these, don't move them yourself.
- Is the `triage` skill installed? (a `triage` skill folder alongside this one, or `triage` in your available skills.) This decides whether Section B runs at all.
- Monorepo signals: a `pnpm-workspace.yaml`, a `workspaces` field in `package.json`, or a populated `packages/*` with its own `src/`. These are present only in a genuinely large multi-package repo; their absence means single-context, which is almost every repo.

### 2. Present findings and ask

Summarise what's present and what's missing. Then take the sections in order. One section, one answer, then the next.

Lead each section with the recommended answer so the user can accept it in a word. Give a one-line explainer only when the choice genuinely branches; skip the section entirely when exploration already settled it (Section B when `triage` isn't installed, Section C's layout question when there's no monorepo).

**Section A: Issue tracker.**

> Explainer: The "issue tracker" is where issues live for this repo. Skills like `to-tickets`, `triage`, and `to-spec` read from and write to it. They need to know whether to call `gh issue create` against a central repo, against this one, write a markdown file, or follow some other workflow you describe. Pick the place you actually track work for this product.

Default posture: we track issues centrally, in one repo shared across products, separated by a product label. Propose that first. Offer:

- **Central GitHub repo** (default): issues live in a shared repo, tagged with this product's label. Ask for the central repo (`<owner>/<repo>`) and the product label; both are mandatory, so don't guess either.
- **GitHub**: issues live in this repo's own GitHub Issues (uses the `gh` CLI). Propose this only if the user says this product tracks its own work.
- **GitLab**: issues live in the repo's GitLab Issues (uses the [`glab`](https://gitlab.com/gitlab-org/cli) CLI)
- **Local markdown**: issues live as files under `.agents/issues/<feature>/` in this repo (good for solo projects or repos without a remote)
- **Other** (Jira, Linear, etc.): ask the user to describe the workflow in one paragraph; the skill will record it as freeform prose

Record the choice in `.agents/config/shoddyguard-issue-tracker.md`. The GitHub and GitLab templates carry a "PRs as a request surface" flag, defaulted **off**. Leave it off and don't raise it: a user who wants external PRs in the triage queue can flip the flag in the file later.

**Section B: Triage label vocabulary.** Skip this section entirely if the `triage` skill isn't installed (exploration told you), since an uninstalled skill needs no labels.

If it is installed, ask exactly one question:

> Do you want to keep the default triage labels? (recommended: **yes**)

The defaults are the five canonical roles, each label string equal to its name: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. On **yes**, write them as-is. Only if the user says no, usually because their tracker already uses other names (e.g. `bug:triage` for `needs-triage`), collect the overrides so `triage` applies existing labels instead of creating duplicates.

On a central tracker, the product label is not a triage label and never replaces one. It's recorded in the issue-tracker config and applied on top of whatever triage label is in play.

**Section C: Domain docs.**

Two parts, both needed.

_Where written docs go._ ADRs, tech specs and PDRs live in our central docs repo, not in the product repo. Ask for:

- the central docs repo (`<owner>/<repo>`)
- the local clone path, if they have one checked out
- this product's subdirectory within it

If they don't have it checked out, record that: docs will land in `.agents/docs/` with a warning until they do. Don't refuse to continue over a missing clone.

_Layout._ Default to **single-context** (one `.agents/CONTEXT.md`). This fits almost every repo; write it without asking.

Offer **multi-context** (`.agents/CONTEXT-MAP.md` pointing at per-context glossaries under `.agents/context/`) only when exploration found monorepo signals. Then confirm which layout they want.

### 3. Confirm and edit

Show the user a draft of:

- The `## Agent skills` block to add to whichever of `CLAUDE.md` / `AGENTS.md` is being edited (see step 4 for selection rules)
- The contents of `.agents/config/shoddyguard-issue-tracker.md`, `.agents/config/shoddyguard-domain.md`, and `.agents/config/shoddyguard-triage-labels.md` (the last only when `triage` is installed)
- The `.gitignore` line, if it isn't there already

Let them edit before writing.

### 4. Write

**Pick the file to edit:**

- If `CLAUDE.md` exists, edit it.
- Else if `AGENTS.md` exists, edit it.
- If neither exists, ask the user which one to create; don't pick for them.

Never create `AGENTS.md` when `CLAUDE.md` already exists (or vice versa); always edit the one that's already there.

If an `## Agent skills` block already exists in the chosen file, update its contents in-place rather than appending a duplicate. Don't overwrite user edits to the surrounding sections.

The block:

```markdown
## Agent skills

Agents write inside `.agents/` only, unless making code or implementation changes. `docs/` is human-owned.

### Issue tracker

[one-line summary of where issues are tracked, naming the central repo and product label if used]. See `.agents/config/shoddyguard-issue-tracker.md`.

### Triage labels

[one-line summary of the label vocabulary]. See `.agents/config/shoddyguard-triage-labels.md`.

### Domain docs

[one-line summary: glossary layout, and where ADRs and specs are written]. See `.agents/config/shoddyguard-domain.md`.
```

Include the `### Triage labels` sub-block, and write `.agents/config/shoddyguard-triage-labels.md`, only when `triage` is installed and Section B ran. When it isn't, both are omitted.

Then write the config files using the seed templates in this skill folder as a starting point:

- [issue-tracker-github-central.md](./issue-tracker-github-central.md): central GitHub repo, tagged per product
- [issue-tracker-github.md](./issue-tracker-github.md): this repo's own GitHub issues
- [issue-tracker-gitlab.md](./issue-tracker-gitlab.md): GitLab issue tracker
- [issue-tracker-local.md](./issue-tracker-local.md): local-markdown issue tracker
- [triage-labels.md](./triage-labels.md): label mapping (only if `triage` is installed)
- [domain.md](./domain.md): domain doc consumer rules + layout

Each lands at `.agents/config/shoddyguard-<name>.md`, with the placeholders filled in from the answers. For "other" issue trackers, write `.agents/config/shoddyguard-issue-tracker.md` from scratch using the user's description, keeping the same section headings so the consuming skills still find what they need.

Finally, add `.agents/scratchpad/` to `.gitignore` if it isn't already there. The rest of `.agents/` is committed.

### 5. Done

Tell the user the setup is complete and which engineering skills will now read from these files. Mention they can edit `.agents/config/*.md` directly later; re-running this skill is only necessary if they want to switch issue trackers or restart from scratch.

If exploration found a root `CONTEXT.md` or a `docs/adr/` directory from upstream's layout, say so now and offer to migrate them: the glossary into `.agents/`, the ADRs into the central docs repo. Don't do it unasked.
