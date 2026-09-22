# ai-skills

This repo contains the skills that I use for AI tooling.
It includes a list of the external skills I use plus the skills I write myself.

## External skills

### How a pin is chosen

`.build/update_lock.py` runs weekly. For each entry in `skills.yaml` it:

1. Lists the upstream commits that touched the skill's directory, and picks the
   newest one at least `policy.min_age_days` old. Anything more recent stays in
   quarantine, so a bad publish has time to be noticed by someone other than me.
2. Downloads the skill at that exact commit and records the tree SHA and a
   SHA-256 digest over the sorted file contents.
3. Fetches the published scanner verdicts from skills.sh and requires every
   scanner in `policy.scanners.required` to report a pass, with any risk level
   it does publish at or below `policy.scanners.max_risk`.
4. Diffs the capabilities against the currently pinned version: the frontmatter
   `allowed-tools`, the set of bundled script files, network patterns under
   `egress`, and credential and code-execution patterns under `access`. Anything
   new is raised for a human to review.

A candidate that clears all four increments the pin to the accepted version and raises a pull request.
One that fails any of them leaves the existing pin alone and is recorded under
`held` in the lockfile with its blockers, for further investigation

### The lockfile

`skills.lock.json` is the source of truth:

| Field | Purpose |
| --- | --- |
| `repo`, `path`, `commit` | The exact content to fetch, for example `https://raw.githubusercontent.com/{repo}/{commit}/{path}/SKILL.md` |
| `treeSha` | GitHub tree SHA of the skill directory, used for drift check |
| `contentDigest` | SHA-256 over the sorted file contents, ensures content remains as accepted |
| `scans`, `capabilities` | More granular information about what was fetched |
| `ref` | Upstream branch the pin was resolved from |

I recommend fetching by `commit` as this resolves to a SHA.

The `held` section contains any updates that fail our checks and require inspection.

### Adding a skill

Add an entry to `skills.yaml`:

```yaml
  - name: some-skill
    repo: owner/repo
    path: path/to/skills/some-skill
    ref: main
```

`slug` is optional and only needed when the skills.sh page path differs from
`{repo}/{leaf of path}`, which is what the scan lookup assumes.

Then run the updater and commit both files:

```sh
pip install -r .build/requirements.txt
python .build/update_lock.py
python .build/verify_lock.py
```

A brand new skill that fails the gate is never pinned at all, so it will not
appear in `skills.lock.json` until it passes.

### Overriding a scanner verdict

Sometimes a update is worth taking despite a scanner failure. An entry can relax a named scanner if desired:

```yaml
  - name: some-skill
    repo: owner/repo
    path: path/to/skills/some-skill
    ref: main
    overrides:
      snyk:
        max_risk: medium
        verdicts: [warn]
        reason: "W012, the HTML report template loads tailwind from a CDN at runtime"
```

| Key | Purpose |
| --- | --- |
| `max_risk` | Risk ceiling for this scanner on this skill, replacing `policy.scanners.max_risk` |
| `verdicts` | Extra verdicts to treat as a pass alongside `pass`, `passed` and `ok` |
| `reason` | Why the finding is acceptable, required |

### Commands

| Command | Does |
| --- | --- |
| `python .build/update_lock.py` | Resolve pins and rewrite the lockfile |
| `python .build/update_lock.py --dry-run` | Report what would change |
| `python .build/update_lock.py --force` | Re-resolve and refresh scan data even when the commit is unchanged |
| `python .build/verify_lock.py` | Check the lockfile against the manifest and re-verify upstream content |
| `python .build/verify_lock.py --offline` | Structural checks only, no network |
| `python -m unittest discover -s .build -p "test_*.py"` | Tests for the gate logic |

Set `GITHUB_TOKEN` to avoid unauthenticated API rate limits.
