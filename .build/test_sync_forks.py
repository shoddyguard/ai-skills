"""Offline tests for fork manifest parsing and the upstream change report."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import skillpin as sp
import sync_forks as sf


MANIFEST = """
policy:
  min_age_days: 30
  scanners:
    required: [snyk]
    max_risk: low

forks:
  - repo: owner/upstream
    ref: main
    dir: forks/owner
    strip: skills/
    extra_files:
      - skills/engineering/README.md
    skills:
      - path: skills/engineering/alpha
        patched: true
      - path: skills/engineering/beta
      - path: skills/engineering/setup-theirs
        patched: true
        rename: setup-ours
"""


def policy(**overrides) -> sp.Policy:
    base = {"min_age_days": 30, "scanners": {"required": ["snyk"], "max_risk": "low"},
            "capabilities": {"block_on_new": True}}
    base.update(overrides)
    return sp.Policy.from_dict(base)


class ForkManifest(unittest.TestCase):
    def load(self, text: str = MANIFEST) -> list[sp.ForkSource]:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "skills.yaml"
            manifest.write_text(text, encoding="utf-8")
            return sp.load_forks(manifest, root)

    def test_local_path_strips_the_upstream_prefix(self):
        source = self.load()[0]
        alpha = source.skills[0]
        self.assertEqual(alpha.local_dir.parts[-4:], ("forks", "owner", "engineering", "alpha"))

    def test_rename_changes_the_directory_but_not_the_upstream_path(self):
        renamed = self.load()[0].skills[2]
        self.assertEqual(renamed.spec.path, "skills/engineering/setup-theirs")
        self.assertTrue(str(renamed.local_dir).endswith("forks/owner/engineering/setup-ours"))
        self.assertEqual(renamed.spec.name, "setup-ours")

    def test_patched_defaults_to_false(self):
        self.assertFalse(self.load()[0].skills[1].patched)
        self.assertTrue(self.load()[0].skills[0].patched)

    def test_scan_slug_follows_the_upstream_leaf_not_the_rename(self):
        self.assertEqual(self.load()[0].skills[2].spec.scan_slug, "owner/upstream/setup-theirs")

    def test_extra_files_are_carried(self):
        self.assertEqual(self.load()[0].extra_files, ["skills/engineering/README.md"])

    def test_duplicate_skill_paths_are_rejected(self):
        text = MANIFEST + "      - path: skills/engineering/alpha\n"
        with self.assertRaises(sp.SkillPinError):
            self.load(text)

    def test_a_skill_without_a_path_is_rejected(self):
        text = MANIFEST + "      - patched: true\n"
        with self.assertRaises(sp.SkillPinError):
            self.load(text)

    def test_a_manifest_with_no_forks_is_empty_not_an_error(self):
        self.assertEqual(self.load("policy:\n  min_age_days: 30\n"), [])

    def test_repo_manifest_parses(self):
        sources = sp.load_forks()
        self.assertTrue(sources)
        self.assertTrue(all(fork.local_dir.is_dir() for s in sources for fork in s.skills))


class ChangeClassification(unittest.TestCase):
    def test_additions_removals_and_edits_are_separated(self):
        base = {"SKILL.md": b"one", "gone.md": b"two"}
        candidate = {"SKILL.md": b"one changed", "new.md": b"three"}
        self.assertEqual(
            sf.classify(base, candidate),
            {"added": ["new.md"], "removed": ["gone.md"], "modified": ["SKILL.md"]},
        )

    def test_identical_trees_produce_nothing(self):
        files = {"SKILL.md": b"same"}
        self.assertEqual(
            sf.classify(files, dict(files)), {"added": [], "removed": [], "modified": []}
        )


class Resolution(unittest.TestCase):
    base_sha = "a" * 40
    candidate_sha = "b" * 40

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.local_dir = Path(self.tmp.name) / "alpha"
        self.local_dir.mkdir()
        self.addCleanup(self.tmp.cleanup)
        self.originals = (sp.newest_eligible_commit, sp.download_skill, sp.evaluate_scans)

    def tearDown(self):
        sp.newest_eligible_commit, sp.download_skill, sp.evaluate_scans = self.originals

    def fork(self, patched: bool = True) -> sp.ForkSkill:
        return sp.ForkSkill(
            spec=sp.SkillSpec(name="alpha", repo="owner/upstream", path="skills/alpha"),
            patched=patched,
            local_dir=self.local_dir,
        )

    def write_local(self, files: dict[str, bytes]) -> None:
        for name, blob in files.items():
            (self.local_dir / name).write_bytes(blob)

    def stub(self, candidate: dict, trees: dict[str, dict[str, bytes]], blockers=None):
        sp.newest_eligible_commit = lambda spec, min_age: candidate
        sp.download_skill = lambda spec, commit: ("tree", sorted(trees[commit].items()))
        sp.evaluate_scans = lambda slug, pol, overrides=None: ({}, list(blockers or []))

    def commit(self, sha: str, date: str) -> dict:
        return {"sha": sha, "date": date, "age_days": 40}

    def record(self, date: str = "2026-01-01T00:00:00Z") -> dict:
        return {"skills": {}, "baseCommit": self.base_sha, "baseCommitDate": date}

    def test_same_commit_is_current(self):
        self.stub(self.commit(self.base_sha, "2026-01-01T00:00:00Z"), {})
        result = sf.resolve(self.fork(), policy(), self.record())
        self.assertEqual(result["status"], "current")

    def test_a_base_newer_than_the_gated_candidate_reports_ahead(self):
        self.stub(self.commit(self.candidate_sha, "2026-01-01T00:00:00Z"), {})
        result = sf.resolve(self.fork(), policy(), self.record(date="2026-06-01T00:00:00Z"))
        self.assertEqual(result["status"], "ahead")

    def test_a_commit_that_does_not_touch_the_content_is_current(self):
        files = {"SKILL.md": b"same"}
        self.stub(
            self.commit(self.candidate_sha, "2026-06-01T00:00:00Z"),
            {self.base_sha: files, self.candidate_sha: dict(files)},
        )
        result = sf.resolve(self.fork(), policy(), self.record())
        self.assertEqual(result["status"], "current")
        self.assertIn("identical", result["note"])

    def test_an_upstream_edit_to_a_file_we_patched_is_flagged(self):
        self.write_local({"SKILL.md": b"ours, patched"})
        self.stub(
            self.commit(self.candidate_sha, "2026-06-01T00:00:00Z"),
            {self.base_sha: {"SKILL.md": b"theirs"}, self.candidate_sha: {"SKILL.md": b"theirs, moved on"}},
        )
        result = sf.resolve(self.fork(), policy(), self.record())
        self.assertEqual(result["status"], "available")
        self.assertTrue(result["touchesPatch"])
        self.assertFalse(result["localMatchesBase"])
        self.assertEqual(result["changes"]["modified"], ["SKILL.md"])

    def test_an_upstream_edit_to_an_untouched_file_is_not_flagged(self):
        self.write_local({"SKILL.md": b"theirs", "OTHER.md": b"ours, patched"})
        self.stub(
            self.commit(self.candidate_sha, "2026-06-01T00:00:00Z"),
            {
                self.base_sha: {"SKILL.md": b"theirs", "OTHER.md": b"theirs"},
                self.candidate_sha: {"SKILL.md": b"theirs, moved on", "OTHER.md": b"theirs"},
            },
        )
        result = sf.resolve(self.fork(), policy(), self.record())
        self.assertFalse(result["touchesPatch"])

    def test_a_failing_scanner_marks_the_update_blocked(self):
        self.write_local({"SKILL.md": b"theirs"})
        self.stub(
            self.commit(self.candidate_sha, "2026-06-01T00:00:00Z"),
            {self.base_sha: {"SKILL.md": b"theirs"}, self.candidate_sha: {"SKILL.md": b"new"}},
            blockers=["snyk: verdict fail"],
        )
        result = sf.resolve(self.fork(), policy(), self.record())
        self.assertEqual(result["status"], "blocked")

    def test_a_new_capability_upstream_blocks_the_update(self):
        self.write_local({"SKILL.md": b"theirs"})
        self.stub(
            self.commit(self.candidate_sha, "2026-06-01T00:00:00Z"),
            {
                self.base_sha: {"SKILL.md": b"theirs"},
                self.candidate_sha: {"SKILL.md": b"now we curl https://example.com"},
            },
        )
        result = sf.resolve(self.fork(), policy(), self.record())
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(any("curl" in b for b in result["blockers"]))

    def test_a_missing_base_commit_is_an_error(self):
        self.stub(self.commit(self.candidate_sha, "2026-06-01T00:00:00Z"), {})
        with self.assertRaises(sp.SkillPinError):
            sf.resolve(self.fork(), policy(), {"skills": {}})


class OfflineCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fork_dir = Path(self.tmp.name) / "forks" / "owner"
        (self.fork_dir / "engineering" / "alpha").mkdir(parents=True)
        (self.fork_dir / "engineering" / "alpha" / "SKILL.md").write_text("hello", encoding="utf-8")

    def source(self, patched: bool = False) -> sp.ForkSource:
        source = sp.ForkSource(repo="owner/upstream", ref="main", dir=self.fork_dir, strip="skills/")
        source.skills.append(
            sp.ForkSkill(
                spec=sp.SkillSpec(name="alpha", repo="owner/upstream", path="skills/engineering/alpha"),
                patched=patched,
                local_dir=self.fork_dir / "engineering" / "alpha",
            )
        )
        return source

    def lock(self, **entry) -> dict:
        base = {"baseCommit": "a" * 40, "patched": False}
        base.update(entry)
        return {"forks": {"owner/upstream": {"skills": {"skills/engineering/alpha": base}}}}

    def digest(self) -> str:
        return sp.content_digest([("SKILL.md", b"hello")])

    def test_matching_content_and_flags_pass(self):
        self.assertEqual(sf.check([self.source()], self.lock(localDigest=self.digest())), [])

    def test_edited_content_is_reported(self):
        problems = sf.check([self.source()], self.lock(localDigest="sha256:something-else"))
        self.assertEqual(len(problems), 1)
        self.assertIn("changed since it was recorded", problems[0])

    def test_a_patched_flag_that_disagrees_with_the_manifest_is_reported(self):
        problems = sf.check([self.source(patched=True)], self.lock(localDigest=self.digest()))
        self.assertIn("manifest says patched=True", problems[0])

    def test_an_undeclared_forked_skill_is_reported(self):
        stray = self.fork_dir / "engineering" / "stray"
        stray.mkdir()
        (stray / "SKILL.md").write_text("surprise", encoding="utf-8")
        problems = sf.check([self.source()], self.lock(localDigest=self.digest()))
        self.assertTrue(any("not declared" in p for p in problems))

    def test_a_declared_skill_missing_from_disk_is_reported(self):
        source = self.source()
        source.skills[0].local_dir = self.fork_dir / "engineering" / "ghost"
        problems = sf.check([source], self.lock(localDigest=self.digest()))
        self.assertTrue(any("missing" in p for p in problems))


if __name__ == "__main__":
    unittest.main(verbosity=2)
