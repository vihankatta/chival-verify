"""
The Evaluation layer — `Outcome`.

In the Chival hierarchy (World -> Scenario -> Experience -> Trajectory ->
Outcome/Evaluation -> Export), the Outcome is how an experience is *measured*.
It is deliberately domain-neutral: software engineering is V1, but a browser,
cloud, security, or finance World must be able to produce the same object.

Design constraints honored here:

  * NOT a reward wrapper. `reward` is a derived convenience scalar; the object's
    purpose is structured evaluation that can grow to hold capability
    measurements, safety signals, reliability metrics, and per-domain metrics.
  * Raw information is preserved — never collapsed into one number. We keep the
    raw verifier output, the metric dimensions, structured evidence/signals, and
    provenance of how the scalar was derived.
  * No software-engineering fields at the top level. Anything SE-specific
    (tests_total, bug_detection_rate, ...) lives *inside* the generic `metrics`
    dictionary, keyed by name.
  * Extensible without schema churn: dict-based metrics/signals/raw let a domain
    add multiple validators, multiple success criteria, or a different reward
    function later without changing this type.

Each domain supplies its own constructor that maps its verifier into an Outcome.
`from_verification` is the software-engineering mapper; future domains add their
own (e.g. `from_browser_run`) without touching this class.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Verifier identities (provenance).
VERIFIER_DIFFERENTIAL_EXECUTION = "differential_execution"  # dataset certification
VERIFIER_SANDBOX_EXECUTION = "sandbox_execution"            # single-submission grading
# Provenance of how the convenience scalar is derived (so consumers can recompute).
REWARD_BASIS = "verification_score/100 (0.0 if unverified); deterministic"
REWARD_BASIS_PASS_RATE = "fraction of scenario tests passed (0.0 on timeout); deterministic"


@dataclass(frozen=True)
class Outcome:
    """A domain-neutral, deterministic evaluation of one Experience."""

    verified: bool                                     # passed deterministic verification
    reward: float                                      # derived convenience scalar in [0, 1]
    verifier: str = VERIFIER_DIFFERENTIAL_EXECUTION    # provenance: which verifier produced this
    reward_basis: str = REWARD_BASIS                   # provenance: how `reward` was computed
    metrics: dict[str, float] = field(default_factory=dict)   # quantitative dimensions
    signals: dict[str, Any] = field(default_factory=dict)     # structured evidence (non-scalar)
    raw: dict[str, Any] = field(default_factory=dict)         # full raw verifier/score output
    provenance: dict[str, Any] = field(default_factory=dict)  # how this was produced (auditable)

    def to_dict(self) -> dict:
        """Plain dict for exporters / metrics. Domain-neutral by construction."""
        return {
            "verified": self.verified,
            "reward": self.reward,
            "verifier": self.verifier,
            "reward_basis": self.reward_basis,
            "metrics": dict(self.metrics),
            "signals": dict(self.signals),
            "raw": dict(self.raw),
            "provenance": dict(self.provenance),
        }

    # ------------------------------------------------------------------ #
    # Domain mappers. One per domain; this is the software-engineering one.
    # ------------------------------------------------------------------ #
    @classmethod
    def from_verification(cls, verification, score=None) -> "Outcome":
        """
        Map the software-engineering deterministic verifier (and optional quality
        score) into a neutral Outcome. Reads attributes by duck typing so this
        module stays decoupled from the verifier/scoring types.
        """
        verified = bool(getattr(verification, "verified", False))
        vscore = float(getattr(verification, "verification_score", 0) or 0)

        metrics: dict[str, float] = {
            "verification_score": vscore,
            "bug_detection_rate": float(getattr(verification, "bug_detection_rate", 0.0) or 0.0),
            "tests_total": float(getattr(verification, "tests_total", 0) or 0),
            "tests_killed": float(getattr(verification, "tests_killed", 0) or 0),
            "runtime_seconds": float(getattr(verification, "runtime_seconds", 0.0) or 0.0),
        }
        if score is not None and hasattr(score, "quality_score"):
            metrics["quality_score"] = float(score.quality_score)

        signals: dict[str, Any] = {
            "error": getattr(verification, "error", None),
            "adversarial_reason": getattr(verification, "adversarial_reason", None),
            "solution_passed": getattr(verification, "solution_passed", None),
            "bug_caught": getattr(verification, "bug_caught", None),
            "observed_failure": getattr(verification, "observed_failure", "") or "",
        }

        raw: dict[str, Any] = {}
        if hasattr(verification, "to_dict"):
            raw["verification"] = verification.to_dict()
        if score is not None and hasattr(score, "to_dict"):
            raw["score"] = score.to_dict()

        reward = (vscore / 100.0) if verified else 0.0
        return cls(
            verified=verified,
            reward=round(reward, 4),
            verifier=VERIFIER_DIFFERENTIAL_EXECUTION,
            reward_basis=REWARD_BASIS,
            metrics=metrics,
            signals=signals,
            raw=raw,
            provenance={
                "verifier": VERIFIER_DIFFERENTIAL_EXECUTION,
                "method": "differential: solution passes AND buggy fails; graded mutation strength",
                "deterministic": True,
            },
        )

    @classmethod
    def from_run(cls, execution, *, timeout: float | None = None, scenario=None) -> "Outcome":
        """
        Map a single-submission sandbox run (the grader's primitive) into a neutral
        Outcome. Used by the Reward API: a customer's solution is executed against
        a scenario's tests and scored by verifiable pass rate. Reads attributes by
        duck typing so this stays decoupled from the execution/scenario types.

        When a `scenario` is supplied, its success criteria decide `verified` (e.g.
        all_pass vs a pass_rate threshold) and its identity is recorded in
        provenance. `reward` remains the derived pass-rate signal either way — the
        criteria gate the verdict, they do not replace the measurement.

        Evidence is structured and deterministic (per-test statuses + counts); the
        volatile pytest text is intentionally NOT embedded so identical inputs
        yield identical Outcomes.
        """
        per_test: dict[str, str] = dict(getattr(execution, "per_test", {}) or {})
        timed_out = bool(getattr(execution, "timed_out", False))
        passed = int(getattr(execution, "passed", 0) or 0)
        failed = int(getattr(execution, "failed", 0) or 0)
        total = len(per_test) if per_test else (passed + failed)

        suite_ok = bool(getattr(execution, "suite_ok", False))
        pass_rate = (passed / total) if total else 0.0
        reward = 0.0 if timed_out else round(pass_rate, 4)

        # Verdict: default is the clean suite_ok; a scenario's success criteria
        # override it (e.g. a pass_rate threshold) without changing `reward`.
        verified = suite_ok
        provenance: dict[str, Any] = {
            "verifier": VERIFIER_SANDBOX_EXECUTION,
            "method": "single sandbox run of submission against scenario tests",
            "deterministic": True,
            "timeout": timeout,
        }
        if scenario is not None:
            criteria = getattr(scenario, "success", None)
            if criteria is not None and hasattr(criteria, "evaluate"):
                verified = (not timed_out) and bool(criteria.evaluate(pass_rate, suite_ok))
                provenance["success_criteria"] = (
                    criteria.to_dict() if hasattr(criteria, "to_dict") else str(criteria)
                )
            provenance["scenario_id"] = getattr(scenario, "id", None)
            provenance["scenario_fingerprint"] = getattr(scenario, "fingerprint", None)

        metrics: dict[str, float] = {
            "tests_total": float(total),
            "tests_passed": float(passed),
            "tests_failed": float(failed),
            "pass_rate": round(pass_rate, 4),
        }
        signals: dict[str, Any] = {
            "per_test": per_test,                # structured, deterministic evidence
            "failed_tests": sorted(t for t, s in per_test.items() if s == "failed"),
            "timed_out": timed_out,
            "suite_ok": suite_ok,
        }
        raw: dict[str, Any] = {"backend": getattr(execution, "backend", None)}
        return cls(
            verified=verified,
            reward=reward,
            verifier=VERIFIER_SANDBOX_EXECUTION,
            reward_basis=REWARD_BASIS_PASS_RATE,
            metrics=metrics,
            signals=signals,
            raw=raw,
            provenance=provenance,
        )
