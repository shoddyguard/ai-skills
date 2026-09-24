# Forks

Third-party skills I maintain a modified copy of, rather than consuming upstream
unchanged.

Some skills hardcode assumptions that clash with how I work: where agent config lives,
where files are written, what commands are used etc. These are hardcoded into the skill
and can't easily be changed

There's also the case where I like the overall design of a skill but want/need to tweak it to
get it to work for me, this allows me to do that without the weight of maintaining an entire fork.

## Layout

One directory per upstream author/owner, each with a copy of that project's licence,
a README crediting the author, and a `PATCHES.md` recording which skills are modified and why.

## Updating

Updates are never applied automatically due to the very real risk that a patch can break the
patches.

`python .build/sync_forks.py` will report on what has changed and any issues encountered.

| Command | Does |
| --- | --- |
| `python .build/sync_forks.py` | Report what upstream has that we don't |
| `python .build/sync_forks.py --diff <skill>` | Print the upstream diff, base to candidate |
| `python .build/sync_forks.py --record --path <skill> --commit <sha>` | Record a hand-applied update against its new base |
| `python .build/sync_forks.py --check` | Offline: does the forked tree still match the manifest and lockfile? |

To update: read the report, read the diff, edit the files, re-run `--record`
to bump the base. `--check` catches a skill that drifted without its `patched` flag being
flipped, which is the failure mode that would otherwise lose a patch silently.

Base commits and content digests live in the `forks` block of `skills.lock.json`.
