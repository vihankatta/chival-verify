"""
The `chival` command-line interface (chival-verify package).

Fully offline, no network calls anywhere in this file:

    chival doctor                 # is my environment ready? (runs a real eval)
    chival grade -s sol.py -t test_sol.py   # grade a submission -> reward
    chival certify --bug bug.py --fix fix.py --tests tests.py \\
        --category security --subtype access_control
    chival suite list
    chival suite stats     # coverage, quality, growth, next-recommended category
    chival suite export --anonymize   # bundle for optional sharing -- nothing auto-uploaded
    chival version

This is the standalone extraction of Chival's four-gate verification engine.
The full Chival platform (model connections, live benchmark runs, regression
history across runs) is a separate, private product at https://chival.ai --
everything in this file works completely on its own.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Keep stdout UTF-8 tolerant on Windows consoles.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

_SMOKE_SOLUTION = "def f():\n    return 1\n"
_SMOKE_TESTS = "from solution import f\n\ndef test_f():\n    assert f() == 1\n"

# A tiny, illustrative task for `chival grade --example` — a zero-setup first
# successful grade (no files required).
_EXAMPLE_SOLUTION = "def add(a, b):\n    return a + b\n"
_EXAMPLE_TESTS = (
    "from solution import add\n\n"
    "def test_add():\n    assert add(2, 3) == 5\n\n"
    "def test_zero():\n    assert add(0, 0) == 0\n"
)

_FIRST_GRADE_HINT = "Try it now (no files needed): chival grade --example"

# Kept as a plain string (not chival_verify.suite.DEFAULT_SUITE_DIR) so
# argparse's default is available without importing chival_verify.suite at
# parser-build time -- every other dependency here is imported lazily inside
# its cmd_* function for the same fast-startup reason.
_DEFAULT_SUITE_DIR = ".chival/suite"


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def cmd_version(_args: argparse.Namespace) -> int:
    import chival_verify
    print(f"chival-verify {chival_verify.__version__}")
    return 0


def _try_smoke(sandbox, timeout: float) -> tuple[bool, str]:
    """Run a trivial evaluation; return (ok, detail)."""
    from chival_verify.grader import grade_submission
    try:
        outcome = grade_submission(_SMOKE_SOLUTION, _SMOKE_TESTS, timeout=timeout, sandbox=sandbox)
    except Exception as exc:  # noqa: BLE001 - surface anything actionable (e.g. image lacks pytest)
        return False, str(exc).splitlines()[0]
    if outcome.verified:
        return True, ""
    return False, f"ran but the smoke test did not pass: {outcome.signals}"


_DOCKER_HINT = (
    "  (optional) for isolated Docker grading, build the image once:\n"
    "    docker build -f Dockerfile.sandbox -t chival-verify-sandbox .\n"
    "    set CHIVAL_IMAGE=chival-verify-sandbox   (PowerShell: $env:CHIVAL_IMAGE=...)"
)


def cmd_doctor(args: argparse.Namespace) -> int:
    import platform
    from chival_verify.verifier.sandbox import docker_available, get_sandbox

    print("chival doctor")
    print(f"  python:          {platform.python_version()} ({sys.platform})")
    print(f"  docker daemon:   {'available' if docker_available() else 'not reachable'}")
    sandbox = get_sandbox(args.sandbox)
    print(f"  sandbox backend: {sandbox.backend}")
    print("  running a smoke evaluation...")

    ok, detail = _try_smoke(sandbox, args.timeout)
    if ok:
        print("  [OK] sandbox executed a test and returned a deterministic reward.")
        print(f"\nchival-verify is ready. {_FIRST_GRADE_HINT}")
        return 0

    # The chosen backend didn't work. Before declaring failure, fall back to the
    # local sandbox — a fresh machine often has Docker running but no image built,
    # and the tool works fine via local. A clean install should never red-fail
    # when grading actually works.
    print(f"  [warn] {sandbox.backend} backend not ready: {detail}")
    if sandbox.backend != "local":
        print("  trying the local sandbox instead...")
        ok2, detail2 = _try_smoke(get_sandbox("local"), args.timeout)
        if ok2:
            print("  [OK] local sandbox works — chival-verify is ready.")
            print(_DOCKER_HINT)
            print(f"\nReady (local backend). {_FIRST_GRADE_HINT} --sandbox local")
            # If the user explicitly demanded docker, their intent still failed.
            return 1 if args.sandbox == "docker" else 0
        print(f"  [FAIL] local sandbox also failed: {detail2}")
        return 1

    print(f"  [FAIL] {detail}")
    return 1


# Only genuinely count-like metric keys get whole-number int display.
# Deliberately an allowlist, not "any whole float": pass_rate/reward/
# bug_detection_rate are fractions in [0,1] where a perfect 1.0 must stay
# "1.0", not become "1" and read like a count instead of 100%.
_INT_DISPLAY_METRICS = {"tests_total", "tests_passed", "tests_failed", "tests_killed", "verification_score"}


def _humanize_metrics(metrics: dict) -> dict:
    """Display-only: `chival_verify.evaluation.Outcome.metrics` is
    deliberately typed `dict[str, float]` (a real, documented contract other
    domains and RL/eval exporters rely on) so counts like tests_total are
    stored as e.g. 2.0. That's correct for the data model but reads as a typo
    in a terminal ("why is a test count a float?"); this only reformats
    whole-number COUNT fields as ints for the printed copy, it does not touch
    the underlying Outcome type or rate/score fields."""
    out = {}
    for k, v in metrics.items():
        if k in _INT_DISPLAY_METRICS and isinstance(v, float) and v.is_integer():
            out[k] = int(v)
        else:
            out[k] = v
    return out


def cmd_grade(args: argparse.Namespace) -> int:
    from chival_verify.grader import grade_submission
    from chival_verify.verifier.sandbox import get_sandbox

    # Resolve the submission + tests: built-in example, or user-provided files.
    if args.example:
        submission, tests = _EXAMPLE_SOLUTION, _EXAMPLE_TESTS
        print("Running the built-in example (a one-line `add` bug fix)...\n")
    else:
        if not args.submission or not args.tests:
            print("error: provide -s/--submission and -t/--tests, "
                  "or run `chival grade --example` for a zero-setup demo.")
            return 2
        try:
            submission = _read(args.submission)
            tests = _read(args.tests)
        except FileNotFoundError as exc:
            print(f"error: file not found: {exc.filename}")
            return 2

    # Grade, falling back to the local sandbox if the chosen backend isn't ready
    # (so a first grade succeeds even when Docker is up but unconfigured).
    sandbox = get_sandbox(args.sandbox)
    try:
        outcome = grade_submission(submission, tests, timeout=args.timeout, sandbox=sandbox)
    except Exception as exc:  # noqa: BLE001
        if sandbox.backend != "local":
            print(f"[warn] {sandbox.backend} backend not ready "
                  f"({str(exc).splitlines()[0]}); using the local sandbox.\n")
            outcome = grade_submission(submission, tests, timeout=args.timeout,
                                       sandbox=get_sandbox("local"))
        else:
            print(f"error: sandbox could not run: {exc}")
            return 1

    out = outcome.to_dict()
    if not args.verbose:
        # Compact, friendly summary; full detail with --verbose.
        out = {
            "verified": out["verified"],
            "reward": out["reward"],
            "metrics": out["metrics"],
            "failed_tests": out["signals"].get("failed_tests", []),
            "verifier": out["verifier"],
        }
    out["metrics"] = _humanize_metrics(out["metrics"])
    print(json.dumps(out, indent=2))
    if args.example:
        print("\nThat's the whole flow. Now grade your own:")
        print("  chival grade -s your_solution.py -t your_tests.py")
    return 0 if outcome.verified else 1


# error code -> which of the four gates it corresponds to, for a clean
# certify failure message (see chival_verify/verifier/runner.py's
# Verifier.verify() -- the gate order below matches its actual check order).
_GATE_FAILURE_LABELS = {
    "timeout": "Gate 1 (fix passes tests) -- the fix timed out",
    "solution_failed": "Gate 1 (fix passes tests) -- the fix does not pass its own tests",
    "fake_bug": "Gate 2 (behavioral diff) -- bug and fix aren't behaviorally different "
                "(cosmetic or rename-only change)",
    "bug_not_caught": "Gate 3 (bug is caught) -- no test distinguishes the bug from the fix",
    "weak_tests": "Gate 4 (test suite strength) -- the test suite is too weak to be meaningful signal",
}


def cmd_certify(args: argparse.Namespace) -> int:
    """Certify a user's own (bug, fix, tests) trio through the same four
    gates, and save it into a local, private, git-committable regression
    suite."""
    from chival_verify.models import CodingExample
    from chival_verify.verifier.runner import Verifier
    from chival_verify.verifier.sandbox import get_sandbox
    from chival_verify import suite

    try:
        buggy_code = _read(args.bug)
        solution_code = _read(args.fix)
        tests = _read(args.tests)
    except FileNotFoundError as exc:
        print(f"error: file not found: {exc.filename}")
        return 2

    title = args.title or f"{args.category}/{args.subtype} regression"
    try:
        example = CodingExample(
            title=title, buggy_code=buggy_code, solution_code=solution_code, tests=tests,
            category=args.category, subtype=args.subtype, bug_type=args.bug_type,
        )
    except Exception as exc:  # pydantic ValidationError -- e.g. title too short
        print(f"error: {exc}")
        return 2

    print(f"certifying {title!r} ({args.category}/{args.subtype})...")
    sandbox = get_sandbox(args.sandbox)
    result = Verifier(sandbox=sandbox, timeout=args.timeout).verify(example)

    if not result.verified:
        label = _GATE_FAILURE_LABELS.get(result.error, result.error)
        print(f"\nNOT CERTIFIED -- {label}")
        for issue in result.test_quality_issues:
            print(f"  - {issue}")
        if result.observed_failure:
            print(f"\n  observed failure:\n{result.observed_failure}")
        return 1

    print("  gate 1  fix passes the real test suite             PASS")
    print("  gate 2  fix and bug differ in real behavior         PASS")
    print(f"  gate 3  bug is genuinely caught "
          f"({result.tests_killed}/{result.tests_total} tests kill it)      PASS")
    print("  gate 4  test suite isn't trivially weak              PASS")

    suite_dir = Path(args.suite_dir)
    dest = suite.save_certificate(
        suite_dir, title=title, category=args.category, subtype=args.subtype,
        bug_type=args.bug_type, buggy_code=buggy_code, solution_code=solution_code,
        tests=tests, verification=result.to_dict(),
    )
    certs = suite.list_certificates(suite_dir)
    coverage = suite.coverage_summary(certs)
    print(f"\nCERTIFIED  (score {result.verification_score}/100)")
    print(f"  saved: {dest}")
    print(f"\nyour local suite now has {len(certs)} certified task(s) across "
          f"{len(coverage)} categor{'y' if len(coverage) == 1 else 'ies'}: "
          f"{', '.join(f'{k}={v}' for k, v in sorted(coverage.items()))}")
    print(f"  chival suite list --suite-dir {suite_dir}")
    return 0


def cmd_suite_list(args: argparse.Namespace) -> int:
    from chival_verify import suite

    suite_dir = Path(args.suite_dir)
    certs = suite.list_certificates(suite_dir)
    if not certs:
        print(f"no certified tasks yet in {suite_dir}.")
        print("  chival certify --bug bug.py --fix fix.py --tests tests.py "
              "--category security --subtype access_control")
        return 0

    coverage = suite.coverage_summary(certs)
    print(f"{len(certs)} certified task(s) across "
          f"{len(coverage)} categor{'y' if len(coverage) == 1 else 'ies'} in {suite_dir}:\n")
    for c in sorted(certs, key=lambda c: (c["category"], c["subtype"])):
        score = c.get("verification", {}).get("verification_score", "?")
        print(f"  {c['id']}  {c['category']}/{c['subtype']:<20} {c['title']:<40} score {score}/100")
    print(f"\ncoverage: {', '.join(f'{k}={v}' for k, v in sorted(coverage.items()))}")
    return 0


def cmd_suite_stats(args: argparse.Namespace) -> int:
    """The "is my suite becoming better" view: coverage against the 6 starter
    categories, per-category certification quality, weakest spot, recent
    growth, and one concrete next step -- computed entirely from certificates
    already on disk (no new storage)."""
    from chival_verify import suite

    suite_dir = Path(args.suite_dir)
    certs = suite.list_certificates(suite_dir)
    if not certs:
        empty = suite.suite_stats(certs, now=time.time())
        print(f"no certified tasks yet in {suite_dir}. Suite maturity: {empty['maturity']}")
        print("  chival certify --bug bug.py --fix fix.py --tests tests.py "
              f"--category {suite.KNOWN_CATEGORIES[0]} --subtype <your_subtype>")
        return 0

    stats = suite.suite_stats(certs, now=time.time())
    covered_n, known_n = len(stats["categories_covered"]), len(suite.KNOWN_CATEGORIES)
    print(f"Suite maturity: {stats['maturity']}")
    print(f"  {stats['total']} certified task(s), {covered_n}/{known_n} starter categories covered, "
          f"avg score {stats['avg_score_overall']}/100\n")

    print("Coverage:")
    coverage = suite.coverage_summary(certs)
    for cat in suite.KNOWN_CATEGORIES:
        count = coverage.get(cat, 0)
        bar = "#" * min(count * 8, 40)
        if count:
            avg = stats["avg_score_by_category"][cat]
            print(f"  {cat:<20} {bar:<40} {count} task(s)   avg {avg}/100")
        else:
            print(f"  {cat:<20} {'.':<40} 0 tasks   <- not yet covered")

    if stats["weakest_task"]:
        wt = stats["weakest_task"]
        print(f"\nWeakest certified task: {wt['category']}/{wt['subtype']} "
              f"{wt['title']!r} (score {suite.task_score(wt)}/100)")
    if stats["weakest_category"]:
        cat, avg = stats["weakest_category"]
        print(f"Weakest category on average: {cat} (avg {avg}/100)")
    print(f"Certified in the last 7 days: {stats['certified_last_7d']}")

    if stats["next_recommended_category"]:
        cat = stats["next_recommended_category"]
        print(f"\nNext recommended: certify something in `{cat}` -- your suite has zero coverage there yet.")
        print(f"  chival certify --bug bug.py --fix fix.py --tests tests.py --category {cat} --subtype <your_subtype>")
    else:
        print("\nAll starter categories covered. Keep going with real bugs from your own codebase --"
              " there's no scripted suggestion past this point, only your own regressions.")
    return 0


def cmd_suite_export(args: argparse.Namespace) -> int:
    """Bundle the local suite into one shareable JSON file. No account, no
    upload, no server involved -- `--anonymize` strips free-text titles."""
    from chival_verify import suite

    suite_dir = Path(args.suite_dir)
    certs = suite.list_certificates(suite_dir)
    if not certs:
        print(f"no certified tasks yet in {suite_dir} -- nothing to export.")
        return 1

    bundle = suite.export_bundle(certs, anonymize=args.anonymize)
    out_path = Path(args.out)
    out_path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    mode = "anonymized" if args.anonymize else "as-is"
    print(f"exported {bundle['count']} certified task(s) ({mode}) -> {out_path}")
    print("nothing was uploaded -- this is a local file.")
    return 0


def _print_help_and_succeed(parser: argparse.ArgumentParser):
    """Bare invocation of a command group (`chival`, `chival suite`) shows
    that group's help instead of argparse's terse "the following arguments
    are required" error. Exit 0: nothing went wrong, just no subcommand yet."""
    def _fn(_args: argparse.Namespace) -> int:
        parser.print_help()
        return 0
    return _fn


def _add_execution_args(parser: argparse.ArgumentParser) -> None:
    """--sandbox/--timeout, added AFTER a command's own primary arguments so
    the flags someone actually came here for aren't preceded by two generic
    infra flags every time."""
    parser.add_argument("--sandbox", choices=["auto", "docker", "local"], default="auto",
                        help="execution backend (default: auto — docker if available, else local)")
    parser.add_argument("--timeout", type=float, default=30.0, help="per-run timeout in seconds")


def build_parser() -> argparse.ArgumentParser:
    import chival_verify as _pkg

    p = argparse.ArgumentParser(
        prog="chival",
        description="Mutation-tested, execution-verified regression checks. No LLM judge.",
    )
    p.add_argument("-V", "--version", action="version", version=f"chival-verify {_pkg.__version__}")
    sub = p.add_subparsers(dest="command", required=False)
    p.set_defaults(func=_print_help_and_succeed(p))

    d = sub.add_parser("doctor", help="check your environment and run a smoke evaluation")
    _add_execution_args(d)
    d.set_defaults(func=cmd_doctor)

    g = sub.add_parser("grade", help="grade a submission against a test file")
    g.add_argument("-s", "--submission", help="path to the submission (saved as solution.py)")
    g.add_argument("-t", "--tests", help="path to the pytest file (imports from `solution`)")
    g.add_argument("--example", action="store_true",
                   help="grade a built-in example — zero setup, no files needed")
    g.add_argument("--verbose", action="store_true", help="print the full Outcome (evidence + provenance)")
    _add_execution_args(g)
    g.set_defaults(func=cmd_grade)

    c = sub.add_parser(
        "certify", help="certify your own bug/fix/tests as a permanent, private regression task",
    )
    c.add_argument("--bug", required=True, help="path to the buggy code")
    c.add_argument("--fix", required=True, help="path to the fixed code")
    c.add_argument("--tests", required=True, help="path to the pytest file (imports from `solution`)")
    c.add_argument("--title", default=None, help="short task title (default: derived from category/subtype)")
    c.add_argument("--category", default="general",
                   help="taxonomy category -- e.g. security, database, performance (or your own)")
    c.add_argument("--subtype", default="general", help="taxonomy subtype, e.g. access_control, n_plus_one")
    c.add_argument("--bug-type", default="general", dest="bug_type",
                   help="taxonomy bug type (default: general)")
    c.add_argument("--suite-dir", default=_DEFAULT_SUITE_DIR, dest="suite_dir",
                   help="where certified tasks are saved (default: .chival/suite -- commit it to git)")
    _add_execution_args(c)
    c.set_defaults(func=cmd_certify)

    su = sub.add_parser("suite", help="inspect your local certified regression suite")
    su_sub = su.add_subparsers(dest="suite_command", required=False)
    su.set_defaults(func=_print_help_and_succeed(su))
    _SUITE_DIR_HELP = "where certified tasks are saved (default: .chival/suite -- commit it to git)"

    sl = su_sub.add_parser("list", help="list certified tasks and category coverage")
    sl.add_argument("--suite-dir", default=_DEFAULT_SUITE_DIR, dest="suite_dir", help=_SUITE_DIR_HELP)
    sl.set_defaults(func=cmd_suite_list)

    sst = su_sub.add_parser(
        "stats", help="coverage, quality, growth, and a next-recommended-category suggestion",
    )
    sst.add_argument("--suite-dir", default=_DEFAULT_SUITE_DIR, dest="suite_dir", help=_SUITE_DIR_HELP)
    sst.set_defaults(func=cmd_suite_stats)

    sex = su_sub.add_parser(
        "export", help="bundle certified tasks into one shareable JSON file (nothing is uploaded)",
    )
    sex.add_argument("--suite-dir", default=_DEFAULT_SUITE_DIR, dest="suite_dir", help=_SUITE_DIR_HELP)
    sex.add_argument("--out", default="chival-suite-export.json", help="output file path")
    sex.add_argument("--anonymize", action="store_true",
                     help="strip free-text titles before writing, for sharing the bug pattern only")
    sex.set_defaults(func=cmd_suite_export)

    # Listed last on purpose -- a utility command, not part of the workflow
    # narrative the commands above tell in order.
    v = sub.add_parser("version", help="print the installed version")
    v.set_defaults(func=cmd_version)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
