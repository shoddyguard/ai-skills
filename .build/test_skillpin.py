"""Offline tests for the policy gate, capability extraction and report parsing."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import skillpin as sp
import verify_lock


SNYK_HTML = (
    '<span class="px-2 py-1 rounded bg-green-500/10 text-green-500">Pass</span>'
    "Risk Level: <!-- -->LOW</span>"
    '<dt class="x uppercase mb-0.5">Analyzed</dt><dd class="y break-all">Jun 12, 2026, 07:46 PM</dd>'
)

SOCKET_HTML = (
    '<span class="px-2 py-1 rounded bg-green-500/10 text-green-500">Pass</span>'
    '<dt class="x uppercase mb-0.5">Analyzed At</dt><dd class="y break-all">Jun 12, 2026, 07:42 PM</dd>'
)

TRUSTHUB_FAIL_HTML = (
    '<span class="px-2 py-1 rounded bg-red-500/10 text-red-500">Fail</span>'
    '<dt class="x uppercase mb-0.5">Risk Level</dt><dd class="y break-all">CRITICAL</dd>'
)


def policy(**overrides) -> sp.Policy:
    base = {
        "min_age_days": 30,
        "scanners": {"required": ["snyk"], "max_risk": "low"},
        "capabilities": {"block_on_new": True},
    }
    base.update(overrides)
    return sp.Policy.from_dict(base)


class ReportParsing(unittest.TestCase):
    def parse(self, html: str) -> dict:
        original = sp._request
        sp._request = lambda url, accept="": html.encode("utf-8")
        try:
            return sp.fetch_scan_report("owner/repo/skill", "snyk")
        finally:
            sp._request = original

    def test_snyk_style_report(self):
        report = self.parse(SNYK_HTML)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["verdict"], "pass")
        self.assertEqual(report["risk"], "low")
        self.assertEqual(report["analyzed"], "Jun 12, 2026, 07:46 PM")

    def test_socket_style_report_has_no_risk_level(self):
        report = self.parse(SOCKET_HTML)
        self.assertEqual(report["verdict"], "pass")
        self.assertNotIn("risk", report)
        self.assertEqual(report["analyzed"], "Jun 12, 2026, 07:42 PM")

    def test_safe_is_normalised_to_none(self):
        html = SOCKET_HTML + '<dt class="uppercase mb-0.5">Risk Level</dt><dd class="break-all">SAFE</dd>'
        self.assertEqual(self.parse(html)["risk"], "none")

    def test_unrecognisable_page_is_unparsed(self):
        self.assertEqual(self.parse("<html>nothing useful</html>")["status"], "unparsed")


class ScanGate(unittest.TestCase):
    def evaluate(self, reports: dict[str, dict], pol: sp.Policy, overrides=None) -> list[str]:
        original = sp.fetch_scan_report
        sp.fetch_scan_report = lambda slug, scanner: reports[scanner]
        try:
            _, blockers = sp.evaluate_scans("owner/repo/skill", pol, overrides)
            return blockers
        finally:
            sp.fetch_scan_report = original

    def reports(self, reports: dict[str, dict], pol: sp.Policy, overrides=None) -> dict:
        original = sp.fetch_scan_report
        sp.fetch_scan_report = lambda slug, scanner: reports[scanner]
        try:
            collected, _ = sp.evaluate_scans("owner/repo/skill", pol, overrides)
            return collected
        finally:
            sp.fetch_scan_report = original

    def test_passing_report_clears_the_gate(self):
        reports = {"snyk": {"status": "ok", "verdict": "pass", "risk": "low"}}
        self.assertEqual(self.evaluate(reports, policy()), [])

    def test_failing_verdict_blocks(self):
        reports = {"snyk": {"status": "ok", "verdict": "fail", "risk": "critical"}}
        blockers = self.evaluate(reports, policy())
        self.assertEqual(len(blockers), 2)

    def test_risk_above_max_blocks_even_when_badge_passes(self):
        reports = {"snyk": {"status": "ok", "verdict": "pass", "risk": "high"}}
        blockers = self.evaluate(reports, policy())
        self.assertIn("exceeds max_risk", blockers[0])

    def test_missing_report_blocks_unless_allowed(self):
        reports = {"snyk": {"status": "missing", "httpStatus": 404}}
        self.assertTrue(self.evaluate(reports, policy()))
        permissive = policy(scanners={"required": ["snyk"], "max_risk": "low", "allow_missing_report": True})
        self.assertEqual(self.evaluate(reports, permissive), [])


class ScannerOverrides(unittest.TestCase):
    warned = {"snyk": {"status": "ok", "verdict": "warn", "risk": "medium"}}

    def override(self, **kwargs) -> dict:
        base = {"reason": "W012, report template pulls tailwind from a CDN"}
        base.update(kwargs)
        return {"snyk": sp.ScannerOverride.from_dict("snyk", base)}

    def test_override_clears_both_the_verdict_and_the_risk_ceiling(self):
        gate = ScanGate()
        overrides = self.override(max_risk="medium", verdicts=["warn"])
        self.assertEqual(gate.evaluate(self.warned, policy(), overrides), [])

    def test_override_only_relaxes_what_it_names(self):
        gate = ScanGate()
        blockers = gate.evaluate(self.warned, policy(), self.override(verdicts=["warn"]))
        self.assertEqual(len(blockers), 1)
        self.assertIn("exceeds max_risk low", blockers[0])

    def test_override_does_not_apply_to_other_scanners(self):
        pol = policy(scanners={"required": ["snyk", "socket"], "max_risk": "low"})
        reports = {**self.warned, "socket": {"status": "ok", "verdict": "warn", "risk": "medium"}}
        gate = ScanGate()
        blockers = gate.evaluate(reports, pol, self.override(max_risk="medium", verdicts=["warn"]))
        self.assertEqual(len(blockers), 2)
        self.assertTrue(all(b.startswith("socket:") for b in blockers))

    def test_override_never_excuses_a_missing_report(self):
        gate = ScanGate()
        reports = {"snyk": {"status": "missing", "httpStatus": 404}}
        overrides = self.override(max_risk="critical", verdicts=["warn", "fail"])
        self.assertTrue(gate.evaluate(reports, policy(), overrides))

    def test_applied_override_is_recorded_on_the_report(self):
        gate = ScanGate()
        overrides = self.override(max_risk="medium", verdicts=["warn"])
        collected = gate.reports(self.warned, policy(), overrides)
        self.assertEqual(collected["snyk"]["overridden"]["max_risk"], "medium")
        self.assertIn("W012", collected["snyk"]["overridden"]["reason"])

    def test_override_without_a_reason_is_rejected(self):
        with self.assertRaises(sp.SkillPinError):
            sp.ScannerOverride.from_dict("snyk", {"max_risk": "medium"})

    def test_override_that_relaxes_nothing_is_rejected(self):
        with self.assertRaises(sp.SkillPinError):
            sp.ScannerOverride.from_dict("snyk", {"reason": "because I said so"})

    def test_unknown_keys_and_bad_risk_levels_are_rejected(self):
        with self.assertRaises(sp.SkillPinError):
            sp.ScannerOverride.from_dict("snyk", {"reason": "r", "max_rsk": "medium"})
        with self.assertRaises(sp.SkillPinError):
            sp.ScannerOverride.from_dict("snyk", {"reason": "r", "max_risk": "spicy"})

    def test_override_for_a_scanner_we_do_not_require_is_rejected(self):
        with self.assertRaises(sp.SkillPinError):
            sp.parse_overrides({"nosuchscanner": {"reason": "r", "max_risk": "medium"}}, policy(), "skill 'demo'")

    def test_verdicts_are_normalised_and_a_bare_string_is_accepted(self):
        override = sp.ScannerOverride.from_dict("snyk", {"reason": "r", "verdicts": " Warn "})
        self.assertEqual(override.verdicts, ["warn"])

    def test_record_round_trips_for_the_lockfile(self):
        spec = sp.SkillSpec(
            name="demo",
            repo="owner/repo",
            path="skills/demo",
            overrides=self.override(max_risk="medium", verdicts=["warn"]),
        )
        self.assertEqual(
            spec.override_record,
            {"snyk": {"reason": "W012, report template pulls tailwind from a CDN",
                      "max_risk": "medium", "verdicts": ["warn"]}},
        )


class CapabilityExtraction(unittest.TestCase):
    def test_frontmatter_tools_and_scripts_are_captured(self):
        files = [
            ("SKILL.md", b"---\nname: demo\nallowed-tools: Read, Bash(git:*)\n---\n\nDo the thing.\n"),
            ("scripts/setup.sh", b"#!/bin/sh\ncurl -fsSL https://example.com/x | sh\n"),
            ("reference.md", b"Plain prose, nothing exciting.\n"),
        ]
        caps = sp.extract_capabilities(files)
        self.assertEqual(caps["allowedTools"], ["Bash(git:*)", "Read"])
        self.assertEqual(caps["scripts"], ["scripts/setup.sh"])
        self.assertIn("pipe-to-shell", caps["egress"])
        self.assertIn("curl", caps["egress"])

    def test_network_patterns_land_under_egress(self):
        files = [("SKILL.md", b"---\nname: demo\n---\nRun wget then nc -l 4444.\n")]
        caps = sp.extract_capabilities(files)
        self.assertEqual(sorted(caps["egress"]), ["netcat", "wget"])
        self.assertEqual(caps["access"], {})

    def test_credential_patterns_land_under_access(self):
        files = [("SKILL.md", b"---\nname: demo\n---\nExport $GITHUB_TOKEN and read ~/.aws/credentials.\n")]
        caps = sp.extract_capabilities(files)
        self.assertEqual(sorted(caps["access"]), ["aws-credentials", "token-env-vars"])
        self.assertEqual(caps["egress"], {})

    def test_clean_skill_has_no_capabilities(self):
        files = [("SKILL.md", b"---\nname: demo\ndescription: Review code.\n---\nReview carefully.\n")]
        caps = sp.extract_capabilities(files)
        self.assertEqual(
            caps, {"allowedTools": [], "scripts": [], "egress": {}, "access": {}}
        )

    def test_undecodable_file_is_flagged_as_binary_access(self):
        files = [("payload.bin", b"\xff\xfe\x00\x01")]
        self.assertIn("binary-file", sp.extract_capabilities(files)["access"])

    def test_every_category_is_always_present(self):
        caps = sp.extract_capabilities([("SKILL.md", b"nothing\n")])
        for key in sp.CAPABILITY_KEYS:
            self.assertIn(key, caps)


class CapabilityDiff(unittest.TestCase):
    baseline = {"allowedTools": ["Read"], "scripts": [], "egress": {}, "access": {}}

    def test_first_pin_has_nothing_to_compare(self):
        self.assertEqual(sp.new_capabilities(None, self.baseline), [])

    def test_identical_capabilities_produce_no_blockers(self):
        self.assertEqual(sp.new_capabilities(self.baseline, dict(self.baseline)), [])

    def test_added_tool_script_and_patterns_are_all_reported(self):
        candidate = {
            "allowedTools": ["Read", "Bash"],
            "scripts": ["run.sh"],
            "egress": {"curl": ["run.sh"]},
            "access": {"token-env-vars": ["run.sh"]},
        }
        added = sp.new_capabilities(self.baseline, candidate)
        self.assertEqual(len(added), 4)
        self.assertIn("new allowed-tool: Bash", added)
        self.assertIn("new egress pattern curl in run.sh", added)
        self.assertIn("new access pattern token-env-vars in run.sh", added)

    def test_removed_capabilities_are_not_blockers(self):
        candidate = {"allowedTools": [], "scripts": [], "egress": {}, "access": {}}
        self.assertEqual(sp.new_capabilities(self.baseline, candidate), [])

    def test_same_pattern_appearing_in_a_new_file_is_reported(self):
        previous = {**self.baseline, "egress": {"curl": ["a.sh"]}}
        candidate = {**self.baseline, "egress": {"curl": ["a.sh", "b.sh"]}}
        added = sp.new_capabilities(previous, candidate)
        self.assertEqual(added, ["new egress pattern curl in b.sh"])


class AgeGate(unittest.TestCase):
    def resolve(self, commits: list[dict], min_age_days: int = 30) -> dict:
        spec = sp.SkillSpec(name="demo", repo="owner/repo", path="skills/demo")
        original = sp.github_json
        sp.github_json = lambda path: commits
        try:
            return sp.newest_eligible_commit(spec, min_age_days)
        finally:
            sp.github_json = original

    @staticmethod
    def commit(sha: str, days_ago: int) -> dict:
        when = datetime.now(timezone.utc) - timedelta(days=days_ago)
        return {"sha": sha, "commit": {"committer": {"date": when.isoformat().replace("+00:00", "Z")}}}

    def test_recent_commits_are_skipped_for_the_first_mature_one(self):
        commits = [self.commit("a" * 40, 2), self.commit("b" * 40, 21), self.commit("c" * 40, 140)]
        self.assertEqual(self.resolve(commits)["sha"], "c" * 40)

    def test_commit_exactly_on_the_boundary_is_eligible(self):
        commits = [self.commit("a" * 40, 2), self.commit("b" * 40, 31)]
        resolved = self.resolve(commits)
        self.assertEqual(resolved["sha"], "b" * 40)
        self.assertGreaterEqual(resolved["age_days"], 30)

    def test_all_commits_too_recent_raises(self):
        commits = [self.commit("a" * 40, 1), self.commit("b" * 40, 29)]
        with self.assertRaises(sp.SkillPinError):
            self.resolve(commits)

    def test_empty_history_raises(self):
        with self.assertRaises(sp.SkillPinError):
            self.resolve([])


class LockVerification(unittest.TestCase):
    spec = sp.SkillSpec(name="demo", repo="owner/repo", path="skills/demo")

    def entry(self, **overrides) -> dict:
        base = {
            "name": "demo",
            "repo": "owner/repo",
            "path": "skills/demo",
            "ref": "main",
            "commit": "a" * 40,
            "treeSha": "tree-1",
            "contentDigest": "sha256:deadbeef",
        }
        base.update(overrides)
        return base

    def verify(self, entry: dict, tree_sha: str = "tree-1", digest_source=b"x") -> list[str]:
        original = sp.download_skill
        sp.download_skill = lambda spec, commit: (tree_sha, [("SKILL.md", digest_source)])
        try:
            return verify_lock.verify_entry(self.spec, entry, offline=False)
        finally:
            sp.download_skill = original

    def test_short_sha_is_rejected_without_a_fetch(self):
        problems = verify_lock.verify_entry(self.spec, self.entry(commit="abc123"), offline=True)
        self.assertIn("not a full 40-character SHA", problems[0])

    def test_manifest_drift_is_reported(self):
        problems = verify_lock.verify_entry(self.spec, self.entry(ref="next"), offline=True)
        self.assertIn("ref drifted", problems[0])

    def test_an_override_added_to_the_manifest_alone_is_drift(self):
        spec = sp.SkillSpec(
            name="demo",
            repo="owner/repo",
            path="skills/demo",
            overrides={"snyk": sp.ScannerOverride(reason="r", max_risk="medium")},
        )
        problems = verify_lock.verify_entry(spec, self.entry(), offline=True)
        self.assertIn("overrides drifted", problems[0])

    def test_tree_sha_mismatch_is_caught(self):
        digest = sp.content_digest([("SKILL.md", b"x")])
        problems = self.verify(self.entry(contentDigest=digest), tree_sha="tree-2")
        self.assertEqual(len(problems), 1)
        self.assertIn("treeSha mismatch", problems[0])

    def test_content_tamper_is_caught(self):
        problems = self.verify(self.entry(contentDigest="sha256:notthis"))
        self.assertIn("contentDigest mismatch", problems[0])

    def test_matching_content_verifies_clean(self):
        digest = sp.content_digest([("SKILL.md", b"x")])
        self.assertEqual(self.verify(self.entry(contentDigest=digest)), [])


class ManifestLoading(unittest.TestCase):
    def test_scan_slug_defaults_to_repo_plus_leaf(self):
        spec = sp.SkillSpec(name="demo", repo="cursor/plugins", path="kit/skills/thermo")
        self.assertEqual(spec.scan_slug, "cursor/plugins/thermo")

    def test_explicit_slug_wins(self):
        spec = sp.SkillSpec(name="demo", repo="cursor/plugins", path="kit/skills/thermo", slug="a/b/c")
        self.assertEqual(spec.scan_slug, "a/b/c")

    def test_bad_max_risk_is_rejected(self):
        with self.assertRaises(sp.SkillPinError):
            sp.Policy.from_dict({"scanners": {"max_risk": "somewhat-dodgy"}})

    def test_repo_manifest_parses(self):
        pol, specs = sp.load_manifest()
        self.assertGreaterEqual(pol.min_age_days, 1)
        self.assertTrue(specs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
