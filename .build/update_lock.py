"""Resolve declared skills to policy-compliant commits and refresh skills.lock.json.

Exits 0 on success and 1 if a skill could not be resolved. Whether anything
changed, and whether any candidate was held, is reported via --summary rather
than the exit code, since a single run can both update one skill and hold
another.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import skillpin as sp


def build_entry(spec: sp.SkillSpec, commit: dict, tree_sha: str, digest: str,
                capabilities: dict, scans: dict, previous: dict | None) -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    entry = {
        "name": spec.name,
        "repo": spec.repo,
        "path": spec.path,
        "ref": spec.ref,
        "commit": commit["sha"],
        "commitDate": commit["date"],
        "treeSha": tree_sha,
        "contentDigest": digest,
        "scanSlug": spec.scan_slug,
        "scans": scans,
        "capabilities": capabilities,
        "pinnedAt": now,
        "firstPinnedAt": (previous or {}).get("firstPinnedAt", now),
    }
    if spec.overrides:
        entry["overrides"] = spec.override_record
    return entry


def fingerprint(lock: dict) -> str:
    return json.dumps(
        {"skills": lock.get("skills", {}), "held": lock.get("held", {})},
        sort_keys=True,
    )


def process(spec: sp.SkillSpec, policy: sp.Policy, lock: dict, force: bool) -> str:
    previous = lock["skills"].get(spec.key)
    commit = sp.newest_eligible_commit(spec, policy.min_age_days)
    overrides_changed = previous is not None and (
        previous.get("overrides", {}) != spec.override_record
    )

    if (
        previous
        and previous.get("commit") == commit["sha"]
        and not overrides_changed
        and not force
    ):
        sp.log(f"  up to date at {commit['sha'][:12]} ({commit['age_days']}d old)")
        lock["held"].pop(spec.key, None)
        return "unchanged"

    for scanner, override in sorted(spec.overrides.items()):
        sp.log(f"  override on {scanner}: {override.reason}")

    tree_sha, files = sp.download_skill(spec, commit["sha"])
    digest = sp.content_digest(files)
    capabilities = sp.extract_capabilities(files)
    scans, blockers = sp.evaluate_scans(spec.scan_slug, policy, spec.overrides)

    if policy.block_on_new_capabilities:
        added = sp.new_capabilities(
            previous.get("capabilities") if previous else None, capabilities
        )
        blockers.extend(added)

    if blockers and previous:
        same_commit = previous.get("commit") == commit["sha"]
        lock["held"][spec.key] = {
            "candidateCommit": commit["sha"],
            "candidateCommitDate": commit["date"],
            "candidateContentDigest": digest,
            "blockers": blockers,
            "appliesToCurrentPin": same_commit,
            "heldAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if same_commit:
            sp.log(f"  REGRESSED: the pinned commit {commit['sha'][:12]} no longer passes policy:")
        else:
            sp.log(f"  HELD at {previous['commit'][:12]}; candidate {commit['sha'][:12]} blocked:")
        for blocker in blockers:
            sp.log(f"    - {blocker}")
        return "held-regressed" if same_commit else "held"

    if blockers:
        sp.log(f"  cannot pin initial version of {spec.key}:")
        for blocker in blockers:
            sp.log(f"    - {blocker}")
        return "held-initial"

    lock["skills"][spec.key] = build_entry(
        spec, commit, tree_sha, digest, capabilities, scans, previous
    )
    lock["held"].pop(spec.key, None)
    action = "updated" if previous else "pinned"
    sp.log(f"  {action} to {commit['sha'][:12]} ({commit['age_days']}d old, digest {digest[7:19]})")
    return action


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-resolve even if the commit is unchanged")
    parser.add_argument("--dry-run", action="store_true", help="report without writing the lockfile")
    parser.add_argument("--summary", metavar="PATH", help="write a JSON run summary to PATH")
    args = parser.parse_args()

    policy, specs = sp.load_manifest()
    lock = sp.load_lock()
    before = fingerprint(lock)

    declared = {spec.key for spec in specs}
    for stale in sorted(set(lock["skills"]) - declared):
        sp.log(f"removing {stale} (no longer declared)")
        lock["skills"].pop(stale)
    for stale in sorted(set(lock["held"]) - declared):
        lock["held"].pop(stale)

    results: dict[str, str] = {}
    failures: list[str] = []
    for spec in specs:
        sp.log(f"{spec.key} @ {spec.ref}")
        try:
            results[spec.key] = process(spec, policy, lock, args.force)
        except sp.SkillPinError as exc:
            sp.log(f"  ERROR {exc}")
            failures.append(str(exc))

    lock["generatedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    changed = fingerprint(lock) != before
    held = sorted(k for k, r in results.items() if r.startswith("held"))

    if failures:
        sp.log(f"\n{len(failures)} skill(s) could not be resolved")
    elif args.dry_run:
        sp.log("\ndry run, lockfile not written")
    elif changed:
        sp.write_lock(lock)
        sp.log(f"\nwrote {sp.LOCK_PATH.name}")
    else:
        sp.log("\nno changes")

    if args.summary:
        summary = {
            "changed": changed and not args.dry_run and not failures,
            "held": held,
            "failures": failures,
            "results": results,
            "pinsAdvanced": sorted(k for k, r in results.items() if r in ("pinned", "updated")),
        }
        Path(args.summary).write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
