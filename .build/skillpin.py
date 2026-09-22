"""Shared helpers for resolving, gating and verifying pinned external skills."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "skills.yaml"
LOCK_PATH = REPO_ROOT / "skills.lock.json"

LOCKFILE_VERSION = 1

GITHUB_API = "https://api.github.com"
RAW_HOST = "https://raw.githubusercontent.com"
SKILLS_SH = "https://www.skills.sh"

RISK_ORDER = ["none", "low", "medium", "high", "critical"]
RISK_ALIASES = {"safe": "none", "clean": "none", "informational": "none", "info": "none"}
PASSING_VERDICTS = {"pass", "passed", "ok"}

SCRIPT_SUFFIXES = {
    ".sh",
    ".bash",
    ".zsh",
    ".ps1",
    ".psm1",
    ".bat",
    ".cmd",
    ".py",
    ".rb",
    ".js",
    ".cjs",
    ".mjs",
    ".ts",
    ".pl",
}

PATTERN_CATEGORIES = {
    "egress": {
        "pipe-to-shell": r"(?:curl|wget)[^\n|]*\|\s*(?:sudo\s+)?(?:ba)?sh",
        "curl": r"\bcurl\b",
        "wget": r"\bwget\b",
        "invoke-webrequest": r"\bInvoke-(?:WebRequest|RestMethod)\b",
        "netcat": r"\bnc\s+-",
    },
    "access": {
        "ssh-keys": r"\.ssh/(?:id_[a-z0-9]+|authorized_keys)",
        "aws-credentials": r"\.aws/credentials",
        "dotenv-read": r"(?:cat|Get-Content|type)\s+[^\n]*\.env\b",
        "token-env-vars": r"\b(?:GITHUB_TOKEN|GH_TOKEN|ANTHROPIC_API_KEY|OPENAI_API_KEY|NPM_TOKEN|AWS_SECRET_ACCESS_KEY)\b",
        "base64-decode": r"base64\s+(?:-d|--decode)|FromBase64String",
        "eval": r"\beval\s*[\(\"'$]",
        "remote-exec": r"\bIEX\b|\bInvoke-Expression\b",
    },
}

CAPABILITY_KEYS = ("allowedTools", "scripts", *PATTERN_CATEGORIES)


class SkillPinError(RuntimeError):
    pass


@dataclass
class Policy:
    min_age_days: int = 30
    required_scanners: list[str] = field(default_factory=list)
    max_risk: str = "low"
    allow_missing_report: bool = False
    block_on_new_capabilities: bool = True

    @classmethod
    def from_dict(cls, raw: dict) -> "Policy":
        scanners = raw.get("scanners") or {}
        capabilities = raw.get("capabilities") or {}
        max_risk = str(scanners.get("max_risk", "low")).lower()
        if max_risk not in RISK_ORDER:
            raise SkillPinError(
                f"policy.scanners.max_risk must be one of {RISK_ORDER}, got {max_risk!r}"
            )
        return cls(
            min_age_days=int(raw.get("min_age_days", 30)),
            required_scanners=[str(s) for s in scanners.get("required", [])],
            max_risk=max_risk,
            allow_missing_report=bool(scanners.get("allow_missing_report", False)),
            block_on_new_capabilities=bool(capabilities.get("block_on_new", True)),
        )


@dataclass
class ScannerOverride:
    """A per-skill relaxation of one scanner's verdict or risk ceiling."""

    reason: str
    max_risk: str | None = None
    verdicts: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, scanner: str, raw: object) -> "ScannerOverride":
        if not isinstance(raw, dict):
            raise SkillPinError(f"override for {scanner!r} must be a mapping, got {raw!r}")
        unknown = sorted(set(raw) - {"reason", "max_risk", "verdicts"})
        if unknown:
            raise SkillPinError(f"override for {scanner!r} has unknown keys {unknown}")

        reason = str(raw.get("reason") or "").strip()
        if not reason:
            raise SkillPinError(f"override for {scanner!r} needs a non-empty reason")

        max_risk = raw.get("max_risk")
        if max_risk is not None:
            max_risk = str(max_risk).lower()
            if max_risk not in RISK_ORDER:
                raise SkillPinError(
                    f"override for {scanner!r}: max_risk must be one of {RISK_ORDER}, got {max_risk!r}"
                )

        raw_verdicts = raw.get("verdicts") or []
        if isinstance(raw_verdicts, str):
            raw_verdicts = [raw_verdicts]
        if not isinstance(raw_verdicts, list):
            raise SkillPinError(f"override for {scanner!r}: verdicts must be a list")
        verdicts = sorted({str(v).strip().lower() for v in raw_verdicts if str(v).strip()})

        if max_risk is None and not verdicts:
            raise SkillPinError(
                f"override for {scanner!r} relaxes nothing, set max_risk and/or verdicts"
            )
        return cls(reason=reason, max_risk=max_risk, verdicts=verdicts)

    def to_dict(self) -> dict:
        record: dict = {"reason": self.reason}
        if self.max_risk is not None:
            record["max_risk"] = self.max_risk
        if self.verdicts:
            record["verdicts"] = list(self.verdicts)
        return record


@dataclass
class SkillSpec:
    name: str
    repo: str
    path: str
    ref: str = "main"
    slug: str | None = None
    overrides: dict[str, ScannerOverride] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.repo}/{self.path}"

    @property
    def scan_slug(self) -> str:
        if self.slug:
            return self.slug
        leaf = self.path.rstrip("/").split("/")[-1]
        return f"{self.repo}/{leaf}"

    @property
    def override_record(self) -> dict:
        return {name: o.to_dict() for name, o in sorted(self.overrides.items())}


def parse_overrides(raw: object, policy: Policy, context: str) -> dict[str, ScannerOverride]:
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise SkillPinError(f"{context}: overrides must be a mapping of scanner to relaxation")
    parsed: dict[str, ScannerOverride] = {}
    for scanner, body in raw.items():
        scanner = str(scanner)
        if scanner not in policy.required_scanners:
            raise SkillPinError(
                f"{context}: override names {scanner!r}, which is not in "
                f"policy.scanners.required {policy.required_scanners}"
            )
        parsed[scanner] = ScannerOverride.from_dict(scanner, body)
    return parsed


def load_manifest(path: Path = MANIFEST_PATH) -> tuple[Policy, list[SkillSpec]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    policy = Policy.from_dict(raw.get("policy") or {})
    specs: list[SkillSpec] = []
    for entry in raw.get("skills") or []:
        missing = [k for k in ("name", "repo", "path") if not entry.get(k)]
        if missing:
            raise SkillPinError(f"skill entry missing required keys {missing}: {entry!r}")
        specs.append(
            SkillSpec(
                name=entry["name"],
                repo=entry["repo"],
                path=entry["path"].strip("/"),
                ref=entry.get("ref", "main"),
                slug=entry.get("slug"),
                overrides=parse_overrides(
                    entry.get("overrides"), policy, f"skill {entry['name']!r}"
                ),
            )
        )
    keys = [s.key for s in specs]
    dupes = {k for k in keys if keys.count(k) > 1}
    if dupes:
        raise SkillPinError(f"duplicate skill entries in manifest: {sorted(dupes)}")
    return policy, specs


def load_lock(path: Path = LOCK_PATH) -> dict:
    if not path.exists():
        return {"lockfileVersion": LOCKFILE_VERSION, "skills": {}, "held": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("lockfileVersion") != LOCKFILE_VERSION:
        raise SkillPinError(
            f"unsupported lockfileVersion {data.get('lockfileVersion')!r}, expected {LOCKFILE_VERSION}"
        )
    data.setdefault("skills", {})
    data.setdefault("held", {})
    return data


def write_lock(data: dict, path: Path = LOCK_PATH) -> None:
    data["lockfileVersion"] = LOCKFILE_VERSION
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _request(url: str, accept: str = "application/vnd.github+json") -> bytes:
    headers = {
        "Accept": accept,
        "User-Agent": "ai-skills-pinner",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token and url.startswith((GITHUB_API, RAW_HOST)):
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def github_json(path: str) -> object:
    return json.loads(_request(f"{GITHUB_API}{path}"))


def newest_eligible_commit(spec: SkillSpec, min_age_days: int) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=min_age_days)
    url = f"/repos/{spec.repo}/commits?sha={spec.ref}&path={spec.path}&per_page=100"
    commits = github_json(url)
    if not isinstance(commits, list) or not commits:
        raise SkillPinError(f"{spec.key}: no commits found touching path on ref {spec.ref!r}")
    for commit in commits:
        date_raw = commit["commit"]["committer"]["date"]
        when = datetime.fromisoformat(date_raw.replace("Z", "+00:00"))
        if when <= cutoff:
            return {"sha": commit["sha"], "date": date_raw, "age_days": (datetime.now(timezone.utc) - when).days}
    oldest = commits[-1]["commit"]["committer"]["date"]
    raise SkillPinError(
        f"{spec.key}: no commit older than {min_age_days} days in the last 100 touching this path "
        f"(oldest examined {oldest})"
    )


def fetch_skill_tree(spec: SkillSpec, commit: str) -> tuple[str, list[dict]]:
    tree = github_json(f"/repos/{spec.repo}/git/trees/{commit}:{spec.path}?recursive=1")
    if not isinstance(tree, dict) or "tree" not in tree:
        raise SkillPinError(f"{spec.key}: could not read tree at {commit}:{spec.path}")
    files = [n for n in tree["tree"] if n.get("type") == "blob"]
    if not files:
        raise SkillPinError(f"{spec.key}: skill directory is empty at {commit}")
    return tree["sha"], sorted(files, key=lambda n: n["path"])


def fetch_file(spec: SkillSpec, commit: str, rel_path: str) -> bytes:
    url = f"{RAW_HOST}/{spec.repo}/{commit}/{spec.path}/{rel_path}"
    return _request(url, accept="text/plain")


def content_digest(files: list[tuple[str, bytes]]) -> str:
    h = hashlib.sha256()
    for rel_path, blob in sorted(files):
        h.update(rel_path.encode("utf-8"))
        h.update(b"\0")
        h.update(hashlib.sha256(blob).digest())
    return f"sha256:{h.hexdigest()}"


def parse_frontmatter(text: str) -> dict:
    match = re.match(r"^---\r?\n(.*?)\r?\n---\s*?\r?\n", text, re.DOTALL)
    if not match:
        return {}
    try:
        parsed = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _as_tool_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [t.strip() for t in value.split(",") if t.strip()]
    if isinstance(value, list):
        return [str(t).strip() for t in value if str(t).strip()]
    return []


def extract_capabilities(files: list[tuple[str, bytes]]) -> dict:
    allowed_tools: list[str] = []
    scripts: list[str] = []
    matches: dict[str, dict[str, list[str]]] = {c: {} for c in PATTERN_CATEGORIES}

    for rel_path, blob in files:
        suffix = Path(rel_path).suffix.lower()
        if suffix in SCRIPT_SUFFIXES:
            scripts.append(rel_path)
        try:
            text = blob.decode("utf-8")
        except UnicodeDecodeError:
            matches["access"].setdefault("binary-file", []).append(rel_path)
            continue
        if Path(rel_path).name.lower() == "skill.md":
            fm = parse_frontmatter(text)
            for key in ("allowed-tools", "allowed_tools", "allowedTools"):
                allowed_tools.extend(_as_tool_list(fm.get(key)))
        for category, patterns in PATTERN_CATEGORIES.items():
            for label, pattern in patterns.items():
                if re.search(pattern, text):
                    matches[category].setdefault(label, []).append(rel_path)

    capabilities = {
        "allowedTools": sorted(set(allowed_tools)),
        "scripts": sorted(scripts),
    }
    for category, found in matches.items():
        capabilities[category] = {k: sorted(v) for k, v in sorted(found.items())}
    return capabilities


def new_capabilities(previous: dict | None, candidate: dict) -> list[str]:
    if not previous:
        return []
    added: list[str] = []
    for tool in candidate.get("allowedTools", []):
        if tool not in (previous.get("allowedTools") or []):
            added.append(f"new allowed-tool: {tool}")
    for script in candidate.get("scripts", []):
        if script not in (previous.get("scripts") or []):
            added.append(f"new script file: {script}")
    for category in PATTERN_CATEGORIES:
        prev_matches = previous.get(category) or {}
        for label, paths in (candidate.get(category) or {}).items():
            prev_paths = prev_matches.get(label) or []
            for path in paths:
                if path not in prev_paths:
                    added.append(f"new {category} pattern {label} in {path}")
    return added


def fetch_scan_report(slug: str, scanner: str) -> dict:
    url = f"{SKILLS_SH}/{slug}/security/{scanner}"
    try:
        html = _request(url, accept="text/html").decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return {"status": "missing", "httpStatus": exc.code, "url": url}
    except urllib.error.URLError as exc:
        return {"status": "error", "detail": str(exc.reason), "url": url}

    verdict = None
    badge = re.search(
        r'rounded\s+bg-[a-z]+-500/10\s+text-[a-z]+-500">\s*([A-Za-z][A-Za-z ]{0,18}?)\s*</span>',
        html,
    )
    if badge:
        verdict = badge.group(1).strip().lower()

    risk = None
    match = re.search(r"Risk Level:\s*(?:<!--\s*-->)?\s*([A-Za-z]+)", html)
    if not match:
        match = re.search(r">Risk Level</dt>.*?<dd[^>]*>\s*([A-Za-z]+)\s*<", html, re.DOTALL)
    if match:
        raw_risk = match.group(1).lower()
        risk = RISK_ALIASES.get(raw_risk, raw_risk)

    analysed = None
    date_match = re.search(
        r">Analyzed(?: At)?</dt>.*?<dd[^>]*>\s*([^<]+?)\s*<", html, re.DOTALL
    )
    if date_match:
        analysed = date_match.group(1)

    if verdict is None and risk is None:
        return {"status": "unparsed", "url": url}

    report = {"status": "ok", "url": url}
    if verdict is not None:
        report["verdict"] = verdict
    if risk is not None:
        report["risk"] = risk
    if analysed is not None:
        report["analyzed"] = analysed
    return report


def evaluate_scans(
    slug: str, policy: Policy, overrides: dict[str, ScannerOverride] | None = None
) -> tuple[dict, list[str]]:
    reports: dict[str, dict] = {}
    blockers: list[str] = []
    overrides = overrides or {}

    for scanner in policy.required_scanners:
        override = overrides.get(scanner)
        max_risk = policy.max_risk
        accepted = PASSING_VERDICTS
        if override:
            max_risk = override.max_risk or max_risk
            accepted = PASSING_VERDICTS | set(override.verdicts)
        limit = RISK_ORDER.index(max_risk)

        report = fetch_scan_report(slug, scanner)
        if override:
            report = {**report, "overridden": override.to_dict()}
        reports[scanner] = report
        if report["status"] != "ok":
            if not policy.allow_missing_report:
                blockers.append(f"{scanner}: no usable report ({report['status']})")
            continue

        verdict = report.get("verdict")
        if verdict is not None and verdict not in accepted:
            blockers.append(f"{scanner}: verdict is {verdict!r}, not a pass")

        risk = report.get("risk")
        if risk is None:
            if verdict is None:
                blockers.append(f"{scanner}: report carried neither a verdict nor a risk level")
        elif risk not in RISK_ORDER:
            blockers.append(f"{scanner}: unrecognised risk level {risk!r}")
        elif RISK_ORDER.index(risk) > limit:
            blockers.append(f"{scanner}: risk {risk} exceeds max_risk {max_risk}")

    return reports, blockers


def download_skill(spec: SkillSpec, commit: str) -> tuple[str, list[tuple[str, bytes]]]:
    tree_sha, nodes = fetch_skill_tree(spec, commit)
    files = [(node["path"], fetch_file(spec, commit, node["path"])) for node in nodes]
    return tree_sha, files


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)
