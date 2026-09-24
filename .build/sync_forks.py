"""Report upstream changes to the forks under forks/.

This tool never edits a forked file. Taking an upstream change is a deliberate
human act: the patches are prose, and a merge that looks clean can still leave a
skill quietly contradicting itself. The job here is to say what moved upstream,
whether it cleared the same policy gate as the pinned skills, and whether it
lands on a file we patched.

Modes:
  (default)  resolve upstream candidates and report what changed
  --diff     print the upstream diff for one skill, base to candidate
  --record   write what is on disk now into the lockfile, optionally at a new base
  --check    offline: verify the fork tree matches the manifest and the lockfile

Exit codes: 0 ok, 1 a fork could not be resolved or a check failed.
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import skillpin as sp


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def display(path: Path) -> str:
    try:
        return str(path.relative_to(sp.REPO_ROOT))
    except ValueError:
        return str(path)


def source_record(lock: dict, source: sp.ForkSource) -> dict:
    record = lock["forks"].setdefault(source.repo, {})
    record.setdefault("skills", {})
    return record


def base_for(record: dict, fork: sp.ForkSkill) -> tuple[str, str]:
    entry = record["skills"].get(fork.spec.path, {})
    commit = entry.get("baseCommit") or record.get("baseCommit")
    date = entry.get("baseCommitDate") or record.get("baseCommitDate", "")
    if not commit:
        raise sp.SkillPinError(
            f"{fork.key}: no base commit recorded, run --record before reporting"
        )
    return commit, date


def as_map(files: list[tuple[str, bytes]]) -> dict[str, bytes]:
    return dict(files)


def classify(base: dict[str, bytes], candidate: dict[str, bytes]) -> dict[str, list[str]]:
    return {
        "added": sorted(set(candidate) - set(base)),
        "removed": sorted(set(base) - set(candidate)),
        "modified": sorted(p for p in set(base) & set(candidate) if base[p] != candidate[p]),
    }


def decode(blob: bytes) -> list[str]:
    try:
        return blob.decode("utf-8").splitlines(keepends=True)
    except UnicodeDecodeError:
        return ["<binary>\n"]


def unified(path: str, before: bytes, after: bytes) -> str:
    return "".join(
        difflib.unified_diff(
            decode(before), decode(after), fromfile=f"a/{path}", tofile=f"b/{path}"
        )
    )


def local_state(fork: sp.ForkSkill) -> tuple[dict[str, bytes], str]:
    files = sp.read_local_files(fork.local_dir)
    return as_map(files), sp.content_digest(files)


def resolve(fork: sp.ForkSkill, policy: sp.Policy, record: dict) -> dict:
    base_commit, base_date = base_for(record, fork)
    candidate = sp.newest_eligible_commit(fork.spec, policy.min_age_days)

    result = {
        "skill": fork.spec.name,
        "path": fork.spec.path,
        "patched": fork.patched,
        "baseCommit": base_commit,
        "candidateCommit": candidate["sha"],
        "candidateCommitDate": candidate["date"],
    }

    if candidate["sha"] == base_commit:
        result["status"] = "current"
        return result

    if base_date and candidate["date"] <= base_date:
        result["status"] = "ahead"
        return result

    base_files = as_map(sp.download_skill(fork.spec, base_commit)[1])
    candidate_files = as_map(sp.download_skill(fork.spec, candidate["sha"])[1])
    changes = classify(base_files, candidate_files)

    if not any(changes.values()):
        result["status"] = "current"
        result["note"] = "commit moved but the skill's content is identical"
        return result

    local_files, local_digest = local_state(fork)
    touches_patch = fork.patched and any(
        local_files.get(path) != base_files.get(path)
        for path in changes["modified"] + changes["removed"]
    )

    scans, blockers = sp.evaluate_scans(fork.spec.scan_slug, policy, fork.spec.overrides)
    if policy.block_on_new_capabilities:
        blockers.extend(
            sp.new_capabilities(
                sp.extract_capabilities(list(base_files.items())),
                sp.extract_capabilities(list(candidate_files.items())),
            )
        )

    result.update(
        {
            "status": "blocked" if blockers else "available",
            "changes": changes,
            "blockers": blockers,
            "scans": scans,
            "touchesPatch": touches_patch,
            "localDigest": local_digest,
            "localMatchesBase": local_digest == sp.content_digest(list(base_files.items())),
        }
    )
    return result


def describe(result: dict) -> None:
    status = result["status"]
    if status == "current":
        sp.log(f"  current at {result['baseCommit'][:12]}{'; ' + result['note'] if result.get('note') else ''}")
        return
    if status == "ahead":
        sp.log(
            f"  base {result['baseCommit'][:12]} is newer than the newest commit clearing "
            f"the age gate, nothing to report"
        )
        return

    changes = result["changes"]
    counts = ", ".join(f"{len(v)} {k}" for k, v in changes.items() if v)
    sp.log(f"  UPDATE AVAILABLE at {result['candidateCommit'][:12]} ({counts})")
    for kind in ("added", "removed", "modified"):
        for path in changes[kind]:
            sp.log(f"    {kind[0].upper()} {path}")
    if result["touchesPatch"]:
        sp.log("    ! upstream changed a file we patched, this one needs a careful read")
    if not result["localMatchesBase"] and not result["patched"]:
        sp.log("    ! local content differs from its base but is marked verbatim, fix the manifest flag")
    for blocker in result["blockers"]:
        sp.log(f"    BLOCKED {blocker}")


def report(sources: list[sp.ForkSource], policy: sp.Policy, lock: dict) -> tuple[list[dict], list[str]]:
    results: list[dict] = []
    failures: list[str] = []
    for source in sources:
        record = source_record(lock, source)
        sp.log(f"{source.repo} @ {source.ref}")
        for fork in source.skills:
            sp.log(f"  {fork.spec.path}")
            try:
                result = resolve(fork, policy, record)
            except sp.SkillPinError as exc:
                sp.log(f"    ERROR {exc}")
                failures.append(str(exc))
                continue
            result["repo"] = source.repo
            describe(result)
            results.append(result)
    return results, failures


def show_diff(sources: list[sp.ForkSource], policy: sp.Policy, lock: dict, wanted: str) -> int:
    for source in sources:
        record = source_record(lock, source)
        for fork in source.skills:
            if wanted not in (fork.spec.path, fork.spec.name):
                continue
            base_commit, _ = base_for(record, fork)
            candidate = sp.newest_eligible_commit(fork.spec, policy.min_age_days)
            base_files = as_map(sp.download_skill(fork.spec, base_commit)[1])
            candidate_files = as_map(sp.download_skill(fork.spec, candidate["sha"])[1])
            sp.log(f"{fork.spec.path}: {base_commit[:12]} -> {candidate['sha'][:12]}")
            for path in sorted(set(base_files) | set(candidate_files)):
                patch = unified(
                    path, base_files.get(path, b""), candidate_files.get(path, b"")
                )
                if patch:
                    print(patch, end="")
            return 0
    sp.log(f"no fork matches {wanted!r}")
    return 1


def record_disk(sources: list[sp.ForkSource], lock: dict, wanted: str | None, commit: str | None) -> list[str]:
    problems: list[str] = []
    matched = False
    for source in sources:
        record = source_record(lock, source)
        for fork in source.skills:
            if wanted and wanted not in (fork.spec.path, fork.spec.name):
                continue
            matched = True
            try:
                _, digest = local_state(fork)
            except sp.SkillPinError as exc:
                problems.append(str(exc))
                continue
            entry = record["skills"].setdefault(fork.spec.path, {})
            if commit:
                entry["baseCommit"] = commit
                entry["baseCommitDate"] = sp.commit_date(fork.spec.repo, commit)
            entry.setdefault("baseCommit", record.get("baseCommit", ""))
            entry.setdefault("baseCommitDate", record.get("baseCommitDate", ""))
            entry["patched"] = fork.patched
            entry["localDigest"] = digest
            entry["recordedAt"] = now()
            sp.log(f"{fork.spec.path}: recorded at {entry['baseCommit'][:12]}, digest {digest[7:19]}")
    if wanted and not matched:
        problems.append(f"no fork matches {wanted!r}")
    return problems


def check(sources: list[sp.ForkSource], lock: dict) -> list[str]:
    problems: list[str] = []
    for source in sources:
        record = source_record(lock, source)
        declared = {fork.local_dir for fork in source.skills}
        for fork in source.skills:
            entry = record["skills"].get(fork.spec.path)
            try:
                _, digest = local_state(fork)
            except sp.SkillPinError as exc:
                problems.append(str(exc))
                continue
            if entry is None:
                problems.append(f"{fork.spec.path}: on disk but not recorded in the lockfile")
                continue
            if entry.get("patched") != fork.patched:
                problems.append(
                    f"{fork.spec.path}: manifest says patched={fork.patched}, "
                    f"lockfile says patched={entry.get('patched')}"
                )
            recorded = entry.get("localDigest")
            if recorded and recorded != digest:
                problems.append(
                    f"{fork.spec.path}: our copy changed since it was recorded "
                    f"({recorded[7:19]} -> {digest[7:19]}), re-run --record if that was deliberate"
                )
        for path in sorted(p for p in source.dir.rglob("*") if p.is_dir()):
            if (path / "SKILL.md").is_file() and path not in declared:
                problems.append(f"{display(path)}: forked but not declared in skills.yaml")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--diff", metavar="SKILL", help="print the upstream diff for one skill and exit")
    parser.add_argument("--record", action="store_true", help="write the on-disk state into the lockfile")
    parser.add_argument("--path", metavar="SKILL", help="limit --record to one skill")
    parser.add_argument("--commit", metavar="SHA", help="with --record, set the new base commit")
    parser.add_argument("--check", action="store_true", help="offline consistency check, no network")
    parser.add_argument("--summary", metavar="PATH", help="write a JSON run summary to PATH")
    args = parser.parse_args()

    policy, _ = sp.load_manifest()
    sources = sp.load_forks()
    lock = sp.load_lock()

    if not sources:
        sp.log("no forks declared in skills.yaml")
        return 0

    if args.check:
        problems = check(sources, lock)
        for problem in problems:
            sp.log(problem)
        sp.log(f"\n{len(problems) or 'no'} problem(s)")
        return 1 if problems else 0

    if args.diff:
        return show_diff(sources, policy, lock, args.diff)

    if args.record:
        problems = record_disk(sources, lock, args.path, args.commit)
        for problem in problems:
            sp.log(problem)
        if problems:
            return 1
        sp.write_lock(lock)
        sp.log(f"\nwrote {sp.LOCK_PATH.name}")
        return 0

    results, failures = report(sources, policy, lock)
    available = [r for r in results if r["status"] == "available"]
    blocked = [r for r in results if r["status"] == "blocked"]
    needs_care = [r for r in available if r["touchesPatch"]]

    sp.log(
        f"\n{len(available)} update(s) available, {len(needs_care)} touching a patched file, "
        f"{len(blocked)} blocked by policy"
    )
    if available:
        sp.log("Nothing has been changed on disk. Review with --diff, apply by hand, then --record.")

    if args.summary:
        Path(args.summary).write_text(
            json.dumps(
                {
                    "available": [r["path"] for r in available],
                    "needsCare": [r["path"] for r in needs_care],
                    "blocked": [r["path"] for r in blocked],
                    "failures": failures,
                    "results": results,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
