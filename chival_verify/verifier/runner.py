"""
Verification runner — differential verification + quality certification.

An example is a (buggy_code -> solution_code) pair plus a test suite. The runner
turns the old binary pass/fail into a graded *certification*:

  Gate 1  solution_code passes every test            (the fix is correct)
  Gate 2  the diff is a real behavioral change        (adversarial check)
  Gate 3  buggy_code is caught by >=1 meaningful test  (mutation strength)
  Gate 4  the test suite isn't trivially weak          (test-quality check)

Surviving examples get a `verification_score` (0-100) built from how robustly
the bug is caught (mutation strength), how thorough the suite is, and how clean
the tests are. The verdict is the gate: only `verified == True` is ever saved.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from chival_verify.models import CodingExample
from chival_verify.verifier import analysis
from chival_verify.verifier.execution import ExecutionResult, failures_only, run_tests
from chival_verify.verifier.sandbox import Sandbox, get_sandbox

# Rejection reason categories (also recorded in dataset / generation reports).
ERR_TIMEOUT = "timeout"                 # solution itself hung
ERR_SOLUTION_FAILED = "solution_failed"  # the "fix" doesn't actually pass
ERR_BUG_NOT_CAUGHT = "bug_not_caught"    # tests don't distinguish bug from fix
ERR_FAKE_BUG = "fake_bug"                # cosmetic / rename-only difference
ERR_WEAK_TESTS = "weak_tests"           # suite too weak / only trivial catch

# Tunables for the quality gate.
MIN_MEANINGFUL_TESTS = 2


@dataclass
class VerificationResult:
    verified: bool
    tests_passed: int          # passing tests in the solution run
    tests_failed: int          # failing tests in the solution run
    runtime_seconds: float     # total across both runs
    backend: str
    error: str | None
    # Differential + mutation signals:
    solution_passed: bool = False
    bug_caught: bool = False
    tests_total: int = 0       # total tests exercised
    tests_killed: int = 0      # tests that pass on fix AND fail on bug
    bug_detection_rate: float = 0.0
    verification_score: int = 0
    adversarial_reason: str = analysis.REASON_NONE
    test_quality_issues: list[str] = field(default_factory=list)
    # Ground truth: the REAL pytest FAILURES block from the buggy run (actual
    # wrong values + traceback), captured from the sandbox — not reconstructed.
    observed_failure: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class Verifier:
    """Runs the differential + certification check for a single example."""

    def __init__(self, sandbox: Sandbox | None = None, timeout: float = 30.0):
        self.sandbox = sandbox or get_sandbox()
        self.timeout = timeout

    def _run(self, code: str, tests: str) -> ExecutionResult:
        # Shared execution primitive — identical to what the grader uses.
        return run_tests(self.sandbox, code, tests, self.timeout)

    def _reject(self, reason: str, sol: ExecutionResult, total: float, **extra) -> VerificationResult:
        return VerificationResult(
            verified=False,
            tests_passed=sol.passed,
            tests_failed=sol.failed,
            runtime_seconds=round(total, 3),
            backend=sol.backend,
            error=reason,
            **extra,
        )

    def verify(self, example: CodingExample) -> VerificationResult:
        # --- Gate 1: the fix must pass cleanly. ------------------------------
        sol = self._run(example.solution_code, example.tests)
        total = sol.runtime
        if sol.timed_out:
            return self._reject(ERR_TIMEOUT, sol, total)
        if not sol.suite_ok:
            return self._reject(ERR_SOLUTION_FAILED, sol, total)

        # --- Gate 2: the difference must be behavioral (adversarial). --------
        adv = analysis.behavioral_difference(example.solution_code, example.buggy_code)
        if adv.is_fake and adv.reason == analysis.REASON_IDENTICAL:
            # Identical AST => no behavioral diff is possible; reject before
            # spending a second sandbox run.
            return self._reject(
                ERR_FAKE_BUG, sol, total,
                solution_passed=True, adversarial_reason=adv.reason,
            )

        # --- Gate 3: the bug must be caught (mutation strength). -------------
        bug = self._run(example.buggy_code, example.tests)
        total += bug.runtime
        tests_total, tests_killed, rate, killing = _mutation_strength(sol, bug)
        bug_caught = tests_killed > 0

        if not bug_caught:
            return self._reject(
                ERR_BUG_NOT_CAUGHT, sol, total,
                solution_passed=True, tests_total=tests_total,
                adversarial_reason=adv.reason,
            )

        if adv.is_fake and adv.reason == analysis.REASON_RENAME:
            # A rename-only change cannot legitimately change behavior; if a test
            # "caught" it, the test is flaky/over-specified -> reject as fake.
            return self._reject(
                ERR_FAKE_BUG, sol, total,
                solution_passed=True, bug_caught=True, tests_total=tests_total,
                tests_killed=tests_killed, bug_detection_rate=rate,
                adversarial_reason=adv.reason,
            )

        # --- Gate 4: the suite must not be trivially weak. ------------------
        tq = analysis.analyze_test_quality(example.tests)
        # Did at least one *non-trivial* test catch the bug?
        nontrivial_catch = (
            any(name not in tq.trivial_names for name in killing) if killing
            else tq.n_meaningful > 0
        )
        if tq.meaningful_tests < MIN_MEANINGFUL_TESTS or not nontrivial_catch:
            return self._reject(
                ERR_WEAK_TESTS, sol, total,
                solution_passed=True, bug_caught=True, tests_total=tests_total,
                tests_killed=tests_killed, bug_detection_rate=rate,
                test_quality_issues=tq.issues,
            )

        # --- Certified. ----------------------------------------------------
        vscore = _verification_score(tests_killed, tests_total, tq)
        return VerificationResult(
            verified=True,
            tests_passed=sol.passed,
            tests_failed=sol.failed,
            runtime_seconds=round(total, 3),
            backend=sol.backend,
            error=None,
            solution_passed=True,
            bug_caught=True,
            tests_total=tests_total,
            tests_killed=tests_killed,
            bug_detection_rate=round(rate, 3),
            verification_score=vscore,
            adversarial_reason=adv.reason,
            test_quality_issues=tq.issues,
            observed_failure=failures_only(bug.output),
        )


def _mutation_strength(sol: ExecutionResult, bug: ExecutionResult):
    """
    Returns (tests_total, tests_killed, detection_rate, killing_test_names).

    A test "kills" the mutant if it PASSES on the fix and FAILS on the bug —
    that's the only evidence the test actually probes the buggy behavior.
    """
    if sol.per_test and bug.per_test:
        sol_pass = {t for t, s in sol.per_test.items() if s == "passed"}
        bug_fail = {t for t, s in bug.per_test.items() if s == "failed"}
        killing = sol_pass & bug_fail
        total = len(sol_pass) or sol.passed
        killed = len(killing)
        rate = killed / total if total else 0.0
        return total, killed, rate, killing

    # Junit unavailable (e.g. buggy crashed at collection): use coarse counts.
    total = sol.passed
    if not bug.suite_ok and bug.passed == 0:
        killed = total  # whole suite broke -> bug catastrophically caught
    else:
        killed = min(bug.failed, total)
    rate = killed / total if total else 0.0
    return total, killed, rate, set()


def _verification_score(tests_killed: int, tests_total: int, tq: analysis.TestQuality) -> int:
    """
    0-100 certification strength:
        50%  discrimination  — robustly caught (>=2 tests) beats a single catch
        25%  thoroughness    — more tests probing the code
        25%  test cleanliness — penalize meaningless / duplicate tests
    """
    discrimination = 1.0 if tests_killed >= 2 else 0.55 if tests_killed == 1 else 0.0
    thoroughness = min(tests_total, 5) / 5
    if tq.n_tests:
        frac_bad = (tq.n_meaningless + tq.n_duplicate) / tq.n_tests
        cleanliness = max(0.0, 1.0 - frac_bad)
    else:
        cleanliness = 0.0
    score = 100 * (0.50 * discrimination + 0.25 * thoroughness + 0.25 * cleanliness)
    return int(max(0, min(100, round(score))))
