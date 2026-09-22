"""Verify skills.lock.json against the manifest and against upstream content.

Checks every declared skill is locked, every locked entry matches its manifest
entry, and (unless --offline) that re-fetching each pinned commit reproduces the
recorded tree SHA and content digest.

Exit codes: 0 ok, 1 verification failed.
"""

from __future__ import annotations

import argparse
import sys

import skillpin as sp


def verify_entry(spec: sp.SkillSpec, entry: dict, offline: bool) -> list[str]:
    problems: list[str] = []

    for field in ("name", "repo", "path", "ref"):
        expected = getattr(spec, field)
        if entry.get(field) != expected:
            problems.append(f"{field} drifted: lock has {entry.get(field)!r}, manifest has {expected!r}")

    commit = entry.get("commit", "")
    if len(commit) != 40 or not all(c in "0123456789abcdef" for c in commit):
        problems.append(f"commit {commit!r} is not a full 40-character SHA")
        return problems

    if offline:
        return problems

    try:
        tree_sha, files = sp.download_skill(spec, commit)
    except sp.SkillPinError as exc:
        problems.append(f"could not fetch pinned content: {exc}")
        return problems

    if tree_sha != entry.get("treeSha"):
        problems.append(f"treeSha mismatch: upstream {tree_sha}, lock {entry.get('treeSha')}")

    digest = sp.content_digest(files)
    if digest != entry.get("contentDigest"):
        problems.append(f"contentDigest mismatch: upstream {digest}, lock {entry.get('contentDigest')}")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="skip upstream re-fetch, check structure only")
    args = parser.parse_args()

    policy, specs = sp.load_manifest()
    lock = sp.load_lock()
    failed = False

    by_key = {spec.key: spec for spec in specs}
    for orphan in sorted(set(lock["skills"]) - set(by_key)):
        sp.log(f"{orphan}: locked but not declared in skills.yaml")
        failed = True

    for spec in specs:
        entry = lock["skills"].get(spec.key)
        held = lock["held"].get(spec.key)
        if entry is None:
            if held:
                sp.log(f"{spec.key}: declared but never pinned, candidate held ({len(held['blockers'])} blocker(s))")
            else:
                sp.log(f"{spec.key}: declared but missing from the lockfile")
            failed = True
            continue

        problems = verify_entry(spec, entry, args.offline)
        if problems:
            failed = True
            sp.log(f"{spec.key}: FAILED")
            for problem in problems:
                sp.log(f"  - {problem}")
        else:
            suffix = " (structure only)" if args.offline else ""
            sp.log(f"{spec.key}: ok at {entry['commit'][:12]}{suffix}")
            if held:
                sp.log(f"  note: newer candidate {held['candidateCommit'][:12]} is held")

    if policy.min_age_days < 1:
        sp.log("warning: policy.min_age_days is below 1, the quarantine window is effectively disabled")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
