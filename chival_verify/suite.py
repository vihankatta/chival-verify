"""
Local, private regression suite of customer-certified tasks (`chival certify`).

A certified task is exactly one gold_sample-style example (bug, fix, tests)
that has passed the same four-gate `verifier.runner.Verifier` used
internally for the shipped 6-task corpus -- there is no separate, weaker
certification path for user-submitted tasks. Certificates are plain JSON
files under a suite directory (default `.chival/suite/`), committable to git
like any other test fixture, so a team's suite is diffable, branchable, and
owned by them, not held on a server.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

DEFAULT_SUITE_DIR = ".chival/suite"

# The 6 categories the shipped starter corpus (experiment.tasks.mock_bank_tasks)
# covers -- the same product-facing taxonomy the landing page and README
# already describe. Coverage/suggestions are measured against this, not the
# much larger internal generator/taxonomy.py space, which was built for the
# dataset generator's combinatorial sampling, not as a customer-facing
# checklist -- showing someone "3/23 categories" on their first certify would
# be discouraging noise, not signal.
KNOWN_CATEGORIES = ["api", "async_concurrency", "backend", "database", "performance", "security"]

_DAY_SECONDS = 86400


def certificate_id(*, title: str, category: str, subtype: str, buggy_code: str,
                    solution_code: str, tests: str) -> str:
    """Content hash of everything that defines this task's identity -- editing
    any of these fields produces a different id, same discipline as the
    adapter-hash integrity check in docs/validation/sanity_check_report.md.
    """
    h = hashlib.sha256()
    for part in (title, category, subtype, buggy_code, solution_code, tests):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


def save_certificate(suite_dir: Path, *, title: str, category: str, subtype: str,
                      bug_type: str, buggy_code: str, solution_code: str, tests: str,
                      verification: dict) -> Path:
    suite_dir.mkdir(parents=True, exist_ok=True)
    cid = certificate_id(title=title, category=category, subtype=subtype,
                          buggy_code=buggy_code, solution_code=solution_code, tests=tests)
    cert = {
        "id": cid,
        "title": title,
        "category": category,
        "subtype": subtype,
        "bug_type": bug_type,
        "buggy_code": buggy_code,
        "solution_code": solution_code,
        "tests": tests,
        "verification": verification,
        "certified_at": time.time(),
    }
    dest = suite_dir / f"{cid}.json"
    dest.write_text(json.dumps(cert, indent=2), encoding="utf-8")
    return dest


def list_certificates(suite_dir: Path) -> list[dict]:
    if not suite_dir.exists():
        return []
    certs = []
    for f in sorted(suite_dir.glob("*.json")):
        try:
            certs.append(json.loads(f.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return certs


def coverage_summary(certs: list[dict]) -> dict:
    """category -> count. This is the "your suite now covers N bug classes"
    growth signal the design-partner flywheel is built around -- a number
    that only ever goes up as a team certifies more of its own real bugs."""
    counts: dict[str, int] = {}
    for c in certs:
        counts[c["category"]] = counts.get(c["category"], 0) + 1
    return counts


def task_score(cert: dict) -> int:
    return cert.get("verification", {}).get("verification_score", 0)


def _maturity_label(total: int, covered: int, known: int) -> str:
    """A plain, honest maturity read -- no badges, no streak-gamification,
    just where the suite actually stands. Bucketed on covered/known so it
    means the same thing regardless of how many *extra* categories (beyond
    the 6 starter ones) someone has also certified into."""
    if total == 0:
        return "empty -- not started yet"
    if covered >= known:
        return "full starter coverage -- every shipped category has at least one certified task"
    if covered >= known / 2:
        return "growing -- past the halfway point on starter category coverage"
    return "starting -- first certified tasks are in"


def next_recommended_category(certs: list[dict]) -> str | None:
    """One concrete suggestion: the first known category with zero coverage,
    in KNOWN_CATEGORIES order. Once every known category has >=1 task, there
    is nothing left to recommend from this fixed list -- deepening coverage
    or certifying real bugs outside it is then the user's own call, not a
    scripted suggestion (this function returns None, deliberately, rather
    than inventing busywork)."""
    covered = set(coverage_summary(certs))
    for cat in KNOWN_CATEGORIES:
        if cat not in covered:
            return cat
    return None


def suite_stats(certs: list[dict], *, now: float) -> dict:
    """Pure computation over a suite's certificates -- no I/O, so it's
    trivially testable and the CLI layer only has to format it. `now` is
    passed in (not `time.time()` called here) so tests are deterministic.
    """
    coverage = coverage_summary(certs)
    covered_categories = sorted(coverage)
    missing_categories = [c for c in KNOWN_CATEGORIES if c not in coverage]

    scores_by_category: dict[str, list[int]] = {}
    for c in certs:
        scores_by_category.setdefault(c["category"], []).append(task_score(c))
    avg_score_by_category = {
        cat: round(sum(scores) / len(scores), 1) for cat, scores in scores_by_category.items()
    }

    weakest_task = min(certs, key=task_score) if certs else None
    strongest_task = max(certs, key=task_score) if certs else None
    weakest_category = (
        min(avg_score_by_category.items(), key=lambda kv: kv[1]) if avg_score_by_category else None
    )

    certified_last_7d = sum(
        1 for c in certs if now - c.get("certified_at", 0) <= 7 * _DAY_SECONDS
    )

    return {
        "total": len(certs),
        "categories_covered": covered_categories,
        "categories_missing": missing_categories,
        "avg_score_overall": round(sum(task_score(c) for c in certs) / len(certs), 1) if certs else None,
        "avg_score_by_category": avg_score_by_category,
        "weakest_task": weakest_task,
        "strongest_task": strongest_task,
        "weakest_category": weakest_category,
        "certified_last_7d": certified_last_7d,
        "maturity": _maturity_label(len(certs), len(covered_categories), len(KNOWN_CATEGORIES)),
        "next_recommended_category": next_recommended_category(certs),
    }


def export_bundle(certs: list[dict], *, anonymize: bool) -> dict:
    """Bundle certificates for optional, manual, opt-in sharing -- the
    concrete, zero-infrastructure mechanic behind "grow the shared corpus":
    a plain JSON file a user can choose to email or attach to a PR, nothing
    auto-uploaded, no account, no server on our side required to receive it.

    `anonymize=True` strips free-text fields (title, and any embedded
    identifiers in the code/tests are the user's own responsibility to check
    before sharing -- this only removes what Chival itself added) so what's
    left is the reusable bug PATTERN (category, subtype, code, tests,
    verification metrics), not anything with the submitter's own naming or
    business-specific title attached.
    """
    bundled = []
    for c in certs:
        entry = dict(c)
        if anonymize:
            entry.pop("title", None)
            entry.pop("certified_at", None)
        bundled.append(entry)
    return {
        "chival_suite_export_version": 1,
        "anonymized": anonymize,
        "count": len(bundled),
        "tasks": bundled,
    }
