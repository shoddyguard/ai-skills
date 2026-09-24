# Issue tracker: Central GitHub repo

Issues and specs for this product don't live in this repo. They live as GitHub issues in
a central repo shared across products, separated by a product label. Use the `gh` CLI for
all operations.

## Configuration

- **Central repo**: `<owner>/<repo>`
- **Product label**: `<label>`

Both are mandatory. Never infer the repo from `git remote -v`: that points at the product
repo, which is the wrong place.

## The two rules

1. **Every command carries `--repo <central repo>`.** `gh` defaults to the clone you're
   standing in, so an omitted flag silently files the issue against the product repo.
2. **Every command carries the product label.** On create, so the issue is findable. On
   every list and search, as a filter, so you see this product's work and not the whole
   company's backlog. A query without the label is always wrong, even when it looks like
   it returned something sensible.

## Conventions

- **Create an issue**: `gh issue create --repo <central repo> --label "<label>" --title "..." --body "..."`. Use a heredoc for multi-line bodies. Any further labels go alongside the product label, never instead of it.
- **Read an issue**: `gh issue view <number> --repo <central repo> --comments`, filtering comments by `jq` and also fetching labels.
- **List issues**: `gh issue list --repo <central repo> --label "<label>" --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with any further `--label` and `--state` filters added on top.
- **Comment on an issue**: `gh issue comment <number> --repo <central repo> --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --repo <central repo> --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close <number> --repo <central repo> --comment "..."`

Issue numbers are the central repo's, so `#42` in a product repo commit message means
`<central repo>#42`. When writing a reference anywhere in the product repo, write it
fully qualified as `<owner>/<repo>#42` so a human reading it in the product repo doesn't
follow it to the wrong issue.

## Pull requests as a triage surface

**PRs as a request surface: no.** _(This is almost always `no` here: PRs land against the
product repo, issues live centrally, so the two aren't in one queue. `/triage` reads this
flag.)_

If set to `yes`, say explicitly in this file which repo the PRs live in, since it isn't
the central one.

## When a skill says "publish to the issue tracker"

Create a GitHub issue in the central repo, with the product label.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --repo <central repo> --comments`.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets. All
of it lives in the central repo and carries the product label.

- **Map**: a single issue labelled `wayfinder:map` plus the product label, holding the Notes / Decisions-so-far / Fog body. `gh issue create --repo <central repo> --label "<label>" --label wayfinder:map`.
- **Child ticket**: an issue linked to the map as a GitHub sub-issue (`gh api` on the sub-issues endpoint, against the central repo). Where sub-issues aren't enabled, add the child to a task list in the map body and put `Part of #<map>` at the top of the child body. Labels: the product label plus `wayfinder:<type>` (`research`/`prototype`/`grilling`/`task`). Once claimed, the ticket is assigned to the driving dev.
- **Blocking**: GitHub's **native issue dependencies**. Add an edge with `gh api --method POST repos/<central repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`, where `<blocker-db-id>` is the blocker's numeric **database id** (`gh api repos/<central repo>/issues/<n> --jq .id`, _not_ the `#number` or `node_id`). GitHub reports `issue_dependencies_summary.blocked_by` (open blockers only, the live gate). Where dependencies aren't available, fall back to a `Blocked by: #<n>, #<n>` line at the top of the child body. A ticket is unblocked when every blocker is closed.
- **Frontier query**: list the map's open children (`gh issue list --repo <central repo> --label "<label>" --state open`, scoped to the map's sub-issues / task list), drop any with an open blocker (`issue_dependencies_summary.blocked_by > 0`, or an open issue in the `Blocked by` line) or an assignee; first in map order wins.
- **Claim**: `gh issue edit <n> --repo <central repo> --add-assignee @me`, the session's first write.
- **Resolve**: `gh issue comment <n> --repo <central repo> --body "<answer>"`, then `gh issue close <n> --repo <central repo>`, then append a context pointer (gist + link) to the map's Decisions-so-far.
